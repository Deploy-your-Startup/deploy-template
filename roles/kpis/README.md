# kpis

Deploy self-hosted, cookieless KPI tracking using the pinned upstream Umami
image (`3.4.0`). There is no application source, Dockerfile or build workflow.
Security updates reach consumers through `startup sync` and a reviewed project
shared-role pin. Replays and heatmaps stay off.

Projects guard the role in their own playbook; the role does not define a toggle:

```yaml
- name: Deploy KPI tracking
  ansible.builtin.import_role:
    name: kpis
  when: kpis_enabled | default(false)
  tags: kpis
```

The same guard works with `include_role`. New projects from the application
template will default `kpis_enabled` to `true`. Disabling the toggle skips the
role; it does not remove existing resources or data.

## Configuration

Set these variables in project `deployment/group_vars`:

| Variable | Required value |
| --- | --- |
| `kpis_enabled` | `true` to include the role |
| `base_domain` | Public base domain, for example `example.com` |
| `project_name` | Website display name, for example `sample-startup` |
| `kpis_website_id` | Stable public UUID for the tracked website |
| `kpis_db_password` | Non-empty dedicated database password, stored in Vault |
| `kpis_app_secret` | Non-empty application signing secret, stored in Vault |
| `kpis_admin_password` | Admin password of at least 16 characters, stored in Vault |

The three Vault secrets are generated at bootstrap. Read the admin password with:

```bash
startup secrets get-field -f deployment/group_vars/production.yml --field kpis_admin_password
```

The role requires the existing Postgres Service and `postgres` Secret containing
`admin_username` and `admin_password` in the same namespace. Set `postgres_host`,
`postgres_port`, and `postgres_version` to match that deployment. The init
container creates the dedicated database/user and updates its password.

Defaults are `kpis_host: "kpis.{{ base_domain }}"`, `kpis_db_name: kpis_db`,
`kpis_db_user: kpis_db_user`, and `kpis_version: "3.4.0"`; override them in
group_vars as needed. `k8s_namespace` defaults to `default` when absent.
Provide DNS for the host, the namespace's `letsencrypt-prod` issuer and
`redirect-to-https` middleware.

## Safe first run

Before applying anything, the role validates the website UUID and secrets.
The public ingress exposes only `/api/heartbeat` during bootstrap. Through the
cluster-internal Service, the role replaces the default `admin/umami` password
and verifies the configured login. Only then does it publish the full HTTPS
ingress and create the website with `kpis_website_id` via the API if missing.
The Ansible host must be able to reach the Service's ClusterIP. Failed password
bootstrap leaves the UI closed. Password and token tasks use `no_log`; Secret
application also disables diff. Pod credentials come from the Secret, never args.

## Frontend contract and funnel

Configure the frontend runtime values:

```text
KPIS_SCRIPT_URL=https://<kpis host>/script.js
KPIS_WEBSITE_ID=<kpis_website_id>
```

For the default host, the script URL is `https://kpis.example.com/script.js`.
When tracking is disabled, clear both values and omit the tracking script.
Respect Do Not Track in the frontend. Upstream telemetry is disabled in the pod.

Use the standard funnel `visit → cta_click → signup → activation → return`.
`visit` is the automatic page view; do not duplicate it with a custom event.
Use `cta_click` for key actions, `signup` for account creation, `activation` for
the first meaningful success, and `return` for a returning product user.
