"""Select an immutable shared action without giving the job cross-repo credentials."""
import json
import os
from pathlib import Path
import re
import sys

name = sys.argv[1]
workspace = Path(os.environ["GITHUB_WORKSPACE"])
revision = (workspace / "deployment/shared-roles.ref").read_text().strip()
if not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise SystemExit("shared-roles.ref must contain a full Git commit SHA")
repository = os.environ["STARTUP_ACTION_REPOSITORY"]
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
    raise SystemExit("Invalid shared action repository")
inputs = {"_pin-resolved": "true"}
if name == "deploy":
    inputs.update(environment="${{ env.STARTUP_PIN_ENVIRONMENT }}",
                  service="${{ env.STARTUP_PIN_SERVICE }}",
                  vault_password="${{ env.STARTUP_PIN_VAULT_PASSWORD }}")
elif name == "export-shared-roles":
    inputs["destination"] = "${{ env.STARTUP_PIN_DESTINATION }}"
else:
    raise SystemExit("Unknown shared action")
target = workspace / "deployment" / (".startup-pinned-" + name)
target.mkdir(parents=True, exist_ok=True)
# JSON is valid YAML. Keep expressions literal: never persist the Vault password.
(target / "action.yml").write_text(json.dumps({
    "name": "Reviewed shared runtime",
    "description": "Execute the action at the project's immutable role revision",
    "runs": {"using": "composite", "steps": [{
        "uses": repository + "/.github/actions/" + name + "@" + revision,
        "with": inputs,
    }]},
}, indent=2) + "\n")
