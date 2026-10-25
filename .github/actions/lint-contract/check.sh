#!/usr/bin/env bash
# Run the project's pinned `startup lint-contract`. A CLI pin from before the
# command existed only warns, so updating the shared workflow cannot break a
# project; updating deploy-your-startup-cli turns the check on.
set -euo pipefail
cd "${GITHUB_WORKSPACE:-.}"
startup=deployment/.venv/bin/startup
if [ ! -x "$startup" ]; then
  echo "::warning::No startup CLI in deployment/.venv; the lint contract was not checked."
  exit 0
fi
if ! "$startup" lint-contract --help >/dev/null 2>&1; then
  echo "::warning::The pinned startup CLI has no lint-contract command; update deploy-your-startup-cli in deployment/pyproject.toml to enforce the lint contract."
  exit 0
fi
"$startup" lint-contract --project-dir .
