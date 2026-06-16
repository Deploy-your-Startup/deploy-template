# =============================================================================
# Provider-neutral input interface
# =============================================================================
# This file defines the shared variable contract that every provider module
# (hetzner today, ovh in phase 2) must accept. It is NOT a usable module on its
# own — provider modules copy this interface so a future `var.provider` switch
# can route the same inputs to either backend without the caller changing.
#
# Keep this in sync with modules/<provider>/variables.tf.
# =============================================================================

variable "project_name" {
  description = "Project slug, used for naming all resources (servers, firewall, LB)."
  type        = string
}

variable "master_count" {
  description = "Number of master nodes."
  type        = number
  default     = 1
}

variable "worker_count" {
  description = "Number of worker nodes."
  type        = number
  default     = 0
}

variable "location" {
  description = "Provider datacenter/location (Hetzner: fsn1)."
  type        = string
  default     = "fsn1"
}

variable "server_type" {
  description = "Provider instance/flavor type (Hetzner: cx23)."
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

variable "network_ip_range" {
  description = "CIDR of the private network."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_ip_range" {
  description = "CIDR of the node subnet within the private network."
  type        = string
  default     = "10.0.1.0/24"
}

variable "create_load_balancer" {
  description = "Whether to provision a load balancer. When false, DNS points at the first master node's public IP."
  type        = bool
  default     = false
}

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
