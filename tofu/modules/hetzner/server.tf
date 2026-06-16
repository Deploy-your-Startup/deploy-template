# Port of roles/hetzner-server.
# The playbook calls the role twice (master_count + worker_count), so we model
# two node groups here. Both carry ingress=true (LB target) and a type label the
# k3s roles and inventory.hcloud.yml dynamic inventory key on.
# hcloud_ssh_key                -> hcloud_ssh_key
# hcloud_server (loop)          -> hcloud_server (master/worker count)
# hetzner.hcloud.server_network -> hcloud_server_network

resource "hcloud_ssh_key" "keys" {
  for_each = { for k in var.ssh_public_keys : k.name => k.key }

  name       = each.key
  public_key = each.value
}

resource "hcloud_server" "masters" {
  count = var.master_count

  name        = "${var.project_name}-master-${count.index}"
  server_type = var.server_type
  location    = var.location
  image       = "ubuntu-24.04"
  ssh_keys    = [for k in var.ssh_public_keys : k.name]

  labels = {
    type    = "master"
    ingress = "true"
  }

  depends_on = [hcloud_ssh_key.keys]
}

resource "hcloud_server" "workers" {
  count = var.worker_count

  name        = "${var.project_name}-worker-${count.index}"
  server_type = var.server_type
  location    = var.location
  image       = "ubuntu-24.04"
  ssh_keys    = [for k in var.ssh_public_keys : k.name]

  labels = {
    type    = "worker"
    ingress = "true"
  }

  depends_on = [hcloud_ssh_key.keys]
}

locals {
  # All cluster nodes, masters first — used by firewall, LB attachment and DNS.
  all_nodes = concat(hcloud_server.masters, hcloud_server.workers)
}

resource "hcloud_server_network" "masters" {
  count = var.master_count

  server_id  = hcloud_server.masters[count.index].id
  network_id = hcloud_network.private.id

  depends_on = [hcloud_network_subnet.nodes]
}

resource "hcloud_server_network" "workers" {
  count = var.worker_count

  server_id  = hcloud_server.workers[count.index].id
  network_id = hcloud_network.private.id

  depends_on = [hcloud_network_subnet.nodes]
}
