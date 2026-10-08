"""Execute the shipped script; GitHub and clock boundaries use local stand-ins."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def launch(tmp_path, responses, *, minutes="1", byos=False, managed=True):
    directory = tmp_path / "bin"
    directory.mkdir()
    (tmp_path / "responses").write_text("\n".join(responses) + "\n")
    gh = directory / "gh"
    gh.write_text('''#!/usr/bin/env python3
import os,pathlib
root=pathlib.Path(os.environ['WAIT_TEST_ROOT'])
counter=root/'counter'
i=int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(i+1))
lines=(root/'responses').read_text().splitlines()
value=lines[min(i,len(lines)-1)]
if value=='API_ERROR': raise SystemExit(1)
print(value)
''')
    gh.chmod(0o755)
    sleep = directory / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    if managed:
        (workflows / "deploy-infrastructure.yml").write_text("name: Infrastructure\n")
    if byos:
        (tmp_path / "deployment").mkdir()
        (tmp_path / "deployment/inventory.byos.yml").write_text("all: {}\n")
    return subprocess.run(
        ["bash", str(ROOT / ".github/actions/wait-for-infrastructure/wait.sh")],
        cwd=tmp_path, text=True, capture_output=True, timeout=10,
        env={**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"],
             "WAIT_TEST_ROOT": str(tmp_path), "STARTUP_WAIT_MINUTES": minutes,
             "GITHUB_REPOSITORY": "example/startup", "GITHUB_REF_NAME": "main"},
    )


def test_initial_dispatch_race_waits_until_success(tmp_path):
    # GIVEN an initial push before dispatch, WHEN provisioning completes,
    # THEN the real script only proceeds after success.
    result = launch(tmp_path, ["none", "42\tqueued\tpending", "42\tin_progress\tpending", "42\tcompleted\tsuccess"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "succeeded" in result.stdout
    assert (tmp_path / "counter").read_text() == "4"


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped"])
def test_failed_infrastructure_stops_deploy(tmp_path, conclusion):
    # GIVEN an unsuccessful run, WHEN waiting, THEN deployment fails.
    result = launch(tmp_path, [f"42\tcompleted\t{conclusion}"])
    assert result.returncode == 1
    assert conclusion in result.stdout


@pytest.mark.parametrize("response", ["none", "42\tin_progress\tpending"])
def test_timeout_never_continues_anyway(tmp_path, response):
    # GIVEN unfinished provisioning, WHEN the deadline expires, THEN stop.
    result = launch(tmp_path, [response], minutes="0")
    assert result.returncode == 1
    assert "Deployment stopped" in result.stdout


@pytest.mark.parametrize("response", ["API_ERROR", "garbled"])
def test_unreadable_runs_fail_closed(tmp_path, response):
    # GIVEN an API error or malformed output, WHEN querying, THEN fail closed.
    result = launch(tmp_path, [response])
    assert result.returncode == 1


@pytest.mark.parametrize("byos,managed", [(True, True), (False, False)])
def test_unmanaged_projects_do_not_query_infrastructure(tmp_path, byos, managed):
    # GIVEN BYOS or pitch, WHEN waiting, THEN no cloud workflow is required.
    result = launch(tmp_path, ["API_ERROR"], byos=byos, managed=managed)
    assert result.returncode == 0
    assert not (tmp_path / "counter").exists()
