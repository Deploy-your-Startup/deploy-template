#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-help}" in
  # Nothing here is auto-formatted; `format` exists so the make.sh contract
  # (format writes, lint only checks) holds for every repository.
  format) echo "No formatter configured; ./make.sh lint validates role YAML." ;;
  lint) uv run --locked python scripts/check_yaml.py ;;
  # Container lifecycle changes interrupt Chromium on the shared Linux host.
  # Finish parallel scenarios and their teardown before starting any KPI browser.
  test)
    uv run --locked pytest -n auto --dist loadgroup --ignore=tests/test_kpis_runtime_integration.py
    uv run --locked pytest -n0 tests/test_kpis_runtime_integration.py
    ;;
  check) "$0" lint; "$0" test; git diff --check ;;
  *) echo "Usage: ./make.sh {format|lint|test|check}" ;;
esac
