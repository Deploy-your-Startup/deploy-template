# Remote state on S3-compatible Object Storage — provider-agnostic.
#
# The backend block is intentionally EMPTY (partial config). Backend config can
# not use variables, so the concrete bucket/key/endpoint/region are supplied at
# init time per deployment, which lets the SAME template target either provider:
#
#   Hetzner -> https://fsn1.your-objectstorage.com   (region eu-central)
#   OVH     -> https://s3.gra.io.cloud.ovh.net        (region gra)
#
# The CLI renders backend.<env>.hcl for the chosen provider and runs:
#   tofu init -backend-config=backend.<env>.hcl
#
# Auth is read from the environment (CLI injects from the vault, never committed):
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  -> object-storage credentials
#
# Until a bucket exists, init with `tofu init -backend=false` to skip the
# backend and use local state (terraform.tfstate, gitignored) so you can iterate.

terraform {
  backend "s3" {}
}

# -----------------------------------------------------------------------------
# Example backend.<env>.hcl rendered by the CLI (Hetzner shown; OVH swaps the
# endpoint/region/bucket and the AWS_* creds point at OVH Object Storage):
#
#   bucket = "startup-tfstate"
#   key    = "<project_name>/production/terraform.tfstate"
#   region = "eu-central"
#   endpoints = { s3 = "https://fsn1.your-objectstorage.com" }
#   encrypt = true
#
#   # Native S3 state locking (OpenTofu >= 1.10) — a .tflock object in the
#   # bucket, no DynamoDB. Both Hetzner and OVH object storage are Ceph/RGW; if
#   # conditional writes aren't supported, the workflow concurrency group still
#   # serializes infra runs per environment.
#   use_lockfile = true
#
#   # Non-AWS S3: skip AWS-specific validations.
#   skip_credentials_validation = true
#   skip_metadata_api_check     = true
#   skip_region_validation      = true
#   skip_requesting_account_id  = true
#   use_path_style              = true
# -----------------------------------------------------------------------------
