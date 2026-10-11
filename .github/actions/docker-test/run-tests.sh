#!/usr/bin/env bash
# Run `./make.sh test` in the test image and bring the service's coverage file
# out of the container.
#
# Usage: run-tests.sh IMAGE DATABASE_URL COVERAGE_DIR
#
# COVERAGE_DIR is mounted over `coverage/` in the image's working directory, the
# place where `./make.sh test` writes `cobertura.xml` (Cobertura XML). A service
# that writes nothing there simply has no coverage report.
set -euo pipefail
image="$1"
database_url="$2"
coverage_dir="$3"

mkdir -p "$coverage_dir"
# The container user is chosen by the service's Dockerfile and may not be root.
chmod 0777 "$coverage_dir"
workdir="$(docker image inspect --format '{{.Config.WorkingDir}}' "$image")"
workdir="${workdir:-/}"

echo "Running tests in $image"
docker run --network host --rm \
  -e DATABASE_URL="$database_url" \
  -v "$(cd "$coverage_dir" && pwd)":"${workdir%/}/coverage" \
  "$image" ./make.sh test

if [ -f "$coverage_dir/cobertura.xml" ]; then
  echo "Coverage report: $coverage_dir/cobertura.xml"
fi
