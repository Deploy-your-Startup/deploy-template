"""GIVEN portable instructions, WHEN following their link, THEN the test policy is explicit."""
from pathlib import Path
import re


def test_portable_testing_policy():
    # GIVEN this real standalone repository and its agent entrypoint.
    root = Path(__file__).resolve().parents[1]
    instructions = (root / "AGENTS.md").read_text()
    # WHEN a contributor follows the test-policy link.
    target = re.search(r"\[Testing policy and completion evidence\]\(([^)]+)\)", instructions)
    assert target is not None
    policy = (root / target.group(1)).read_text()
    # THEN required flow coverage, the limited exception and honest evidence survive.
    assert "Integration tests are the default" in policy
    assert "Unit tests are reserved for complex algorithms" in policy
    assert "Every enabled shard must succeed" in policy
    assert "not a pass" in policy
    assert "Record uncovered flows" in policy
    for old_rule in ("Never write unit tests", "never unit tests", "No unit tests:"):
        assert old_rule not in instructions


def test_e2e_execution_documentation():
    # GIVEN the real shared workflow and its public documentation.
    root = Path(__file__).resolve().parents[1]
    guide = (root / "docs/e2e-execution.md").read_text()
    # WHEN following the guide's local workflow references.
    links = re.findall(r"\]\((\.\./[^)]+)\)", guide)
    assert len(links) == 4
    for link in links:
        assert (root / "docs" / link).is_file(), link
    parallel = (root / ".github/workflows/build-and-deploy-service-parallel.yml").read_text()
    direct = (root / ".github/workflows/deploy.yml").read_text()
    # THEN documented gate controls exist and direct deploy has no E2E job.
    assert "run_e2e:" in parallel
    assert "if: inputs.run_e2e" in parallel
    assert "run_e2e" not in direct
    assert "do\nnot call E2E" in guide
    assert "[when E2E runs](e2e-execution.md)" in (root / "docs/testing-policy.md").read_text()
    assert "[E2E execution guide](docs/e2e-execution.md)" in (root / "README.md").read_text()


if __name__ == "__main__":
    test_portable_testing_policy()
    test_e2e_execution_documentation()
    print("Portable agent instructions and testing policy verified")
