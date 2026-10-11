#!/usr/bin/env bash
# Run `./make.sh test` in the test image and copy the service's coverage file
# out of the container.
#
# Usage: run-tests.sh IMAGE DATABASE_URL COVERAGE_DIR [REQUIRE_COVERAGE]
#
# `./make.sh test` may write `coverage/cobertura.xml` (Cobertura XML) below the
# image's working directory. It is copied to COVERAGE_DIR after the run instead
# of mounting a volume, so the tests may delete and recreate `coverage/` and the
# copy belongs to the runner whatever user the container runs as. A service
# that enables REQUIRE_COVERAGE must produce the report or fail the job.
set -euo pipefail
image="$1"
database_url="$2"
coverage_dir="$3"
require_coverage="${4:-false}"
case "$require_coverage" in true|false) ;; *) echo "Expected require_coverage=true or false" >&2; exit 2 ;; esac
# Never reuse a report left by an earlier run.
mkdir -p "$coverage_dir"
rm -f "$coverage_dir/cobertura.xml"

container="startup-test-$$-$RANDOM"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
workdir="$(docker image inspect --format '{{.Config.WorkingDir}}' "$image")"
workdir="${workdir:-/}"

test_command=test
if [ "$require_coverage" = true ]; then test_command=coverage; fi
echo "Running $test_command in $image"
status=0
docker run --network host --name "$container" \
  -e DATABASE_URL="$database_url" \
  "$image" ./make.sh "$test_command" || status=$?

mkdir -p "$coverage_dir"
if docker cp "$container:${workdir%/}/coverage/cobertura.xml" "$coverage_dir/cobertura.xml" >/dev/null 2>&1; then
  echo "Coverage report: $coverage_dir/cobertura.xml"
elif [ "$status" -eq 0 ] && [ "$require_coverage" = true ]; then
  echo "::error title=Coverage contract::Tests passed but coverage/cobertura.xml is missing."
  exit 1
fi
exit "$status"
