# Checking shared Ansible roles

Run the same checks locally and in CI:

```sh
mise run check
```

Global uv selects the interpreter committed in `.python-version`. The check
runtime is locked in `uv.lock`; no project or cloud credentials are needed.
`./make.sh lint` validates YAML, duplicate keys and misplaced task keywords.
`./make.sh test` loads every role and included task file through Ansible and
checks storage placement, teardown guards, secret censorship and Cloud-init
rendering. These checks do not provision infrastructure or execute a deployment.

The CLI source also provides a syntax-only command. With that CLI installed:

```sh
startup ansible validate --playbook tests/roles.yml \
  --inventory tests/inventory.ini --roles-path roles
```

Use a static test inventory to avoid provider lookups. The command uses local
files without refreshing shared roles or resolving a Vault password. It must be
released in the CLI before users of a published installer can invoke it.

## Changed operational behavior

- New k3s installations target `v1.36.5+k3s1` and cert-manager `v1.21.2`.
  Existing clusters retain their versions until an explicit upgrade. Gateway API
  CRDs already managed by the cluster are preserved; an absent Gateway API uses
  `v1.6.1`, and a partial installation stops before overwriting any CRDs.
- Optional Hetzner charts are pinned: cloud controller `1.39.0`, CSI `2.23.0`,
  and cert-manager webhook `0.9.0`. They require provider-specific integration
  verification when enabled.
- Kubernetes Secrets are applied with task output and diffs censored. k3s
  installation tokens are passed through the environment in censored tasks.
- Tailscale OAuth secrets are exchanged on the controller. New nodes receive
  distinct single-use auth keys expiring after ten minutes. Existing joined
  nodes do not request another key. A supplied `tskey-auth-` key retains its
  configured expiry and reuse policy; prefer OAuth for repeatable provisioning.
  Previously provisioned nodes may still hold older OAuth secrets in Cloud-init
  state. This change does not remove or rotate those credentials.
- Surplus workers are preserved unless the CLI invocation explicitly uses
  `--allow-worker-teardown`. The CLI asks for confirmation; `--yes` confirms
  that explicit request for automation. Failed drains stop deletion. Unmanaged
  pods or emptyDir data block a drain; resolve them deliberately before retrying.
  Release the corresponding CLI change before using this option.
- The default Postgres image is pinned to `18.6`; existing project overrides
  remain authoritative. Apply only a patch update within the existing major.
  Backups run once per cluster and are stored with owner-only permissions.
- Postgres records its storage node on the PV and constrains pod scheduling to
  that node. Existing pod placement is adopted. New multi-node databases require
  `postgres_storage_node` set to a Kubernetes node name. Conflicting placement or
  an absent data node stops deployment. This is local storage, without failover;
  node replacement still requires a verified backup and restore.
- DNS zones use a pinned Public Suffix List, including suffixes such as `co.uk`.
  Existing delegated zones are preferred; use `dns_zone_overrides` for an explicit
  zone. Invalid domain or unrelated zone overrides stop before DNS writes.
- Kubernetes modules use a pinned Python client in `/opt/startup-ansible`,
  preserving the distribution Python environment.
- SSH accepts new host keys and rejects changed keys. The public Kubernetes
  API is closed by default. Set `firewall_api_source_ips` to trusted administration
  CIDRs before updating an existing public cluster. SSH stays public by default
  for hosted CI runners; restrict `firewall_ssh_source_ips` for fixed runners.
- Set `cert_manager_acme_email` to an operator-owned ACME contact address if
  contact notifications are wanted. No personal maintainer address is supplied.

## Verification before release

After local checks, exercise a fresh single-node project in an authorized test
account: first install, repeat infrastructure, application deployment, DNS and
HTTPS, backup and restore into a disposable database, then explicit upgrades.
Also verify private-node bootstrap with Tailscale and the ten-minute join-key
window. Static checks do not establish successful provisioning or production
readiness. Review optional charts and provider settings separately.

Shared-role changes reach applications only after `startup sync` updates the
owner's `deploy-your-startup` repository and a CLI run refreshes `.shared-roles`.
