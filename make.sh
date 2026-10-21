#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-help}" in
  # Nothing here is auto-formatted; `format` exists so the make.sh contract
  # (format writes, lint only checks) holds for every repository.
  format) echo "No formatter configured; ./make.sh lint validates role YAML." ;;
  lint) uv run --locked python scripts/check_yaml.py ;;
  # Workers share one Docker daemon; scenarios keep their own names and ports.
  test) uv run --locked pytest -n auto --dist loadgroup ;;
  check) "$0" lint; "$0" test; git diff --check ;;
  *) echo "Usage: ./make.sh {format|lint|test|check}" ;;
esac
