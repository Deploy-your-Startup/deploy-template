#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-help}" in
  lint) uv run --locked python scripts/check_yaml.py ;;
  test) uv run --locked pytest ;;
  check) "$0" lint; "$0" test; git diff --check ;;
  *) echo "Usage: ./make.sh {lint|test|check}" ;;
esac
