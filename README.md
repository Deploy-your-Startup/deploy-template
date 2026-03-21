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
  - Exports `roles/`, `requirements.yml`, and `backup-playbook.yml`
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

## Dependabot Configuration

This repository includes automatic dependency updates via Dependabot for:
- GitHub Actions workflows
- Go modules (auth-proxy)
- NPM packages (frontend)
- Python packages (backend, ai, deployment)

## Extending the Workflows

To add workflows for new service types, follow the pattern in the existing workflows with appropriate customizations for build, test, and deployment steps.
