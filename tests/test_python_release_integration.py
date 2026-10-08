"""Exercise the real isolated client role after a distribution Python change."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_rebuilds_previous_python_environment_and_preserves_current_one(tmp_path):
    # GIVEN a real Ubuntu 26 environment whose venv has the previous release's
    # site-packages layout. This models the OS boundary without mocking our role.
    if not shutil.which("docker") or subprocess.run(
        ["docker", "info"], capture_output=True, timeout=15
    ).returncode:
        if os.environ.get("STARTUP_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("Docker is required for distribution Python integration")
        pytest.skip("Docker is unavailable")
    name = "startup-python-release-" + uuid.uuid4().hex[:12]

    def docker(*args):
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=300
        )

    try:
        started = docker("run", "-d", "--name", name, "ubuntu:26.04", "sleep", "1200")
        assert started.returncode == 0, started.stderr
        setup = docker("exec", "-e", "DEBIAN_FRONTEND=noninteractive", name,
                       "bash", "-c", "apt-get update -qq && apt-get install -y python3 python3-venv python3-packaging && python3 -m venv /opt/startup-ansible")
        assert setup.returncode == 0, setup.stdout + setup.stderr
        legacy = docker("exec", name, "python3", "-c", """
from pathlib import Path
import sys
p = Path('/opt/startup-ansible')
current = f'python{sys.version_info.major}.{sys.version_info.minor}'
(p / 'lib' / current).rename(p / 'lib/python3.12')
cfg = p / 'pyvenv.cfg'
cfg.write_text('\\n'.join('version = 3.12.3' if line.startswith('version =') else line for line in cfg.read_text().splitlines()) + '\\n')
""")
        assert legacy.returncode == 0, legacy.stdout + legacy.stderr
        assert docker("exec", name, "/opt/startup-ansible/bin/python", "-m", "pip", "--version").returncode != 0
        inventory = {"all": {"hosts": {name: {"ansible_connection": "community.docker.docker", "ansible_python_interpreter": "/usr/bin/python3", "ansible_user": "root"}}}}
        (tmp_path / "inventory.yml").write_text(yaml.safe_dump(inventory))
        (tmp_path / "playbook.yml").write_text(yaml.safe_dump([{"hosts": "all", "gather_facts": False, "roles": [{"role": str(ROOT / "roles/python")}]}]))

        def provision():
            return subprocess.run(
                [str(Path(sys.executable).parent / "ansible-playbook"), "-i", str(tmp_path / "inventory.yml"), str(tmp_path / "playbook.yml")],
                capture_output=True, text=True, timeout=300,
            )

        # WHEN the complete real role prepares the post-upgrade host, THEN
        # its pinned Kubernetes client can be imported with distribution Python.
        result = provision()
        assert result.returncode == 0, result.stdout + result.stderr
        imported = docker("exec", name, "/opt/startup-ansible/bin/python", "-c", "import kubernetes; print(kubernetes.__version__)")
        assert imported.returncode == 0 and imported.stdout.strip() == "36.0.3", imported.stderr
        marker = docker("exec", name, "touch", "/opt/startup-ansible/current-runtime-marker")
        assert marker.returncode == 0, marker.stderr
        # WHEN provision runs again on the same Python release, THEN the
        # current environment is retained rather than cleared on every deploy.
        repeated = provision()
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert docker("exec", name, "test", "-f", "/opt/startup-ansible/current-runtime-marker").returncode == 0
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)
