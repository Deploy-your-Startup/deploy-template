# Port of roles/hetzner-network.
# hetzner.hcloud.network    -> hcloud_network
# hetzner.hcloud.subnetwork -> hcloud_network_subnet

resource "hcloud_network" "private" {
  name     = var.network_name
  ip_range = var.network_ip_range
}

resource "hcloud_network_subnet" "nodes" {
  network_id   = hcloud_network.private.id
  type         = "cloud"
  network_zone = var.network_zone
  ip_range     = var.subnet_ip_range
}
