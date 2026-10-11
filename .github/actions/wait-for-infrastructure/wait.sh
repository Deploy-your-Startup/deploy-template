#!/usr/bin/env bash
set -euo pipefail

# BYOS is provisioned explicitly by its owner; pitch has no infrastructure.
if [ -f deployment/inventory.byos.yml ] || [ ! -f .github/workflows/deploy-infrastructure.yml ]; then
  echo "No managed infrastructure workflow to wait for."
  exit 0
fi

case "${STARTUP_WAIT_MINUTES:-30}" in
  ''|*[!0-9]*) echo "::error::timeout_minutes must be a non-negative integer."; exit 1 ;;
esac
deadline=$(( SECONDS + 10#${STARTUP_WAIT_MINUTES:-30} * 60 ))
while :; do
  # The first push can reach this step before bootstrap dispatches provisioning.
  if ! latest="$(gh api \
    "repos/${GITHUB_REPOSITORY}/actions/workflows/deploy-infrastructure.yml/runs?branch=${GITHUB_REF_NAME}&per_page=20" \
    --jq '.workflow_runs | sort_by(.created_at) | reverse | if length == 0 then "none" else .[0] | [.id, .status, (.conclusion // "pending")] | @tsv end' 2>/dev/null)"; then
    echo "::error::Cannot read infrastructure runs. Check GitHub availability and actions: read permissions."
    exit 1
  fi
  if [ "$latest" != none ]; then
    IFS=$'\t' read -r run_id status conclusion <<< "$latest"
    case "$status" in
      completed)
        if [ "$conclusion" = success ]; then
          echo "Infrastructure run $run_id succeeded."
          exit 0
        fi
        echo "::error::Infrastructure run $run_id ended with $conclusion. Fix and rerun infrastructure before deploying."
        exit 1 ;;
      queued|in_progress|waiting|pending|requested) ;;
      *) echo "::error::Unexpected infrastructure run response."; exit 1 ;;
    esac
  elif [ -f .github/workflows/deploy.yml ]; then
    # Existing projects may have been provisioned locally, or their infrastructure
    # run may have expired. A successful application deployment is durable enough
    # evidence while retained by GitHub; never override an actual infrastructure run.
    if ! deployed="$(gh api \
      "repos/${GITHUB_REPOSITORY}/actions/workflows/deploy.yml/runs?branch=${GITHUB_REF_NAME}&status=success&per_page=100" \
      --jq '.workflow_runs | map(select(.conclusion == "success" and (.event == "push" or .event == "workflow_dispatch"))) | if length == 0 then "none" else .[0].id | tostring end' 2>/dev/null)"; then
      echo "::error::Cannot read previous deployments. Check GitHub availability and actions: read permissions."
      exit 1
    fi
    if [[ "$deployed" =~ ^[0-9]+$ ]]; then
      echo "Deployment run $deployed succeeded; existing infrastructure is already provisioned."
      exit 0
    elif [ "$deployed" != none ]; then
      echo "::error::Unexpected deployment run response."
      exit 1
    fi
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::No successful infrastructure run within ${STARTUP_WAIT_MINUTES:-30} minutes. Deployment stopped."
    exit 1
  fi
  echo "Waiting for successful infrastructure ..."
  sleep 20
done
