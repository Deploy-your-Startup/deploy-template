# Port of roles/hetzner-loadbalancer.
# Gated by var.create_load_balancer to match the role (playbook runs the LB role
# only `when: create_load_balancer`). When disabled, DNS targets the first master
# node's public IP instead (see dns.tf).
# hcloud_load_balancer         -> hcloud_load_balancer
# hcloud_load_balancer_target  -> hcloud_load_balancer_target (label_selector)
# hcloud_load_balancer_service -> hcloud_load_balancer_service (80->30080, 443->30443)

resource "hcloud_load_balancer" "this" {
  count = var.create_load_balancer ? 1 : 0

  name               = var.project_name
  load_balancer_type = "lb11"
  algorithm {
    type = "round_robin"
  }
  location = var.location
}

resource "hcloud_load_balancer_target" "ingress" {
  count = var.create_load_balancer ? 1 : 0

  type             = "label_selector"
  load_balancer_id = hcloud_load_balancer.this[0].id
  label_selector   = "ingress=true"

  # Targets are matched by label; ensure nodes exist first.
  depends_on = [hcloud_server.masters, hcloud_server.workers]
}

resource "hcloud_load_balancer_service" "http" {
  count = var.create_load_balancer ? 1 : 0

  load_balancer_id = hcloud_load_balancer.this[0].id
  protocol         = "tcp"
  listen_port      = 80
  destination_port = 30080
}

resource "hcloud_load_balancer_service" "https" {
  count = var.create_load_balancer ? 1 : 0

  load_balancer_id = hcloud_load_balancer.this[0].id
  protocol         = "tcp"
  listen_port      = 443
  destination_port = 30443
}
