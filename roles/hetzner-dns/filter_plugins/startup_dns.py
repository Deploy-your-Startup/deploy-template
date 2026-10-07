"""Resolve registrable domains using a vendored Public Suffix List.

PSL snapshot: publicsuffix/list@4018bd98001399ebff682f401664d469787ed7eb.
The adjacent data file is MPL-2.0 licensed; retain its copyright notice.
No network request or additional controller dependency is needed.
"""
from functools import lru_cache
from pathlib import Path
import re

from ansible.errors import AnsibleFilterError


def canonical_domain(value):
    try:
        domain = value.rstrip('.').encode('idna').decode('ascii').lower()
    except (AttributeError, UnicodeError) as exc:
        raise AnsibleFilterError('A valid DNS domain is required') from exc
    labels = domain.split('.')
    if len(labels) < 2 or len(domain) > 253 or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
        for label in labels
    ) or labels[-1].isdigit():
        raise AnsibleFilterError(f'Invalid DNS domain: {domain}')
    return domain


@lru_cache(maxsize=1)
def suffix_rules():
    exact, wildcard, exceptions = set(), set(), set()
    for line in Path(__file__).with_name('public_suffix_list.dat').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        if line.startswith('!'):
            exceptions.add(line[1:].encode('idna').decode('ascii').lower())
        elif line.startswith('*.'):
            wildcard.add(line[2:].encode('idna').decode('ascii').lower())
        else:
            exact.add(line.encode('idna').decode('ascii').lower())
    return exact, wildcard, exceptions


def registrable_domain(domain):
    labels = domain.split('.')
    exact, wildcard, exceptions = suffix_rules()
    suffix_length = 1
    for index in range(len(labels)):
        candidate = '.'.join(labels[index:])
        length = len(labels) - index
        if candidate in exceptions:
            suffix_length = length - 1
            break
        if candidate in exact:
            suffix_length = max(suffix_length, length)
        if index > 0 and candidate in wildcard:
            suffix_length = max(suffix_length, length + 1)
    if len(labels) <= suffix_length:
        raise AnsibleFilterError(f'{domain} is a public suffix, not an owned domain')
    return '.'.join(labels[-suffix_length - 1:])


def dns_records(domains, existing_zones=None, overrides=None):
    zones = [canonical_domain(zone) for zone in (existing_zones or [])]
    overrides = {canonical_domain(domain): canonical_domain(zone) for domain, zone in (overrides or {}).items()}
    records = []
    for value in domains:
        domain = canonical_domain(value)
        registered = registrable_domain(domain)
        candidates = [zone for zone in zones if
                      (domain == zone or domain.endswith('.' + zone)) and
                      (zone == registered or zone.endswith('.' + registered))]
        zone = overrides.get(domain) or max(candidates, key=len, default=registered)
        if not (domain == zone or domain.endswith('.' + zone)) or not (
            zone == registered or zone.endswith('.' + registered)
        ):
            raise AnsibleFilterError(f'DNS zone {zone} does not contain owned domain {domain}')
        records.append({'domain': domain, 'zone': zone,
                        'name': '@' if domain == zone else domain[:-len(zone) - 1]})
    return records


class FilterModule:
    def filters(self):
        return {'startup_dns_records': dns_records}
