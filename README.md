# Deploy Your Startup — shared deployment foundation

This repository contains the shared deploy workflows, composite actions, and
Ansible roles that Deploy Your Startup users sync into their own private
`deploy-your-startup` repository.

It combines the reusable GitHub Actions logic with the shared deployment assets
so projects can reuse one deployment foundation for each new startup. Workflows
and infrastructure remain in the user's own accounts and are open to
customization. Services provide their own build, lint and test commands, keeping
shared deployment independent of application languages.

**Harness Engineering for startups: Speed, Control and Scalability.**
Build quickly with reusable agent instructions, tools and automated checks,
while keeping ownership and room to grow.

Part of [Deploy Your Startup](https://deploy-your-startup.com). For your first
application, follow the [CLI quickstart](https://github.com/Deploy-your-Startup/cli#your-first-startup).
Contributor conventions live in [AGENTS.md](AGENTS.md).

## Available Workflows

### Generic Service Build and Deploy
- **File**: `.github/workflows/build-and-deploy-service.yml`
- **Type**: Reusable workflow
- **Features**:
  - Generic workflow for building and deploying any service
  - Configurable service name
  - Optional testing and linting through `./make.sh test` and `./make.sh lint`
  - Pull requests build and check without pushing images or deploying
  - Optional multi-platform support (amd64/arm64)
  - Standardized Docker image building and pushing
  - Deployment to configured environments

### Parallel container checks

`.github/workflows/build-and-deploy-service-parallel.yml` keeps the service
inputs of the original workflow and adds `run_e2e`, `e2e_shards` (1–8, default
2) and `e2e_directory` (default `e2e_tests`). Adopt it after syncing a release
that contains this workflow. Existing callers can keep the original workflow.

Integration checks and the production image build run concurrently. With
`run_e2e: true`, browser checks also run before the required-checks gate. A
failed, cancelled or unexpectedly skipped check prevents publication and
deployment. Pull requests never publish or deploy. The production image is
exported as an OCI archive and published after the gate without rebuilding it.
Build caches are scoped per service and target.

The E2E directory supplies two small files:

- `Dockerfile`, built with the **repository root** as its context. It contains
  the project's test tools and application dependencies, separate from the
  production image. The image is built once and transferred to each shard.
- `compose.yml`, with a `test` service using `${E2E_IMAGE}` and the local
  dependencies it needs. Do not publish fixed host ports or use external/shared
  volumes. Each shard receives its own Compose project and database.

The test service receives `SHARD_INDEX` and `SHARD_TOTAL` through Compose. Its
project-owned command translates these into the test runner's options and
writes diagnostics and any coverage to `/reports`. The shared harness knows
no application language or browser framework. It preserves reports on failure
and removes the disposable stack afterwards. Application test commands must
return nonzero on failure. Use one worker per shard until tests support multiple
isolated databases. E2E artifacts are separate from integration coverage; their
percentages are not added or averaged.

Include application, E2E, Docker context and workflow paths in the caller's
triggers. For multi-service applications, every deployable service must wait
for the E2E gate; a separate unconnected E2E workflow does not block deployment.

### Deployment
- **File**: `.github/workflows/deploy.yml`
- **Type**: Reusable workflow (`workflow_call`)
- **Triggers**: Called by the project's own workflow; define push/manual triggers there
- **Features**:
  - Can be reused in other workflows
  - Deploys the services configured in the project playbook

### Infrastructure Deployment
- **File**: `.github/workflows/deploy-infrastructure.yml`
- **Type**: Reusable workflow and standalone workflow
- **Triggers**: Manual workflow dispatch
- **Features**:
  - Can be reused in other workflows
  - Deploys infrastructure changes via Ansible

## Custom Actions

### Deploy Action
- **Location**: `.github/actions/deploy/action.yml`
- **Purpose**: Standardized deployment mechanism using Ansible
- **Features**:
  - Environment selection
  - Service-specific deployment
  - Vault integration for secrets management
  - SSH key management for secure deployments

### Join Tailnet Action
- **Location**: `.github/actions/join-tailnet/action.yml`
- **Purpose**: Put the runner on the tailnet for projects in private network mode
- **Features**:
  - No-op unless `network_mode: private` (environment file overrides `all.yml`)
  - Reads the CI OAuth client from the vault and masks it
  - Used by the Deploy Action; see "Private Network Mode" below

### Export Shared Roles Action
- **Location**: `.github/actions/export-shared-roles/action.yml`
- **Purpose**: Copy the bundled shared roles into `deployment/.shared-roles`
- **Features**:
  - Exports `roles/`, `requirements.yml`, `backup-playbook.yml`, and `restore-playbook.yml`
  - Keeps CI secret-free for shared roles access

### Docker Test Action
- **Location**: `.github/actions/docker-test/action.yml`
- **Purpose**: Build Docker image for testing and run tests inside the container
- **Features**:
  - Builds Docker image up to the test stage
  - Runs tests in a container with database connection
  - Uses make.sh script for test execution
  - Copies `coverage/cobertura.xml` out of the test container and returns
    `coverage_file` when `./make.sh test` wrote it

### Coverage Report Action
- **Location**: `.github/actions/coverage-report/action.yml`
- **Purpose**: Show test coverage per service without knowing the service's language
- **Features**:
  - Reads only Cobertura XML, the file a service's `./make.sh test` may write to
    `<service>/coverage/cobertura.xml`
  - Adds line and branch rates to the job summary and keeps one pull request
    comment per service up to date
  - Shows the supplied `measured_from` test suites beside each service;
    reports without this label show `Not specified`
  - Optional by default; `required: true` fails on missing or invalid reports.
    No percentage threshold is enforced
  - Uses a small Python script in this repository; no third-party action or
    external coverage service

### Docker Build and Push

The generic service workflow calls `docker/build-push-action` directly. Configure
`platforms` (for example `linux/amd64,linux/arm64`) on the reusable workflow;
there is no separate bundled Docker build/push action.

### Wait for Infrastructure Action
- **Location**: `.github/actions/wait-for-infrastructure/action.yml`
- **Purpose**: Wait for an active infrastructure run before deploying services

### Setup Environment Action
- **Location**: `.github/actions/setup-environment/action.yml`
- **Purpose**: Sets up the CI environment for build and deployment
- **Features**:
  - Repository checkout
  - Environment preparation

## Service Requirements

For a service to work with these workflows, it needs to include:

1. **Dockerfile** with the following:
   - A `test` stage/target for running tests
   - A production build stage for the final image

2. **make.sh** script with the following commands:
   - `test` command when `run_tests: true`
   - `lint` command when `run_lint: true` (checks only, no changes)
   - `format` command for local formatting and fixes
   - `run` command for starting the service
   - The script must be executable and located at the root of the service directory

Example minimal Dockerfile structure:
```dockerfile
FROM base-image:version as builder
# Build steps...

FROM builder as test
# Copy test files
COPY . .
# Setup for testing
RUN npm install
# Tests will be executed by calling make.sh test

FROM builder as production
# Final production image setup
...
# Start the service when container runs
CMD ["./make.sh", "run"]
```

Example make.sh script:
```bash
#!/bin/bash
set -e

case "$1" in
  test)
    echo "Running tests..."
    npm test
    ;;
  lint)
    npm run format:check
    npm run lint
    ;;
  format)
    npm run format
    npm run lint:fix
    ;;
  run)
    echo "Starting service..."
    node server.js
    ;;
  *)
    echo "Unknown command: $1"
    exit 1
    ;;
esac
```

## Usage in Your Projects

Run `startup sync` to copy this template into your own private
`<github-owner>/deploy-your-startup` repository. Projects resolve shared roles
from that user copy. Editing this template alone does not update projects;
run `startup sync` again after the upstream change is available, then let
`startup ansible setup_ansible` refresh the local checkout. Do not hand-edit
`deployment/.shared-roles`.

The `§§deploy_your_startup.*§§` placeholders below are rendered by sync. In a
project workflow, replace them with your GitHub owner and shared repository name.
Enable `run_lint` only after the service implements `./make.sh lint`; it defaults
to false. Caller workflows need a `pull_request` trigger for checks before merge.

To use these workflows in your projects, reference them in your repository's workflow files:

### Using the generic service workflow:

```yaml
name: Build and Deploy Frontend

on:
  push:
    branches: [main]
    paths:
      - frontend/**
      - .github/workflows/build-and-deploy-frontend.yml
  pull_request:
    paths:
      - frontend/**
      - .github/workflows/build-and-deploy-frontend.yml
  workflow_dispatch:

jobs:
  build-and-deploy:
    uses: §§deploy_your_startup.github_username§§/§§deploy_your_startup.deploy_repo_name§§/.github/workflows/build-and-deploy-service.yml@main
    with:
      service: frontend
      environment: production
      run_tests: true
      run_lint: true
      platforms: linux/amd64,linux/arm64
    secrets:
      VAULT_PASSWORD: ${{ secrets.VAULT_PASSWORD }}
```

### Reusing the deploy workflow:

```yaml
name: Custom Deployment Pipeline

on:
  workflow_dispatch:
    inputs:
      custom_param:
        description: 'Custom parameter'
        required: true
        type: string

jobs:
  pre-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Custom pre-deployment task
        env:
          CUSTOM_PARAM: ${{ inputs.custom_param }}
        run: |
          printf 'Running custom pre-deployment task: %s\n' "$CUSTOM_PARAM"
  
  deploy:
    needs: pre-deploy
    uses: §§deploy_your_startup.github_username§§/§§deploy_your_startup.deploy_repo_name§§/.github/workflows/deploy.yml@main
    with:
      environment: production
    secrets:
      VAULT_PASSWORD: ${{ secrets.VAULT_PASSWORD }}
```

### Deploying infrastructure as part of another workflow:

```yaml
name: Complete Deployment

on:
  workflow_dispatch:

jobs:
  deploy-infrastructure:
    uses: §§deploy_your_startup.github_username§§/§§deploy_your_startup.deploy_repo_name§§/.github/workflows/deploy-infrastructure.yml@main
    with:
      environment: production
    secrets:
      VAULT_PASSWORD: ${{ secrets.VAULT_PASSWORD }}
      
  deploy-services:
    needs: deploy-infrastructure
    uses: §§deploy_your_startup.github_username§§/§§deploy_your_startup.deploy_repo_name§§/.github/workflows/build-and-deploy-service.yml@main
    with:
      service: backend
      environment: production
    secrets:
      VAULT_PASSWORD: ${{ secrets.VAULT_PASSWORD }}
```

## Required Secrets

The following secrets need to be configured in your repository:

- `GITHUB_TOKEN`: Automatically provided by GitHub, used for container registry authentication
- `VAULT_PASSWORD`: Required for accessing deployment secrets in Ansible vault

## Project Structure Requirements

To use these workflows effectively, your project should follow this structure:

```
your-project/
├── backend/            # Backend service code with Dockerfile
├── frontend/           # Frontend service code with Dockerfile 
├── auth-proxy/         # Auth proxy service with Dockerfile
├── ai/                 # AI service with Dockerfile
└── deployment/         # Ansible deployment scripts
    ├── pyproject.toml   # Deployment dependencies (uv)
    ├── uv.lock          # Locked versions
    ├── playbook.yml     # Project-specific deployment
    └── group_vars/      # Public settings and encrypted secrets
```

## Shared infrastructure roles

Projects load shared roles from their synced deployment checkout:

| Role | Purpose and configuration |
| --- | --- |
| `postgres` | Local database; configure database credentials and storage placement in project group_vars. |
| `cert-manager` | TLS certificates; configure the ACME solver and operator contact. |
| [`oauth2-proxy`](roles/oauth2-proxy/README.md) | OIDC reverse proxy; set `base_domain`, `auth_domain`, `auth_audience`, and Vault values `oauth2_proxy_client_id`, `oauth2_proxy_client_secret`, `oauth2_proxy_cookie_secret`. Guard the project's role import/include with `oauth2_proxy_enabled \| default(false)`. |
| [`kpis`](roles/kpis/README.md) | Self-hosted, cookieless KPI tracking (Umami); set `base_domain`, `project_name`, `kpis_website_id`, and Vault values `kpis_db_password`, `kpis_app_secret`, `kpis_admin_password`. Guard the project's role import/include with `kpis_enabled \| default(false)`. |

oauth2-proxy defaults to an API subdomain and a namespace-local backend.
Configure `oauth2_proxy_host` and `oauth2_proxy_upstream` for another topology.
`oauth_enabled` is the old application-template toggle; a later template phase
will rename it. The shared role does not define a toggle default.

## Private Network Mode

`network_mode: private` in a project's `group_vars` takes the cluster off the
internet. The servers keep running on Hetzner, but every public port except
Tailscale's UDP 41641 is closed; the site, SSH and the Kubernetes API are only
reachable from devices on your tailnet. Nothing changes for how you work:
`startup ansible …`, `kubectl --context …` and the pipelines keep doing what
they did, over the tailnet instead of the public IP.

### How it fits together

| Piece | Public mode | Private mode |
|---|---|---|
| Firewall (`hetzner-firewall`) | 22, 80, 443, 6443 open | only UDP 41641 open |
| Inventory (`inventory.hcloud.yml`) | `ansible_host` = public IP | servers labelled `network=private` → MagicDNS name |
| New servers (`hetzner-server`) | – | join the tailnet on first boot via cloud-init |
| Existing servers (`tailscale` role) | only with `tailscale_enabled: true` | join over SSH, report `tailscale_ipv4` |
| Pipelines (`actions/deploy`) | unchanged | runner joins the tailnet as `tag:ci` first |
| `startup ansible kubeconfig` | `https://<public-ip>:6443` | `https://<node>:6443` (the node name is in k3s' certificate) |
| TLS (`cert-manager`) | `http01` or `dns01` | `dns01` required |
| DNS (project playbook) | `hetzner-dns` → public IP | `hetzner-dns` → tailnet IP (100.x), imported after the join |

A load balancer is refused in private mode: it is a public endpoint that cloud
firewalls do not cover.

### One-time tailnet setup

1. Tailnet policy — tags, and who may reach them:

   ```jsonc
   "tagOwners": {
     "tag:server": ["autogroup:admin"],
     "tag:ci":     ["autogroup:admin"],
   },
   "grants": [
     { "src": ["autogroup:admin"], "dst": ["tag:server"], "ip": ["*"] },
     { "src": ["tag:ci"], "dst": ["tag:server"], "ip": ["tcp:22", "tcp:6443"] },
   ],
   ```

2. Two OAuth clients (admin console → Settings → Trust credentials → Credential →
   OAuth), both with **Keys → Auth Keys → Write**: one tagged `tag:server` for the
   nodes, one tagged `tag:ci` for the pipelines. OAuth secrets do not expire,
   unlike auth keys. Descriptions accept only letters, digits and spaces.

3. Vault them from the project's `deployment/` directory. Run the command first,
   then generate the credential and paste into the hidden prompts — copying the
   command after the secret would put the command text into the vault. Paths
   are absolute on purpose: a relative `--create-in` resolves against the
   directory of the `-r` file, not the current one.

   ```bash
   read -rs "?Server client secret: " s && printf '%s' "$s" | startup secrets update -r "$PWD/group_vars/production.yml" --field-stdin tailscale_auth_key --create-in "$PWD/group_vars/production.yml"; unset s
   ```

   ```bash
   read -rs "?CI client ID: " id && echo && read -rs "?CI client secret: " sec && echo && printf '%s' "$id" | startup secrets update -r "$PWD/group_vars/production.yml" --field-stdin tailscale_ci_oauth_client_id --create-in "$PWD/group_vars/production.yml" && printf '%s' "$sec" | startup secrets update -r "$PWD/group_vars/production.yml" --field-stdin tailscale_ci_oauth_secret --create-in "$PWD/group_vars/production.yml"; unset id sec
   ```

### Switching an existing project

Two runs, so a broken tailnet can never lock you out:

1. `tailscale_enabled: true`, `cert_manager_solver: dns01` → `startup ansible infrastructure`.
   The nodes join over the still-open public SSH. Check `tailscale status` on
   your machine lists them.
2. `network_mode: private` → `startup ansible infrastructure`. Labels flip, the
   inventory switches to the tailnet, the firewall closes. Then
   `startup ansible kubeconfig` to point your context at the tailnet.

Going back is the same run with `network_mode: public`: the provisioning play
only talks to the Hetzner API, so it reopens the firewall even when SSH is
unreachable.

A server that is deleted and recreated leaves a stale device of the same name in
the tailnet, and the new one would join as `<name>-1`. The `tailscale` role
fails on that instead of letting the inventory reach the dead device — remove the
old device in the admin console.

## Dependabot Configuration

Dependabot updates GitHub Actions in this repository weekly. Application
dependency updates belong in the generated project repositories.

## Extending the Workflows

To add workflows for new service types, follow the pattern in the existing workflows with appropriate customizations for build, test, and deployment steps.

## Shared-cluster ownership

Shared-cluster bootstrap assigns each startup a dedicated namespace. The
`project-namespace` role registers an owner identity in `kube-system`, validates
it for attached projects, and rejects namespaces already owned by another
startup. Optional namespace policies provide LimitRange defaults, ResourceQuota
budgets and NetworkPolicy boundaries. They require an enabled network-policy
controller. Quotas do not reserve capacity or enforce local-volume disk limits.

The cluster owner provisions nodes and manages upgrades. Attached projects must
find cert-manager, the required DNS webhook and Gateway API CRDs already
installed; they never install or upgrade those components. The CLI rejects
cluster-changing operations from attached projects. Administrative SSH access
remains part of the current deployment contract, so this is for mutually trusted
applications under one operator. Local Postgres and media volumes are not highly
available; back up each startup separately before cluster maintenance.

## Ubuntu LTS release upgrades

The shared `os-upgrade-playbook.yml` and `os-upgrade` role support
`startup ansible os-upgrade`. The default is a preview; execution requires
`--execute`, `--backup-confirmed` and an HTTPS `--health-url`. See the
[CLI operation guide](https://github.com/Deploy-your-Startup/cli#ubuntu-lts-release-upgrades)
for prerequisites, backups, downtime and recovery. This requires releases of
both the CLI and shared roles containing the feature, followed by sync and
review of the project's immutable role pin.

The role permits reviewed consecutive LTS paths (initially 24.04 → 26.04),
checks Ubuntu's normal release offer and upgrades one node at a time. Future
LTS support extends `roles/os-upgrade/defaults/main.yml` after compatibility
qualification; the generic driver and CLI remain the same. No development
release is forced and changing `hetzner_os_image` does not upgrade existing nodes.

Run `mise run test` with Docker available to exercise the complete real
playbook against disposable Ubuntu nodes. Package management, file operations
and async execution are real; release upgrades, kernel reboots and k3s are
simulated system boundaries. Without Docker these node checks skip locally;
CI requires them. Before adding a supported path or releasing it for production,
also qualify a real disposable k3s deployment, including release availability,
SSH/reboot recovery, storage, networking and application HTTPS checks. Local
integration success alone is not live release compatibility.

### Immutable runtime in Actions

When `deployment/shared-roles.ref` exists, deployment and runtime export execute
the shared action at that exact owner-repository commit. Advancing the shared
repository's `main` does not replace a project's reviewed roles. The CLI still
checks `shared-roles.sha256` before Ansible runs. Projects without a pin retain
the action's current runtime. Review a new pin before adopting role changes.

For projects pinned before the complete standalone exporter was introduced,
choose a reviewed owner-repository revision containing that exporter before
adding the standalone pre-deploy checksum check. A runtime-equivalent commit
can change the action implementation while leaving the role checksum unchanged.

## Coverage harness contract

Services keep normal local `./make.sh test` runs unmeasured. `./make.sh coverage`
runs measured integration tests and writes `coverage/cobertura.xml` with paths
relative to the service. The reusable build workflow accepts
`require_coverage: true` alongside `run_tests: true`; it calls the coverage verb,
requires a valid Cobertura report, and publishes a summary, PR comment and
`coverage-<service>` artifact. Existing callers remain optional by default.
Browser coverage is enabled explicitly by the application's E2E harness.

Set `coverage_measured_from: Integration` on a reusable build workflow caller
to label the measured test suites. Direct callers of the `coverage-report`
action use `measured_from`, for example `Integration + E2E` for combined data,
`E2E`, `Unit` or `Component`. This label applies to every report supplied in
that action call; use separate calls when reports measure different suites.
The reporter does not infer test types from Cobertura or the report title.
Only label suites whose execution contributed to the coverage data. A combined
report measures the union of covered code, not the sum of suite percentages.

This is a tested service contract, not an architecture decision.

### KPI access integration and browser checks

With Docker running, install the pinned test dependencies and browser once:

```bash
uv sync --locked
uv run --locked playwright install chromium
mise run check
```

The KPI checks use the actual Umami/Postgres images, OAuth2 Proxy and Traefik.
A local OIDC provider replaces the external identity-provider boundary. They
cover session reuse, direct login, anonymous/forged-header denial, public
collection, read-only permissions and switching back to password access.
