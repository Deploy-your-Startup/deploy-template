#!/usr/bin/env bash
# Run `./make.sh test` in the test image and copy the service's coverage file
# out of the container.
#
# Usage: run-tests.sh IMAGE DATABASE_URL COVERAGE_DIR
#
# `./make.sh test` may write `coverage/cobertura.xml` (Cobertura XML) below the
# image's working directory. It is copied to COVERAGE_DIR after the run instead
# of mounting a volume, so the tests may delete and recreate `coverage/` and the
# copy belongs to the runner whatever user the container runs as. A service
# that writes nothing there simply has no coverage report.
set -euo pipefail
image="$1"
database_url="$2"
coverage_dir="$3"

container="startup-test-$$-$RANDOM"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
workdir="$(docker image inspect --format '{{.Config.WorkingDir}}' "$image")"
workdir="${workdir:-/}"

echo "Running tests in $image"
status=0
docker run --network host --name "$container" \
  -e DATABASE_URL="$database_url" \
  "$image" ./make.sh test || status=$?

mkdir -p "$coverage_dir"
if docker cp "$container:${workdir%/}/coverage/cobertura.xml" "$coverage_dir/cobertura.xml" >/dev/null 2>&1; then
  echo "Coverage report: $coverage_dir/cobertura.xml"
fi
exit "$status"
