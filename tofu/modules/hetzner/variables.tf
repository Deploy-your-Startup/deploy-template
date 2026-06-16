# =============================================================================
# Hetzner module inputs
# =============================================================================
# Mirrors tofu/modules/common/variables.tf (the provider-neutral contract) plus
# a few Hetzner-specific network knobs. Keep the shared subset in sync with
# common so a future `var.provider` switch can route the same inputs to OVH.
# =============================================================================

variable "project_name" {
  description = "Project slug, used for naming all resources."
  type        = string
}

variable "node_count" {
  description = "Number of cluster nodes to provision."
  type        = number
  default     = 1
}

variable "node_type" {
  description = "Logical role label applied to nodes (e.g. master)."
  type        = string
  default     = "master"
}

variable "location" {
  description = "Hetzner location."
  type        = string
  default     = "fsn1"
}

variable "server_type" {
  description = "Hetzner server type."
  type        = string
  default     = "cx23"
}

variable "ssh_public_keys" {
  description = "SSH public keys to register and attach to nodes."
  type = list(object({
    name = string
    key  = string
  }))
}

# --- Hetzner-specific network knobs (defaults match roles/hetzner-network) ---

variable "network_name" {
  description = "Name of the private network."
  type        = string
  default     = "k8s-network"
}

variable "network_ip_range" {
  description = "CIDR of the private network."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_ip_range" {
  description = "CIDR of the node subnet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "network_zone" {
  description = "Hetzner network zone for the subnet."
  type        = string
  default     = "eu-central"
}

# --- Load balancer ---

variable "create_load_balancer" {
  description = "Whether to provision a load balancer. When false, DNS points at the first master node's public IP (matches the role default)."
  type        = bool
  default     = false
}

# --- DNS ---

variable "base_domain" {
  description = "Primary domain for the deployment (apex or subdomain)."
  type        = string
}

variable "additional_domains" {
  description = "Extra domains/subdomains that should resolve to the load balancer."
  type        = list(string)
  default     = []
}

variable "dns_apex_wildcard" {
  description = "Whether owned apex zones also get a wildcard (*) A record. Subdomain deployments never get one regardless."
  type        = bool
  default     = true
}

variable "dns_ttl" {
  description = "TTL for the managed A records."
  type        = number
  default     = 300
}

variable "extra_dns_records" {
  description = "Extra DNS records keyed by zone name. Each entry: {name, type, ttl, value}."
  type = map(list(object({
    name  = string
    type  = string
    ttl   = number
    value = string
  })))
  default = {}
}
