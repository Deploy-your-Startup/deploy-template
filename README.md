# Deploy Template

This repository contains the shared deploy workflows, composite actions, and
Ansible roles that Deploy Your Startup customers sync into their own private
`deploy-your-startup` repository.

It combines the reusable GitHub Actions logic with the shared deployment assets
so projects only need one synced private repository.

## Available Workflows

### Generic Service Build and Deploy
- **File**: `.github/workflows/build-and-deploy-service.yml`
- **Type**: Reusable workflow
- **Features**:
  - Generic workflow for building and deploying any service
  - Configurable service name
  - Optional testing
  - Optional multi-platform support (amd64/arm64)
  - Standardized Docker image building and pushing
  - Deployment to configured environments

### Deployment
- **File**: `.github/workflows/deploy.yml`
- **Type**: Reusable workflow and standalone workflow
- **Triggers**: Pushes to `main` branch affecting `deployment/**` files or manual workflow dispatch
- **Features**:
  - Can be reused in other workflows
  - Generic deployment process for any service

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

### Docker Build and Push Action
- **Location**: `.github/actions/docker-build-push/action.yml`
- **Purpose**: Build and push Docker images to container registry
- **Features**:
  - Builds multi-platform images (amd64/arm64)
  - Pushes both latest and versioned tags
  - Uses GitHub Actions cache for faster builds

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
   - `test` command for running tests
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
RUN ./make.sh run
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

To use these workflows in your projects, reference them in your repository's workflow files:

### Using the generic service workflow:

```yaml
name: Build and Deploy Frontend

on:
  push:
    branches: [main]
    paths:
      - frontend/**
  workflow_dispatch:

jobs:
  build-and-deploy:
    uses: §§deploy_your_startup.github_username§§/§§deploy_your_startup.deploy_repo_name§§/.github/workflows/build-and-deploy-service.yml@main
    with:
      service: frontend
      environment: production
      run_tests: true
      multi_platform: true
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
        run: echo "Running custom pre-deployment task: ${{ github.event.inputs.custom_param }}"
  
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
    └── requirements.txt # Python dependencies for deployment
```

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
| DNS (`hetzner-dns`) | A → public IP | A → tailnet IP (100.x), written after the join |

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

This repository includes automatic dependency updates via Dependabot for:
- GitHub Actions workflows
- Go modules (auth-proxy)
- NPM packages (frontend)
- Python packages (backend, ai, deployment)

## Extending the Workflows

To add workflows for new service types, follow the pattern in the existing workflows with appropriate customizations for build, test, and deployment steps.
