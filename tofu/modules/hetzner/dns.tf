# Port of roles/hetzner-dns (unified Cloud DNS API, same HCLOUD_TOKEN).
# hetzner.hcloud.zone       -> hcloud_zone (apex) / data.hcloud_zone (shared parent)
# hetzner.hcloud.zone_rrset -> hcloud_zone_rrset
#
# Security guard preserved from the role: a subdomain deployment
# (app.example.com) must NEVER create @ or * on the shared root zone. Here that
# is structural — @/* rrsets are only emitted for apex domains.
#
# Ownership model (intentional difference vs the imperative role): apex domains
# are managed as zone *resources* (this project owns its apex). Parent zones of
# subdomain deployments are looked up via *data* sources and must already exist
# in the account — so two project states never fight over one shared zone. If a
# parent zone is missing, the plan fails loudly instead of silently skipping.

locals {
  all_domains = concat([var.base_domain], var.additional_domains)

  # Helper: split a domain into labels.
  _labels = { for d in local.all_domains : d => split(".", d) }

  # Zone = last two labels (example.com from app.example.com).
  _zone_of = { for d in local.all_domains : d => join(".", slice(local._labels[d], length(local._labels[d]) - 2, length(local._labels[d]))) }

  # Apex = exactly two labels (host == its own zone).
  apex_domains = [for d in local.all_domains : d if length(local._labels[d]) == 2]

  # Subdomains = 3+ labels. name is everything before the zone.
  subdomains = [for d in local.all_domains : {
    full = d
    name = join(".", slice(local._labels[d], 0, length(local._labels[d]) - 2))
    zone = local._zone_of[d]
  } if length(local._labels[d]) > 2]

  # Zones we manage ourselves (apex deployments own their apex).
  managed_zones = toset(local.apex_domains)

  # Zones referenced but managed elsewhere -> looked up via data source.
  # Includes subdomain parents and any extra_dns_records zone keys not managed here.
  external_zones = toset(concat(
    [for s in local.subdomains : s.zone if !contains(local.apex_domains, s.zone)],
    [for z in keys(var.extra_dns_records) : z if !contains(local.apex_domains, z)],
  ))

  # zone name -> reference that carries the correct create-ordering dependency.
  zone_ref = merge(
    { for z in local.managed_zones : z => hcloud_zone.apex[z].name },
    { for z in local.external_zones : z => data.hcloud_zone.external[z].name },
  )

  # DNS target: the load balancer when enabled, otherwise the first master node's
  # public IP — matching the role's fallback to hostvars[<project>-master-0].
  ingress_ip = var.create_load_balancer ? hcloud_load_balancer.this[0].ipv4 : hcloud_server.masters[0].ipv4_address
}

resource "hcloud_zone" "apex" {
  for_each = local.managed_zones

  name = each.value
  mode = "primary"
  ttl  = var.dns_ttl
}

data "hcloud_zone" "external" {
  for_each = local.external_zones

  name = each.value
}

# Apex @ record — only for owned apex domains.
resource "hcloud_zone_rrset" "apex" {
  for_each = local.managed_zones

  zone = hcloud_zone.apex[each.value].name
  name = "@"
  type = "A"
  ttl  = var.dns_ttl
  records = [
    { value = local.ingress_ip }
  ]
}

# Apex wildcard (*) — apex only, opt-out via dns_apex_wildcard.
resource "hcloud_zone_rrset" "wildcard" {
  for_each = var.dns_apex_wildcard ? local.managed_zones : toset([])

  zone = hcloud_zone.apex[each.value].name
  name = "*"
  type = "A"
  ttl  = var.dns_ttl
  records = [
    { value = local.ingress_ip }
  ]
}

# Subdomain records (e.g. www, app) -> their own A record only.
resource "hcloud_zone_rrset" "subdomain" {
  for_each = { for s in local.subdomains : s.full => s }

  zone = local.zone_ref[each.value.zone]
  name = each.value.name
  type = "A"
  ttl  = var.dns_ttl
  records = [
    { value = local.ingress_ip }
  ]
}

# Extra DNS records (CNAME/MX/TXT/...) per zone.
resource "hcloud_zone_rrset" "extra" {
  for_each = {
    for item in flatten([
      for zone, recs in var.extra_dns_records : [
        for r in recs : {
          key   = "${zone}|${r.type}|${r.name}"
          zone  = zone
          name  = r.name
          type  = r.type
          ttl   = r.ttl
          value = r.value
        }
      ]
    ]) : item.key => item
  }

  zone = local.zone_ref[each.value.zone]
  name = each.value.name
  type = each.value.type
  ttl  = each.value.ttl
  records = [
    { value = each.value.value }
  ]
}
