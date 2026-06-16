terraform {
  # 1.10+: native S3 state locking (use_lockfile), enforced by the startup CLI.
  required_version = ">= 1.10.0"

  required_providers {
    hcloud = {
      source = "hetznercloud/hcloud"
      # >= 1.56.0: DNS (hcloud_zone / hcloud_zone_rrset) is GA and served by the
      # unified Cloud API — same endpoint and HCLOUD_TOKEN as compute/network/LB.
      # This matches the existing Ansible `hetzner.hcloud.zone` role, so no second
      # DNS token is needed.
      version = ">= 1.56.0"
    }
  }
}

# The provider is configured in the root environment (see environments/*/main.tf)
# and inherited here. It authenticates from HCLOUD_TOKEN in the environment, which
# the CLI injects from the vault (`hcloud_token_<env>`) without writing it to disk.
