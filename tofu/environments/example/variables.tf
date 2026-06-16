variable "project_name" {
  type = string
}

variable "master_count" {
  type    = number
  default = 1
}

variable "worker_count" {
  type    = number
  default = 0
}

variable "location" {
  type    = string
  default = "fsn1"
}

variable "server_type" {
  type    = string
  default = "cx23"
}

variable "ssh_public_keys" {
  type = list(object({
    name = string
    key  = string
  }))
}

variable "network_name" {
  type    = string
  default = "k8s-network"
}

variable "network_ip_range" {
  type    = string
  default = "10.0.0.0/16"
}

variable "subnet_ip_range" {
  type    = string
  default = "10.0.1.0/24"
}

variable "network_zone" {
  type    = string
  default = "eu-central"
}

variable "create_load_balancer" {
  type    = bool
  default = false
}

variable "base_domain" {
  type = string
}

variable "additional_domains" {
  type    = list(string)
  default = []
}

variable "dns_apex_wildcard" {
  type    = bool
  default = true
}

variable "dns_ttl" {
  type    = number
  default = 300
}

variable "extra_dns_records" {
  type = map(list(object({
    name  = string
    type  = string
    ttl   = number
    value = string
  })))
  default = {}
}
