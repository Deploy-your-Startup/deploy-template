# Port of roles/hetzner-server.
# hcloud_ssh_key                    -> hcloud_ssh_key
# hcloud_server (loop 0..node_count) -> hcloud_server (count)
# hetzner.hcloud.server_network      -> hcloud_server_network
#
# Labels stay identical to the role (type + ingress=true) so the LB
# label_selector and the inventory.hcloud.yml dynamic inventory keep matching.

resource "hcloud_ssh_key" "keys" {
  for_each = { for k in var.ssh_public_keys : k.name => k.key }

  name       = each.key
  public_key = each.value
}

resource "hcloud_server" "nodes" {
  count = var.node_count

  name        = "${var.project_name}-${var.node_type}-${count.index}"
  server_type = var.server_type
  location    = var.location
  image       = "ubuntu-24.04"
  ssh_keys    = [for k in var.ssh_public_keys : k.name]

  labels = {
    type    = var.node_type
    ingress = "true"
  }

  depends_on = [hcloud_ssh_key.keys]
}

resource "hcloud_server_network" "nodes" {
  count = var.node_count

  server_id  = hcloud_server.nodes[count.index].id
  network_id = hcloud_network.private.id

  # Ensure the subnet exists before attaching, mirroring the role ordering.
  depends_on = [hcloud_network_subnet.nodes]
}
