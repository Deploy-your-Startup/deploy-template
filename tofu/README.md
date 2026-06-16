# tofu/ — OpenTofu provisioning (Phase 1: Hetzner)

This is the provisioning layer for the platform. It replaces the imperative
`roles/hetzner-*` Ansible roles for **creating** cloud resources. Ansible still
owns **configuration** (k3s, Helm, cert-manager, CCM, CSI) and continues to
discover nodes live via `inventory.hcloud.yml` — OpenTofu only creates the
resources and sets the same labels (`ingress=true`, `type=...`) the inventory
plugin filters on. There is no state/IP hand-off between the two.

## Layout

```
tofu/
├── modules/
│   ├── common/      # provider-neutral variable contract (phase-2 reuse)
│   └── hetzner/     # Hetzner module: network, server, firewall, LB, DNS
└── environments/
    └── example/     # copy per project/env, fill terraform.tfvars
```

## What the Hetzner module provisions

| File              | Replaces role            | Resources |
|-------------------|--------------------------|-----------|
| `network.tf`      | `hetzner-network`        | `hcloud_network`, `hcloud_network_subnet` |
| `server.tf`       | `hetzner-server`         | `hcloud_ssh_key`, `hcloud_server`, `hcloud_server_network` |
| `firewall.tf`     | `hetzner-firewall`       | `hcloud_firewall`, `hcloud_firewall_attachment` |
| `loadbalancer.tf` | `hetzner-loadbalancer`   | `hcloud_load_balancer` + target + services |
| `dns.tf`          | `hetzner-dns`            | `hcloud_zone`, `hcloud_zone_rrset` |

DNS uses the **unified Hetzner Cloud DNS API** (`hcloud_zone*`, GA since provider
v1.56) — the same endpoint and `HCLOUD_TOKEN` as everything else, matching the
old `hetzner.hcloud.zone` role. No separate DNS token.

### DNS ownership & the apex guard

Preserved from `roles/hetzner-dns`: a subdomain deployment (`app.example.com`)
never gets `@` or `*` records on the shared root zone — structurally, those are
only emitted for apex domains.

- **Apex domains** (`example.com`) are managed as `hcloud_zone` **resources**
  (this project owns its apex) and get `@` + optional `*`.
- **Parent zones of subdomains** are looked up via `data.hcloud_zone` and must
  already exist in the account — so two project states never fight over one
  shared zone. A missing parent zone fails the plan loudly (intentional
  difference vs the role, which silently skipped).

## Auth

Both provisioning and the (optional) S3 state backend read credentials from the
environment — the CLI injects them from the vault, nothing is written to disk:

- `HCLOUD_TOKEN` — Hetzner Cloud API (compute/network/firewall/LB/DNS),
  from `hcloud_token_<env>`.
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — object-storage creds for the
  S3 state backend (see `environments/example/backend.tf`).

## Manual run (without the CLI)

```bash
cd environments/example
cp terraform.tfvars.example terraform.tfvars   # edit values
export HCLOUD_TOKEN=...                         # do not commit
tofu init
tofu plan
tofu apply
# ... later
tofu destroy
```

State is local until you enable the S3 backend in `backend.tf`.
