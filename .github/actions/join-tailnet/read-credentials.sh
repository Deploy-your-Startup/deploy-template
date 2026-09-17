#!/usr/bin/env bash
# Decide whether this deploy needs the tailnet, and if so, read the CI OAuth
# client from the vault. Writes `mode`, and in private mode the credentials, to
# $GITHUB_OUTPUT. Runs in the project's deployment/ directory.
#
# Env: ENVIRONMENT, VAULT_PASSWORD, GITHUB_OUTPUT
set -euo pipefail

# Same precedence as Ansible: the environment file overrides all.yml.
# `|| true` is load-bearing: projects that predate this mode have no
# network_mode line, grep exits 1 on that, and pipefail would fail every deploy.
mode="$({ grep -hE '^network_mode:' group_vars/all.yml "group_vars/${ENVIRONMENT}.yml" 2>/dev/null || true; } \
  | tail -n 1 | sed -E "s/^network_mode:[[:space:]]*['\"]?([a-z]+).*/\1/")"
mode="${mode:-public}"
echo "mode=$mode" >> "$GITHUB_OUTPUT"

if [ "$mode" != "private" ]; then
  exit 0
fi

read_field() {
  local value="" file
  for file in "group_vars/${ENVIRONMENT}.yml" group_vars/all.yml; do
    [ -f "$file" ] || continue
    value="$(startup secrets get-field -f "$file" --field "$1" -p "$VAULT_PASSWORD" 2>/dev/null || true)"
    [ -n "$value" ] && break
  done
  if [ -z "$value" ]; then
    echo "::error::network_mode is private, but $1 is not set in group_vars. Vault it with 'startup secrets update --field-stdin $1'." >&2
    exit 1
  fi
  printf '%s' "$value"
}

client_id="$(read_field tailscale_ci_oauth_client_id)"
secret="$(read_field tailscale_ci_oauth_secret)"
echo "::add-mask::$client_id"
echo "::add-mask::$secret"
{
  echo "oauth_client_id=$client_id"
  echo "oauth_secret=$secret"
} >> "$GITHUB_OUTPUT"
