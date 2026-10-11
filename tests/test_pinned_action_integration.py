"""Exercise pin dispatch as real processes; GitHub itself exercises the nested action in CI."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/scripts/resolve-pinned-action.py'


@pytest.mark.parametrize('action', ['deploy', 'export-shared-roles'])
def test_pin_dispatch_uses_reviewed_revision_and_does_not_persist_secrets(tmp_path, action):
    # GIVEN a consumer with an immutable pin, even after the shared main advances.
    revision = 'a9e785324a2574989b943231cd29157193a67c12'
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
