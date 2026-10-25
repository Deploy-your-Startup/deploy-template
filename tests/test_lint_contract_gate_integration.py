"""Run the shipped lint-contract gate script against stand-in CLI pins."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/actions/lint-contract/check.sh'


def project_with_cli(tmp_path, body):
    """A project whose deployment venv holds a stand-in for the pinned startup CLI."""
    if body is not None:
        startup = tmp_path / 'deployment/.venv/bin/startup'
        startup.parent.mkdir(parents=True)
        startup.write_text('#!/bin/sh\necho "$*" >> "$GITHUB_WORKSPACE/calls"\n' + body)
        startup.chmod(0o755)
    return tmp_path


def gate(project):
    return subprocess.run(['bash', str(SCRIPT)], capture_output=True, text=True, timeout=30,
                          env={**os.environ, 'GITHUB_WORKSPACE': str(project)})


def test_supported_cli_failure_blocks_the_workflow(tmp_path):
    # GIVEN a pinned CLI with lint-contract that reports a broken contract.
    project = project_with_cli(tmp_path, (
        '[ "$1 $2" = "lint-contract --help" ] && exit 0\n'
        'echo "backend/make.sh: add set -e"; exit 1\n'))
    # WHEN the gate runs as the shared workflow step.
    result = gate(project)
    # THEN the CLI ran on the project root and its failure fails the step.
    assert result.returncode == 1
    assert 'backend/make.sh: add set -e' in result.stdout
    assert 'lint-contract --project-dir .' in (project / 'calls').read_text()


def test_supported_cli_pass_lets_the_workflow_continue(tmp_path):
    # GIVEN a pinned CLI whose contract check passes.
    project = project_with_cli(tmp_path, 'exit 0\n')
    # WHEN the gate runs.
    result = gate(project)
    # THEN the step succeeds without warnings.
    assert result.returncode == 0, result.stderr
    assert '::warning::' not in result.stdout


def test_older_cli_pin_warns_instead_of_breaking_the_project(tmp_path):
    # GIVEN a CLI pin from before lint-contract existed (click exits 2 on unknown commands).
    project = project_with_cli(tmp_path, 'echo "No such command" >&2; exit 2\n')
    # WHEN the gate runs after a shared workflow update.
    result = gate(project)
    # THEN the run continues and the warning names the fix.
    assert result.returncode == 0
    assert '::warning::The pinned startup CLI has no lint-contract command' in result.stdout


def test_project_without_deployment_cli_warns(tmp_path):
    # GIVEN a project without an installed deployment CLI.
    # WHEN the gate runs.
    result = gate(project_with_cli(tmp_path, None))
    # THEN the unchecked contract is visible, not silently passed.
    assert result.returncode == 0
    assert '::warning::No startup CLI in deployment/.venv' in result.stdout
