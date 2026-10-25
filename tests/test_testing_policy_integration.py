"""GIVEN the E2E guide, WHEN following its workflow references, THEN the documented gates exist."""
from pathlib import Path
import re


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
    assert "run_e2e: ${{ inputs.run_e2e }}" in (root / ".github/workflows/verify-service-images.yml").read_text()
    assert "run_e2e" not in direct
    assert "do\nnot call E2E" in guide
    assert "[when E2E runs](e2e-execution.md)" in (root / "docs/testing-policy.md").read_text()
    assert "[E2E execution guide](docs/e2e-execution.md)" in (root / "README.md").read_text()


if __name__ == "__main__":
    test_e2e_execution_documentation()
    print("E2E execution documentation verified")
