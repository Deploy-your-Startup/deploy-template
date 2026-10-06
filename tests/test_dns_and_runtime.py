import importlib.util
from pathlib import Path
import configparser

import pytest
import yaml
from ansible.errors import AnsibleFilterError
from ansible.template import Templar, trust_as_template
from ansible.parsing.dataloader import DataLoader

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('startup_dns', ROOT / 'roles/hetzner-dns/filter_plugins/startup_dns.py')
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)


@pytest.mark.parametrize('domain,zone,name', [
    ('example.com', 'example.com', '@'),
    ('www.example.com', 'example.com', 'www'),
    ('example.co.uk', 'example.co.uk', '@'),
    ('app.example.co.uk', 'example.co.uk', 'app'),
    ('example.com.au', 'example.com.au', '@'),
    ('a.b.ck', 'a.b.ck', '@'),
    ('www.ck', 'www.ck', '@'),
    ('app.city.kawasaki.jp', 'city.kawasaki.jp', 'app'),
    ('EXAMPLE.COM.', 'example.com', '@'),
    ('bücher.de', 'xn--bcher-kva.de', '@'),
])
def test_domains_use_the_public_suffix_list(domain, zone, name):
    assert dns.dns_records([domain]) == [{'domain': dns.canonical_domain(domain), 'zone': zone, 'name': name}]


def test_longest_existing_delegated_zone_is_used():
    assert dns.dns_records(['www.app.example.com'], ['example.com', 'app.example.com'])[0]['zone'] == 'app.example.com'


def test_new_delegated_zone_can_be_explicit():
    assert dns.dns_records(['app.example.com'], overrides={'app.example.com': 'app.example.com'})[0]['name'] == '@'


@pytest.mark.parametrize('domain', ['co.uk', 'localhost', '127.0.0.1', 'bad..com', '-bad.com', 'example.com/'])
def test_public_suffixes_and_invalid_domains_are_rejected(domain):
    with pytest.raises(AnsibleFilterError):
        dns.dns_records([domain])


def test_a_zone_override_cannot_modify_an_unrelated_domain():
    with pytest.raises(AnsibleFilterError):
        dns.dns_records(['app.example.com'], overrides={'app.example.com': 'other.com'})


def test_python_client_is_pinned_and_isolated_from_system_packages():
    tasks = yaml.safe_load((ROOT / 'roles/python/tasks/main.yml').read_text())
    pip_task = next(t['ansible.builtin.pip'] for t in tasks if 'ansible.builtin.pip' in t)
    assert pip_task['name'].startswith('kubernetes==')
    assert pip_task['virtualenv']
    assert 'extra_args' not in pip_task
    assert pip_task['state'] == 'present'
    assert tasks[-1]['ansible.builtin.set_fact']['ansible_python_interpreter'].endswith('/bin/python')


def test_changed_ssh_host_keys_are_rejected():
    config = configparser.ConfigParser()
    config.read(ROOT / 'ansible.cfg')
    assert config.getboolean('defaults', 'host_key_checking')
    assert 'StrictHostKeyChecking=accept-new' in config['ssh_connection']['ssh_args']


@pytest.mark.parametrize('admin_cidrs,ports', [([], ['80', '443', '22']), (['203.0.113.1/32'], ['80', '443', '22', '6443'])])
def test_kubernetes_api_is_closed_unless_admin_cidrs_are_supplied(admin_cidrs, ports):
    tasks = yaml.safe_load((ROOT / 'roles/hetzner-firewall/tasks/main.yml').read_text())
    create = next(t for t in tasks if t['name'] == 'Create Hetzner Firewall')
    variables = {'firewall_ssh_source_ips': ['0.0.0.0/0', '::/0'], 'firewall_api_source_ips': admin_cidrs}
    engine = Templar(loader=DataLoader(), variables=variables)
    for name in ['firewall_web_rules', 'firewall_ssh_rules', 'firewall_api_rules']:
        values = create['vars'][name]
        variables[name] = [{k: engine.template(trust_as_template(v)) if isinstance(v, str) else v for k, v in rule.items()} for rule in values]
        engine = Templar(loader=DataLoader(), variables=variables)
    rules = engine.template(trust_as_template(create['vars']['firewall_public_rules']))
    assert [r['port'] for r in rules] == ports
    if admin_cidrs:
        assert rules[-1]['source_ips'] == admin_cidrs


def test_firewall_default_mode_can_render_the_failure_message():
    # GIVEN a legacy project without network_mode, WHEN Ansible renders its guard,
    # THEN the normal public default does not fail before the assertion runs.
    task = yaml.safe_load((ROOT / 'roles/hetzner-firewall/tasks/main.yml').read_text())[0]
    engine = Templar(loader=DataLoader(), variables={})
    assert 'public' in engine.template(trust_as_template(task['ansible.builtin.assert']['fail_msg']))


def test_repeated_python_role_resets_the_high_precedence_interpreter_fact():
    # GIVEN a previously prepared client, WHEN the same role is imported again,
    # THEN apt/pip use distribution Python and later k8s modules use the venv.
    tasks = yaml.safe_load((ROOT / 'roles/python/tasks/main.yml').read_text())
    engine = Templar(loader=DataLoader(), variables={'kubernetes_python_venv': '/opt/startup-ansible'})
    interpreter = '/opt/startup-ansible/bin/python'
    for task in tasks:
        if 'ansible.builtin.set_fact' in task:
            interpreter = engine.template(trust_as_template(task['ansible.builtin.set_fact']['ansible_python_interpreter']))
        if 'ansible.builtin.pip' in task or 'ansible.builtin.apt' in task:
            assert interpreter == '/usr/bin/python3'
    assert interpreter == '/opt/startup-ansible/bin/python'
