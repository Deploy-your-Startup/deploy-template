# Example environment — copy this directory per project/environment and fill in
# terraform.tfvars. The startup CLI renders one of these per deployment.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = ">= 1.56.0"
    }
  }
}

# Authenticates from HCLOUD_TOKEN in the environment (injected by the CLI from
# the vault). Do not hardcode the token here.
provider "hcloud" {}

module "infra" {
  source = "../../modules/hetzner"

  project_name = var.project_name
  master_count = var.master_count
  worker_count = var.worker_count
  location     = var.location
  server_type  = var.server_type

  ssh_public_keys = var.ssh_public_keys

  network_name     = var.network_name
  network_ip_range = var.network_ip_range
  subnet_ip_range  = var.subnet_ip_range
  network_zone     = var.network_zone

  create_load_balancer = var.create_load_balancer

  base_domain        = var.base_domain
  additional_domains = var.additional_domains
  dns_apex_wildcard  = var.dns_apex_wildcard
  dns_ttl            = var.dns_ttl
  extra_dns_records  = var.extra_dns_records
}
