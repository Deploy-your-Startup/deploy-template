"""Exercise the shipped Compose harness and the actual workflow gate."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/actions/container-e2e/run.sh"


@pytest.mark.parametrize("integration,image,e2e,enabled,expected", [
    ("success", "success", "success", "true", 0),
    ("success", "success", "skipped", "false", 0),
    ("failure", "success", "success", "true", 1),
    ("success", "failure", "success", "true", 1),
    ("success", "success", "failure", "true", 1),
    ("success", "success", "cancelled", "true", 1),
    ("success", "success", "skipped", "true", 1),
])
def test_gate_blocks_publish_unless_every_required_job_passes(integration, image, e2e, enabled, expected):
    # GIVEN the real reusable workflow and results from the GitHub boundary
    workflow = yaml.load((ROOT / ".github/workflows/build-and-deploy-service-parallel.yml").read_text(), Loader=yaml.BaseLoader)
    gate = workflow["jobs"]["checks"]
    assert set(gate["needs"]) == {"build", "image", "e2e"}
    assert workflow["jobs"]["publish"]["needs"] == "checks"
    assert workflow["jobs"]["publish"]["if"] == "github.event_name != 'pull_request'"
    # WHEN the exact gate shell executes
    result = subprocess.run(["bash", "-e", "-c", gate["steps"][0]["run"]], env={
        **os.environ, "INTEGRATION_RESULT": integration, "IMAGE_RESULT": image,
        "E2E_RESULT": e2e, "RUN_E2E": enabled,
    }, capture_output=True)
    # THEN failed, cancelled and unexpectedly skipped checks block deployment
    assert result.returncode == expected


@pytest.mark.parametrize("exit_code", [0, 7])
def test_compose_harness_preserves_reports_exit_status_and_cleans_stack(tmp_path, exit_code):
    # GIVEN a real Compose stack whose test process writes a browser report
    docker = subprocess.run(["docker", "info"], capture_output=True)
    if docker.returncode:
        if os.environ.get("STARTUP_REQUIRE_DOCKER_TESTS"):
            pytest.fail("Docker is required in CI")
        pytest.skip("Docker unavailable")
    (tmp_path / "compose.yml").write_text("""services:
  test:
    image: ${E2E_IMAGE}
    environment:
      SHARD_INDEX: ${SHARD_INDEX}
      SHARD_TOTAL: ${SHARD_TOTAL}
    command: [sh, -c, 'mkdir /reports; echo "$$SHARD_INDEX/$$SHARD_TOTAL" > /reports/result.txt; exit EXIT_CODE']
""".replace("EXIT_CODE", str(exit_code)))
    subprocess.run(["docker", "pull", "busybox:1.37"], check=True, capture_output=True, timeout=120)
    output = tmp_path / "reports"
    # WHEN the actual harness runs, including its EXIT trap
    result = subprocess.run(["bash", str(SCRIPT), str(tmp_path), str(output)],
        env={**os.environ, "E2E_IMAGE": "busybox:1.37", "SHARD_INDEX": "2", "SHARD_TOTAL": "2"},
        text=True, capture_output=True, timeout=120)
    # THEN reports survive success and failure and the test status is unchanged
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert (output / "result.txt").read_text().strip() == "2/2"
    assert (output / "compose.log").exists()
    assert "Removed" in result.stderr


def test_invalid_shard_fails_before_starting_any_stack(tmp_path):
    # GIVEN a shard index outside its declared total
    # WHEN the real script runs without even a Compose file
    result = subprocess.run(["bash", str(SCRIPT), str(tmp_path), str(tmp_path / "reports")],
        env={**os.environ, "E2E_IMAGE": "unused", "SHARD_INDEX": "3", "SHARD_TOTAL": "2"},
        text=True, capture_output=True)
    # THEN validation gives a clear failure before any containers start
    assert result.returncode == 2
    assert "1 <= SHARD_INDEX" in result.stderr
    assert not (tmp_path / "reports").exists()
