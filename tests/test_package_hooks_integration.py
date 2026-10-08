"""Use real Ubuntu apt; its service-restart boundary rejects uncontrolled restarts."""
from pathlib import Path
import shutil
import subprocess
import uuid

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_python_packages_do_not_restart_services_mid_provision(tmp_path):
    # GIVEN a disposable Ubuntu host whose package hook requires controlled
    # restart mode, as cloud-init cannot be safely restarted during setup.
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode:
        pytest.skip("Docker is required for real Ubuntu package integration")
    container = "startup-package-check-" + uuid.uuid4().hex[:12]
    def docker(*args, **kwargs):
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=240, **kwargs)
    try:
        created = docker("run", "-d", "--name", container, "ubuntu:24.04", "sleep", "600")
        assert created.returncode == 0, created.stderr
        prepared = docker("exec", container, "bash", "-c", "apt-get update -qq && printf '%s\\n' 'DPkg::Post-Invoke {\"test x$NEEDRESTART_MODE = xl\";};' > /etc/apt/apt.conf.d/99startup-restart-boundary")
        assert prepared.returncode == 0, prepared.stderr
        tasks = yaml.safe_load((ROOT / "roles/python/tasks/main.yml").read_text())
        task = next(t for t in tasks if "ansible.builtin.apt" in t)
        packages = task["ansible.builtin.apt"]["name"]
        # WHEN the real package manager runs without the fix, THEN its hook
        # refuses the uncontrolled restart and the provision fails.
        baseline = docker("exec", "-e", "DEBIAN_FRONTEND=noninteractive", container, "apt-get", "-y", "install", *packages)
        assert baseline.returncode != 0
        # WHEN it runs with the actual role's environment, THEN installation
        # succeeds and the requested packages are present.
        environment = [item for k, v in task.get("environment", {}).items() for item in ("-e", f"{k}={v}")]
        fixed = docker("exec", *environment, "-e", "DEBIAN_FRONTEND=noninteractive", container, "apt-get", "-y", "--reinstall", "install", *packages)
        assert fixed.returncode == 0, fixed.stdout + fixed.stderr
        installed = docker("exec", container, "dpkg-query", "-W", "-f=${Status}\\n", *packages)
        assert installed.returncode == 0
        assert installed.stdout.count("install ok installed") == len(packages)
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True)
