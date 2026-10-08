"""Render the shipped deployment and exercise its readiness probe on real Postgres."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_deployment_waits_for_real_database_readiness():
    # GIVEN the real manifest, role arguments and a disposable Postgres server.
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode:
        pytest.skip("Docker is required for database readiness integration")
    variables = yaml.safe_load((ROOT / "roles/postgres/defaults/main.yml").read_text())
    variables.update(postgres_selected_node="local-test", k8s_namespace="default")
    engine = Templar(loader=DataLoader(), variables=variables)
    manifest = yaml.safe_load(engine.template(trust_as_template((ROOT / "roles/postgres/templates/deployment.yml").read_text())))
    tasks = yaml.safe_load((ROOT / "roles/postgres/tasks/main.yml").read_text())
    deployment = next(task["kubernetes.core.k8s"] for task in tasks if task["name"] == "apply postgres deployment")
    # The Ansible gate must observe the Deployment condition fed by this probe,
    # rather than stop at creation of its API resource.
    assert deployment["wait"] is True
    assert deployment["wait_condition"] == {"type": "Available", "status": "True"}
    assert engine.template(trust_as_template(deployment["wait_timeout"])) >= 60
    container = "startup-ready-check-" + uuid.uuid4().hex[:12]
    spec = manifest["spec"]["template"]["spec"]["containers"][0]
    probe = spec["readinessProbe"]["exec"]["command"]
    try:
        created = subprocess.run(["docker", "run", "-d", "--name", container, "--network", "none",
                                  "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_USER=readiness_check", spec["image"]],
                                 capture_output=True, text=True, timeout=120)
        assert created.returncode == 0, created.stderr
        # WHEN the real readiness probe is retried, THEN it only succeeds when
        # Postgres is accepting connections with the rendered environment.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = subprocess.run(["docker", "exec", container, *probe], capture_output=True, text=True)
            if result.returncode == 0:
                assert "accepting connections" in result.stdout
                break
            time.sleep(1)
        else:
            pytest.fail("Rendered Postgres readiness probe never became healthy")
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True)
