output "loadbalancer_ip" {
  description = "Public IPv4 of the load balancer, or null when disabled."
  value       = var.create_load_balancer ? hcloud_load_balancer.this[0].ipv4 : null
}

output "ingress_ip" {
  description = "DNS A-record target: the LB IP when enabled, else the first master node's public IP."
  value       = local.ingress_ip
}

output "network_id" {
  description = "ID of the private network."
  value       = hcloud_network.private.id
}

output "server_ids" {
  description = "IDs of the provisioned nodes."
  value       = [for s in hcloud_server.nodes : s.id]
}

output "server_ipv4" {
  description = "Public IPv4 addresses of the provisioned nodes."
  value       = [for s in hcloud_server.nodes : s.ipv4_address]
}

output "server_names" {
  description = "Names of the provisioned nodes (match the dynamic inventory)."
  value       = [for s in hcloud_server.nodes : s.name]
}

output "managed_dns_zones" {
  description = "Apex zones this deployment manages."
  value       = sort(tolist(local.managed_zones))
}
