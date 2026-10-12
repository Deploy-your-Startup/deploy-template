"""Execute both shipped CI exports against real role and playbook files."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("action_name", ["deploy", "export-shared-roles"])
def test_ci_export_preserves_the_complete_pinned_runtime(tmp_path, action_name):
    # GIVEN the real action checkout and an isolated consumer workspace.
    action_dir = ROOT / ".github/actions" / action_name
    action = yaml.safe_load((action_dir / "action.yml").read_text())
    export = next(step["run"] for step in action["runs"]["steps"]
                  if step.get("name") in {"Export shared Ansible roles", "Export shared roles"})
    export = export.replace("${{ github.workspace }}", str(tmp_path))
    # WHEN GitHub's actual export shell step runs.
    result = subprocess.run(["bash", "-c", export], capture_output=True, text=True,
                            env={**os.environ, "ACTION_REPO_ROOT": str(action_dir),
                                 "GITHUB_WORKSPACE": str(tmp_path),
                                 "DESTINATION_DIR": "deployment/.shared-roles"})
    assert result.returncode == 0, result.stdout + result.stderr
    # THEN both entry points export exactly the runtime covered by a role pin.
    target = tmp_path / "deployment/.shared-roles"
    expected = {path.relative_to(ROOT): path.read_bytes()
                for path in (ROOT / "roles").rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    for name in ["ansible.cfg", "requirements.yml", "inventory.ini", "inventory.hcloud.yml",
                 "backup-playbook.yml", "restore-playbook.yml", "update-vms-playbook.yml",
                 "os-upgrade-playbook.yml", "k3s-upgrade-playbook.yml", "dns-playbook.yml"]:
        path = ROOT / name
        if path.exists():
            expected[Path(name)] = path.read_bytes()
    actual = {path.relative_to(target): path.read_bytes() for path in target.rglob("*")
              if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    assert actual == expected
