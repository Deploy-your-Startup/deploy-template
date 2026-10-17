"""Exercise pin dispatch as real processes; GitHub itself exercises the nested action in CI."""
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/scripts/resolve-pinned-action.py'


@pytest.mark.parametrize('action', ['deploy', 'export-shared-roles'])
def test_pin_dispatch_uses_reviewed_revision_and_does_not_persist_secrets(tmp_path, action):
    # GIVEN a consumer with an immutable pin, even after the shared main advances.
    revision = '048869e2e00044c78ebcc9ce5ab80f7a3c350586'
    deployment = tmp_path / 'deployment'
    deployment.mkdir()
    (deployment / 'shared-roles.ref').write_text(revision + '\n')
    # WHEN the shipped resolver runs as it does on a GitHub runner.
    result = subprocess.run(['python3', str(SCRIPT), action], capture_output=True, text=True,
                            env={**os.environ, 'GITHUB_WORKSPACE': str(tmp_path),
                                 'STARTUP_ACTION_REPOSITORY': 'example-owner/deploy-your-startup',
                                 'STARTUP_PIN_VAULT_PASSWORD': 'DISPOSABLE_TEST_PASSWORD'})
    assert result.returncode == 0, result.stderr
    content = (deployment / ('.startup-pinned-' + action) / 'action.yml').read_text()
    metadata = json.loads(content)
    # THEN GitHub loads that repository revision and secrets remain expressions.
    assert metadata['runs']['steps'][0]['uses'] == f'example-owner/deploy-your-startup/.github/actions/{action}@{revision}'
    assert 'DISPOSABLE_TEST_PASSWORD' not in content
    assert metadata['runs']['steps'][0]['with']['_pin-resolved'] == 'true'


@pytest.mark.parametrize('revision', ['main', 'abc', '../../main', 'a' * 40 + '\nmalicious'])
def test_pin_dispatch_rejects_mutable_or_malformed_revisions(tmp_path, revision):
    # GIVEN a mutable or malformed consumer pin.
    (tmp_path / 'deployment').mkdir()
    (tmp_path / 'deployment/shared-roles.ref').write_text(revision)
    # WHEN the real resolver is invoked.
    result = subprocess.run(['python3', str(SCRIPT), 'deploy'], capture_output=True, text=True,
                            env={**os.environ, 'GITHUB_WORKSPACE': str(tmp_path),
                                 'STARTUP_ACTION_REPOSITORY': 'example-owner/deploy-your-startup'})
    # THEN no executable wrapper is emitted.
    assert result.returncode != 0
    assert not (tmp_path / 'deployment/.startup-pinned-deploy').exists()


@pytest.mark.parametrize('history', ['existing-runtime', 'readme-only', 'first-commit'])
def test_synced_workflow_selects_a_pin_that_exists_in_the_owner_repository(tmp_path, history):
    # GIVEN an independent owner repository, whose commit IDs differ from the template.
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Integration Test')
    git('config', 'user.email', 'test@example.invalid')
    if history != 'first-commit':
        (tmp_path / 'README.md').write_text('owner repository\n')
        if history == 'existing-runtime':
            action = tmp_path / '.github/actions/export-shared-roles/action.yml'
            action.parent.mkdir(parents=True)
            action.write_text('name: Earlier runtime\n')
        git('add', '.')
        git('commit', '-m', 'owner history')
        previous = git('rev-parse', 'HEAD')
    action = tmp_path / '.github/actions/export-shared-roles/action.yml'
    action.parent.mkdir(parents=True, exist_ok=True)
    action.write_text('name: Synced runtime\n')
    git('add', '.')
    git('commit', '-m', 'sync')
    expected = previous if history == 'existing-runtime' else git('rev-parse', 'HEAD')
    workflow = yaml.load((ROOT / '.github/workflows/check-pinned-runtime.yml').read_text(), Loader=yaml.BaseLoader)
    # WHEN the actual synced workflow selects its fixture pin.
    script = workflow['jobs']['pinned-runtime']['steps'][1]['run']
    subprocess.run(['bash', '-e', '-c', script], cwd=tmp_path, check=True)
    # THEN it resolves locally even on first adoption, without a template-only SHA.
    selected = (tmp_path / 'deployment/shared-roles.ref').read_text().strip()
    assert selected == expected
    assert git('cat-file', '-t', selected) == 'commit'
