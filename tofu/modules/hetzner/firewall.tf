# Port of roles/hetzner-firewall.
# hetzner.hcloud.firewall          -> hcloud_firewall (rule blocks)
# hetzner.hcloud.firewall_resource -> hcloud_firewall_attachment
#
# The role discovered cluster node public IPs at runtime via server_info; here
# we reference the hcloud_server resources directly — no discovery step needed.

locals {
  firewall_name    = "${var.project_name}-firewall"
  cluster_node_ips = [for s in hcloud_server.nodes : "${s.ipv4_address}/32"]
}

resource "hcloud_firewall" "this" {
  name = local.firewall_name

  # --- PUBLIC ACCESS ---
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "SSH"
  }
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "HTTP"
  }
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "HTTPS"
  }
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "6443"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "Kubernetes API"
  }

  # --- PRIVATE NETWORK ACCESS (cluster-internal) ---
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "any"
    source_ips  = [var.network_ip_range]
    description = "All TCP from private network"
  }
  rule {
    direction   = "in"
    protocol    = "udp"
    port        = "any"
    source_ips  = [var.network_ip_range]
    description = "All UDP from private network"
  }
  rule {
    direction   = "in"
    protocol    = "icmp"
    source_ips  = [var.network_ip_range]
    description = "ICMP from private network"
  }

  # --- CLUSTER NODES (public IP fallback) ---
  dynamic "rule" {
    # Only emit when there are node IPs; an empty source_ips list is invalid.
    for_each = length(local.cluster_node_ips) > 0 ? ["tcp", "udp"] : []
    content {
      direction   = "in"
      protocol    = rule.value
      port        = "any"
      source_ips  = local.cluster_node_ips
      description = "All ${upper(rule.value)} from cluster nodes"
    }
  }
}

resource "hcloud_firewall_attachment" "nodes" {
  firewall_id = hcloud_firewall.this.id
  server_ids  = [for s in hcloud_server.nodes : s.id]
}
