#!/usr/bin/env bash
# Compose owns services and commands; the harness owns isolation and cleanup.
set -euo pipefail
directory="$1"
reports="$2"
: "${E2E_IMAGE:?Set E2E_IMAGE to a locally loaded image}"
: "${SHARD_INDEX:?Set SHARD_INDEX}"
: "${SHARD_TOTAL:?Set SHARD_TOTAL}"
if ! [[ "$SHARD_INDEX" =~ ^[1-8]$ && "$SHARD_TOTAL" =~ ^[1-8]$ ]] || (( SHARD_INDEX > SHARD_TOTAL )); then
  echo "Expected 1 <= SHARD_INDEX <= SHARD_TOTAL <= 8" >&2
  exit 2
fi
export COMPOSE_PROJECT_NAME="startup-e2e-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-${SHARD_INDEX}-$$"
compose=(docker compose --file "$directory/compose.yml")
mkdir -p "$reports"
cleanup() {
  status=$?
  trap - EXIT
  "${compose[@]}" logs --no-color > "$reports/compose.log" 2>&1 || true
  # Report collection must never hide the original test failure.
  if ! "${compose[@]}" cp test:/reports/. "$reports/"; then
    if [ "$status" -eq 0 ]; then status=1; fi
  fi
  "${compose[@]}" down --volumes --remove-orphans || true
  exit "$status"
}
trap cleanup EXIT
"${compose[@]}" up --no-build --abort-on-container-exit --exit-code-from test
