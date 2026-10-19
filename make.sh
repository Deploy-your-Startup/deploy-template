#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-help}" in
  lint) uv run --locked python scripts/check_yaml.py ;;
  # Workers share one Docker daemon; scenarios keep their own names and ports.
  test) uv run --locked pytest -n auto --dist worksteal ;;
  check) "$0" lint; "$0" test; git diff --check ;;
  *) echo "Usage: ./make.sh {lint|test|check}" ;;
esac
