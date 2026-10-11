"""Exercise role guards with Ansible's expression engine and rendered manifests."""
import base64
import os
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
os.environ["ANSIBLE_ROLES_PATH"] = str(ROOT / "roles")

from ansible.parsing.dataloader import DataLoader
from ansible.playbook import Playbook
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
from ansible.template import trust_as_template
from ansible.vars.manager import VariableManager

init_plugin_loader()


def load(relative):
    return yaml.safe_load((ROOT / relative).read_text())


def templar(variables):
    return Templar(loader=DataLoader(), variables=variables)


def render(relative, variables):
    return templar(variables).template(trust_as_template((ROOT / relative).read_text()))


def walk(tasks):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from walk(task.get(key, []))


def apply_preflight(variables):
    """Feed observed Kubernetes state through the actual role expressions."""
    variables = {"postgres_storage_node": "", **variables}
    for task in load("roles/postgres/tasks/preflight.yml"):
        if facts := task.get("ansible.builtin.set_fact"):
            variables.update({k: templar(variables).template(trust_as_template(v)) for k, v in facts.items()})
        if assertions := task.get("ansible.builtin.assert"):
            for expression in assertions["that"]:
                if not templar(variables).evaluate_expression(trust_as_template(expression)):
                    raise ValueError(task["name"])
    return variables


def state(nodes, pods=(), recorded=None, selected=""):
    return {
        "postgres_cluster_nodes": {"resources": [{"metadata": {"name": name}} for name in nodes]},
        "postgres_existing_pods": {"resources": [{"spec": {"nodeName": name}} for name in pods]},
        "postgres_existing_volume": {"resources": [] if recorded is None else [{"metadata": {"annotations": {"startup.deploy/storage-node": recorded}}}]},
        "postgres_storage_node": selected,
    }


def test_every_role_has_valid_ansible_task_syntax():
    loader = DataLoader()
    loader.set_basedir(str(ROOT))
    playbook = Playbook.load(str(ROOT / "tests/roles.yml"), loader=loader, variable_manager=VariableManager(loader=loader))
    assert len(playbook.get_plays()) == 1
    assert {role.get_name() for role in playbook.get_plays()[0].get_roles()} == {path.name for path in (ROOT / "roles").iterdir()}


def kpis_variables(**overrides):
    return {
        **{key: trust_as_template(value) if isinstance(value, str) else value
           for key, value in load('roles/kpis/defaults/main.yml').items()},
        'base_domain': 'example.com', 'project_name': 'sample-startup',
        'k8s_namespace': 'sample',
        'ansible_date_time': {'iso8601_basic': '20261011T120000'},
        'postgres_host': 'postgres', 'postgres_port': 5432, 'postgres_version': '18.6',
        'kpis_website_id': '8d92b4ec-9a6a-4c50-85e4-b6ea4048f3f8',
        'kpis_db_password': "TEST_DB_PASSWORD:/@'?#",
        'kpis_app_secret': 'TEST_APP_SECRET',
        'kpis_admin_password': 'TEST_ADMIN_PASSWORD',
        **overrides,
    }


def kpis_guard_allows(variables):
    guard = load('roles/kpis/tasks/main.yml')[0]['ansible.builtin.assert']
    return all(templar(variables).evaluate_expression(trust_as_template(expression))
               for expression in guard['that'])


@pytest.mark.parametrize('namespace', ['sample', None])
def test_kpis_render_preserves_secret_credentials_and_safe_ingress(namespace):
    # GIVEN shared-role defaults and a project's database and website configuration,
    variables = kpis_variables()
    if namespace is None:
        del variables['k8s_namespace']
    assert kpis_guard_allows(variables)
    # WHEN Ansible renders every actual manifest and both bootstrap ingress states,
    deployment_text = render('roles/kpis/templates/deployment.yml', variables)
    deployment = yaml.safe_load(deployment_text)
    secret = yaml.safe_load(render('roles/kpis/templates/secret.yml', variables))
    service = yaml.safe_load(render('roles/kpis/templates/service.yml', variables))
    ingress = yaml.safe_load(render('roles/kpis/templates/ingress.yml', variables))
    bootstrap = yaml.safe_load(render('roles/kpis/templates/ingress.yml', {
        **variables, 'kpis_bootstrap_only': True,
    }))
    pod = deployment['spec']['template']['spec']
    container = pod['containers'][0]
    # THEN the pinned upstream image uses Secret credentials and heartbeat probes.
    assert container['image'] == 'ghcr.io/umami-software/umami:3.4.0'
    assert pod['initContainers'][0]['image'] == 'postgres:18.6'
    assert container['envFrom'] == [{'secretRef': {'name': secret['metadata']['name']}}]
    assert container['env'] == [{'name': 'DISABLE_TELEMETRY', 'value': '1'}]
    assert 'args' not in container and 'command' not in container
    assert secret['stringData'] == {
        'DATABASE_URL': 'postgresql://kpis_db_user:TEST_DB_PASSWORD%3A%2F%40%27%3F%23@postgres:5432/kpis_db',
        'APP_SECRET': variables['kpis_app_secret'],
        'KPIS_DB_PASSWORD': variables['kpis_db_password'],
    }
    for key in ('kpis_db_password', 'kpis_app_secret', 'kpis_admin_password'):
        assert variables[key] not in deployment_text
    init_env = {item['name']: item for item in pod['initContainers'][0]['env']}
    assert init_env['PGPASSWORD']['valueFrom']['secretKeyRef'] == {'name': 'postgres', 'key': 'admin_password'}
    assert init_env['KPIS_DB_PASSWORD']['valueFrom']['secretKeyRef'] == {'name': 'kpis', 'key': 'KPIS_DB_PASSWORD'}
    for probe in ('livenessProbe', 'readinessProbe'):
        assert container[probe]['httpGet'] == {'path': '/api/heartbeat', 'port': 3000}
    assert container['resources']['limits']['memory'] == '512Mi'
    # THEN every object follows the namespace and only heartbeat is public at first.
    for manifest in (deployment, secret, service, ingress, bootstrap):
        assert manifest['metadata']['name'] == 'kpis'
        assert manifest['metadata']['namespace'] == (namespace or 'default')
    assert service['spec']['selector'] == deployment['spec']['selector']['matchLabels']
    assert service['spec']['ports'] == [{'port': 80, 'targetPort': 3000}]
    for manifest in (ingress, bootstrap):
        assert manifest['spec']['rules'][0]['host'] == 'kpis.example.com'
        assert manifest['spec']['tls'] == [{'hosts': ['kpis.example.com'], 'secretName': 'kpis-tls'}]
        assert manifest['metadata']['annotations']['cert-manager.io/issuer'] == 'letsencrypt-prod'
        assert manifest['metadata']['annotations']['traefik.ingress.kubernetes.io/router.middlewares'] == (namespace or 'default') + '-redirect-to-https@kubernetescrd'
    backend = {'service': {'name': 'kpis', 'port': {'number': 80}}}
    assert bootstrap['spec']['rules'][0]['http']['paths'] == [
        {'path': '/api/heartbeat', 'pathType': 'Exact', 'backend': backend},
    ]
    assert ingress['spec']['rules'][0]['http']['paths'] == [
        {'path': '/', 'pathType': 'Prefix', 'backend': backend},
    ]


def test_kpis_project_overrides_reach_manifests_and_public_api():
    # GIVEN a consuming project with a custom host, image pin and database names,
    variables = kpis_variables(kpis_host='metrics.example.com', kpis_version='3.4.1',
                               kpis_db_name='sample_metrics', kpis_db_user='sample_metrics_user')
    # WHEN Ansible renders the actual templates and public API tasks,
    deployment = yaml.safe_load(render('roles/kpis/templates/deployment.yml', variables))
    secret = yaml.safe_load(render('roles/kpis/templates/secret.yml', variables))
    ingress = yaml.safe_load(render('roles/kpis/templates/ingress.yml', variables))
    tasks = load('roles/kpis/tasks/main.yml')
    public_urls = [task['ansible.builtin.uri']['url'] for task in tasks
                   if task.get('ansible.builtin.uri', {}).get('url', '').startswith('https:')]
    # THEN project configuration reaches the pod, TLS and every public API URL.
    assert deployment['spec']['template']['spec']['containers'][0]['image'].endswith(':3.4.1')
    assert secret['stringData']['DATABASE_URL'].startswith('postgresql://sample_metrics_user:')
    assert secret['stringData']['DATABASE_URL'].endswith('/sample_metrics')
    assert ingress['spec']['rules'][0]['host'] == 'metrics.example.com'
    assert ingress['spec']['tls'][0]['hosts'] == ['metrics.example.com']
    assert public_urls == []
    assert all(templar(variables).template(trust_as_template(url)).startswith('https://metrics.example.com/')
               for url in public_urls)
    website = next(task['ansible.builtin.uri']['body'] for task in tasks if task['name'] == 'Create the configured website if missing')
    assert templar(variables).template(trust_as_template(website['name'])) == 'sample-startup'
    assert templar(variables).template(trust_as_template(website['id'])) == variables['kpis_website_id']


@pytest.mark.parametrize('overrides', [
    {'kpis_website_id': 'not-a-uuid'}, {'kpis_website_id': ''},
    {'kpis_access_mode': 'automatic'},
    {'kpis_access_mode': 'oauth2_proxy'},
    *[{'kpis_access_mode': 'oauth2_proxy', 'oauth2_proxy_enabled': True, 'kpis_allowed_emails': emails}
      for emails in ([], 'admin@example.test', {'admin': 'admin@example.test'},
                     ['*'], ['*@example.test'], ['admin@example.test,outsider@example.test'], [''])],
    {'kpis_admin_password': 'x' * 15}, {'kpis_db_password': ''}, {'kpis_app_secret': ''},
])
def test_kpis_safety_assert_rejects_unsafe_configuration(overrides):
    # GIVEN an invalid website UUID, short admin password or missing secret,
    variables = kpis_variables(**overrides)
    # WHEN Ansible evaluates the actual first task's safety assertions,
    # THEN configuration is rejected before applying any resource.
    assert not kpis_guard_allows(variables)
    tasks = load('roles/kpis/tasks/main.yml')
    assert 'ansible.builtin.assert' in tasks[0]
    assert tasks[0]['no_log'] is True
    assert tasks[0]['ansible.builtin.assert']['quiet'] is True


def test_kpis_bootstrap_replaces_default_password_before_public_ingress():
    # GIVEN the actual role tasks loaded by Ansible's role syntax check,
    tasks = load('roles/kpis/tasks/main.yml')
    # WHEN inspecting the bootstrap sequence and evaluating its service lookup,
    names = [task['name'] for task in tasks]
    restrict = names.index('Restrict public ingress to heartbeat during bootstrap')
    replace = names.index('Replace the default admin password before publishing the UI')
    verify = names.index('Verify the configured admin password privately')
    publish = names.index('Publish kpis ingress after the default login is disabled')
    lookup = next(task['kubernetes.core.k8s_info'] for task in tasks if 'kubernetes.core.k8s_info' in task)
    # THEN replacement and successful private verification precede full ingress.
    assert restrict < names.index('Apply kpis deployment') < replace < verify < publish
    assert tasks[restrict]['vars'] == {'kpis_bootstrap_only': True}
    assert 'kpis_bootstrap_only' not in tasks[publish].get('vars', {})
    assert templar(kpis_variables()).template(trust_as_template(lookup['namespace'])) == 'sample'
    default_namespace_variables = kpis_variables()
    del default_namespace_variables['k8s_namespace']
    assert templar(default_namespace_variables).template(trust_as_template(lookup['namespace'])) == 'default'
    assert tasks[replace]['when'] == 'kpis_initial_login.status == 200'
    assert tasks[replace]['ansible.builtin.uri']['body'] == {
        'currentPassword': 'umami', 'newPassword': '{{ kpis_admin_password }}',
    }
    assert tasks[verify]['ansible.builtin.uri']['body'] == {
        'username': 'admin', 'password': '{{ kpis_admin_password }}',
    }
    assert tasks[verify]['ansible.builtin.uri']['status_code'] == 200
    for task in tasks:
        uri = task.get('ansible.builtin.uri', {})
        if uri.get('url', '').startswith('http:'):
            assert uri['use_proxy'] is False
            assert '{{ kpis_service.resources[0].spec.clusterIP }}' in uri['url'] or uri['url'].endswith('/oauth2/auth')
        if uri.get('body') or uri.get('headers') or 'ansible.builtin.assert' in task or task['name'] == 'Apply kpis secret':
            assert task['no_log'] is True
    assert tasks[1]['diff'] is False
    assert names.index('Check for the configured website') < names.index('Verify the configured website exists before publishing') < publish
    assert names.index('Verify the default admin password is rejected privately') < publish


def oauth2_proxy_variables(**overrides):
    return {
        **{key: trust_as_template(value) if isinstance(value, str) else value
           for key, value in load('roles/oauth2-proxy/defaults/main.yml').items()},
        'base_domain': 'example.com', 'auth_domain': 'https://login.example.com',
        'auth_audience': 'https://example.com/private_api', 'k8s_namespace': 'sample',
        'ansible_date_time': {'iso8601_basic': '20261011T120000'},
        'oauth2_proxy_client_id': 'test-client-id',
        'oauth2_proxy_client_secret': 'test-client-secret',
        'oauth2_proxy_cookie_secret': base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('='),
        **overrides,
    }


def oauth2_proxy_guard_allows(variables):
    guard = load('roles/oauth2-proxy/tasks/main.yml')[0]['ansible.builtin.assert']
    return all(templar(variables).evaluate_expression(trust_as_template(expression))
               for expression in guard['that'])


def test_oauth2_proxy_render_preserves_browser_and_bearer_authentication():
    # GIVEN shared-role defaults and a project's OIDC configuration,
    variables = oauth2_proxy_variables()
    assert oauth2_proxy_guard_allows(variables)
    # WHEN Ansible renders the actual Deployment, Service and Secret,
    deployment_text = render('roles/oauth2-proxy/templates/deployment.yml', variables)
    deployment = yaml.safe_load(deployment_text)
    service = yaml.safe_load(render('roles/oauth2-proxy/templates/service.yml', variables))
    secret = yaml.safe_load(render('roles/oauth2-proxy/templates/secret.yml', variables))
    container = deployment['spec']['template']['spec']['containers'][0]
    # THEN protected writes, anonymous preflight and both caller paths survive.
    assert '--skip-auth-route=!=^/private_api' in container['args']
    assert '--skip-auth-route=OPTIONS=^/private_api' in container['args']
    assert '--skip-jwt-bearer-tokens=true' in container['args']
    assert '--pass-authorization-header=true' in container['args']
    assert '--extra-jwt-issuers=https://login.example.com/=https://example.com/private_api' in container['args']
    assert '--oidc-issuer-url=https://login.example.com/' in container['args']
    assert '--redirect-url=https://backend.example.com/oauth2/callback' in container['args']
    assert '--upstream=http://backend.sample.svc.cluster.local:8000' in container['args']
    assert '--cookie-domain=.example.com' in container['args']
    assert container['image'].endswith(':' + variables['oauth2_proxy_version'])
    # THEN credentials reach the pod only through the namespaced Secret.
    assert container['envFrom'] == [{'secretRef': {'name': secret['metadata']['name']}}]
    assert 'env' not in container
    assert set(secret['data']) == {'OAUTH2_PROXY_CLIENT_ID', 'OAUTH2_PROXY_CLIENT_SECRET', 'OAUTH2_PROXY_COOKIE_SECRET'}
    for key in ('client_id', 'client_secret', 'cookie_secret'):
        value = variables['oauth2_proxy_' + key]
        assert value not in deployment_text
        assert not any(arg.startswith('--' + key.replace('_', '-') + '=') for arg in container['args'])
        assert base64.b64decode(secret['data']['OAUTH2_PROXY_' + key.upper()]).decode() == value
    for manifest in (deployment, service, secret):
        assert manifest['metadata']['namespace'] == 'sample'
    assert service['spec']['selector'] == deployment['spec']['selector']['matchLabels']


@pytest.mark.parametrize('overrides', [
    {'oauth2_proxy_skip_auth_route': '=^/private_api'},
    {'oauth2_proxy_cookie_secret': 'too-short'},
    {'oauth2_proxy_cookie_secret': 'x' * 33},
    {'oauth2_proxy_cookie_secret': 'é' * 16 + 'x'},
    {'oauth2_proxy_cookie_secret': base64.urlsafe_b64encode(bytes(range(20))).decode().rstrip('=')},
    {'oauth2_proxy_cookie_secret': base64.b64encode(b'\xff' * 32).decode()},
    {'oauth2_proxy_client_id': ''},
    {'oauth2_proxy_client_secret': ''},
    {'oauth2_proxy_extra_jwt_issuers': 'https://login.example.com/'},
])
def test_oauth2_proxy_safety_assert_rejects_unsafe_configuration(overrides):
    # GIVEN a missing negation, invalid cookie, missing client credential or audience,
    variables = oauth2_proxy_variables(**overrides)
    # WHEN Ansible evaluates the actual first task's safety assertions,
    # THEN it rejects the configuration before any Kubernetes resource is applied.
    assert not oauth2_proxy_guard_allows(variables)
    tasks = load('roles/oauth2-proxy/tasks/main.yml')
    assert 'ansible.builtin.assert' in tasks[0]
    assert tasks[1]['no_log'] is True
    assert tasks[1]['diff'] is False


@pytest.mark.parametrize('length', [16, 24, 32])
@pytest.mark.parametrize('encoding', ['raw', 'padded', 'unpadded'])
def test_oauth2_proxy_safety_assert_accepts_valid_cookie_bytes(length, encoding):
    # GIVEN an AES-length raw secret or binary secret in the URL-safe alphabet,
    secret = 'x' * length if encoding == 'raw' else base64.urlsafe_b64encode(b'\xff' * length).decode()
    if encoding == 'unpadded':
        secret = secret.rstrip('=')
    # WHEN Ansible evaluates the role guard, THEN both padding forms are accepted.
    assert oauth2_proxy_guard_allows(oauth2_proxy_variables(oauth2_proxy_cookie_secret=secret))


@pytest.mark.parametrize("observed,expected", [
    (state(["one"]), "one"),
    (state(["one", "two"], selected="two"), "two"),
    (state(["one", "two"], pods=["two"]), "two"),
    (state(["one", "two"], recorded="two"), "two"),
    (state(["one", "two"], pods=["two"], recorded="two"), "two"),
])
def test_database_stays_on_its_data_node(observed, expected):
    facts = apply_preflight(observed)
    assert facts["postgres_selected_node"] == expected
    deployment = yaml.safe_load(render("roles/postgres/templates/deployment.yml", {
        **facts, "postgres_version": "17.11", "k8s_namespace": "sample",
    }))
    term = deployment["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]
    assert term["matchFields"] == [{"key": "metadata.name", "operator": "In", "values": [expected]}]
    volume = next(yaml.safe_load_all(render("roles/postgres/templates/persistent-volume.yml", {
        **facts, "postgres_pv_name": "sample-postgres", "project_name": "sample",
        "postgres_data_path": "/srv/sample/postgres", "k8s_namespace": "sample",
    })))
    assert volume["metadata"]["annotations"]["startup.deploy/storage-node"] == expected


@pytest.mark.parametrize("observed", [
    state(["one", "two"]),
    state(["one", "two"], pods=["one"], selected="two"),
    state(["one", "two"], recorded="one", selected="two"),
    state(["one"], recorded="gone"),
    state(["one", "two"], pods=["one", "two"]),
    state(["one", "two"], pods=["two"], recorded="one"),
    state([]),
])
def test_ambiguous_or_moved_database_is_rejected(observed):
    with pytest.raises(ValueError):
        apply_preflight(observed)


@pytest.mark.parametrize("authorized", [False, True])
def test_worker_deletion_requires_opt_in_and_a_successful_drain(authorized):
    tasks = load("roles/hetzner-server/tasks/main.yml")
    guard = next(t for t in tasks if t["name"] == "Require explicit authorization to remove workers")
    expression = guard["ansible.builtin.assert"]["that"][0]
    assert templar({"allow_worker_teardown": authorized}).evaluate_expression(trust_as_template(expression)) is authorized
    guard_index = tasks.index(guard)
    drain_index = next(i for i, t in enumerate(tasks) if t["name"] == "Drain surplus nodes before deleting servers")
    delete_index = next(i for i, t in enumerate(tasks) if t["name"] == "Delete surplus servers")
    assert guard_index < drain_index < delete_index
    drain = tasks[drain_index]
    assert "ignore_errors" not in drain
    assert "failed_when" not in drain
    assert "--force" not in drain["ansible.builtin.command"]["argv"]
    assert "--delete-emptydir-data" not in drain["ansible.builtin.command"]["argv"]


def test_k3s_token_never_enters_install_command_or_task_output():
    tasks = list(walk(load("roles/k3s/tasks/main.yml")))
    installs = [t for t in tasks if "https://get.k3s.io" in t.get("ansible.builtin.shell", "")]
    assert len(installs) == 4
    for task in installs:
        assert "K3S_TOKEN" not in task["ansible.builtin.shell"]
        assert task["environment"]["K3S_TOKEN"]
        assert task["no_log"] is True


def test_secret_manifests_are_censored_even_with_diff():
    count = 0
    for path in (ROOT / "roles").glob("*/tasks/*.yml"):
        for task in walk(yaml.safe_load(path.read_text())):
            module = task.get("kubernetes.core.k8s", {})
            if "secret" in module.get("definition", ""):
                count += 1
                assert task["no_log"] is True, path
                assert task["diff"] is False, path
    assert count >= 6


def test_cloud_init_contains_only_the_single_use_key():
    content = render("roles/hetzner-server/templates/cloud-init-tailscale.yml.j2", {
        "tailscale_auth_key": "tskey-client-LONG-LIVED-MUST-STAY-ON-CONTROLLER",
        "tailscale_boot_keys": {"sample-master-0": "tskey-auth-single-use-test"},
        "server_name": "sample-master-0", "tailscale_tags": ["tag:server"],
    })
    assert "tskey-client" not in content
    assert "tskey-auth-single-use-test" in content
    assert yaml.safe_load(content)["runcmd"]
    tasks = list(walk(load("roles/tailscale-auth/tasks/main.yml")))
    key_request = next(t["ansible.builtin.uri"] for t in tasks if t.get("ansible.builtin.uri", {}).get("url", "").endswith("/keys"))
    assert key_request["body"]["expirySeconds"] == 600
    assert key_request["body"]["capabilities"]["devices"]["create"]["reusable"] is False
    for task in tasks:
        if "ansible.builtin.uri" in task:
            assert task["delegate_to"] == "localhost"
            assert task["become"] is False
    assert load("roles/tailscale-auth/tasks/main.yml")[0]["no_log"] is True


def test_cloud_init_join_keys_are_not_generated_for_existing_servers():
    tasks = load("roles/hetzner-server/tasks/main.yml")
    mint = next(t for t in tasks if t["name"] == "Generate join keys only for new private servers")
    base = {"tailscale_enabled": True, "ansible_check_mode": False, "tailscale_new_server_name": "sample-master-0"}
    for existing, expected in [([], True), ([{"name": "sample-master-0"}], False)]:
        variables = {**base, "preflight_nodes": {"hcloud_server_info": existing}}
        assert all(templar(variables).evaluate_expression(trust_as_template(e)) for e in mint["when"]) is expected


@pytest.mark.parametrize("email", ["", "ops@example.com"])
def test_acme_account_uses_only_the_operators_contact(email):
    issuer = yaml.safe_load(render("roles/cert-manager/templates/cert-manager-issuers.yml", {
        "cert_manager_acme_email": email, "cert_manager_solver": "http01",
        "k8s_namespace": "sample",
    }))
    acme = issuer["spec"]["acme"]
    assert acme.get("email", "") == email
    assert "philipp" not in str(issuer)


def test_sensitive_upgrade_failure_is_not_reprinted_by_rescue():
    upgrade = next(t for t in load("roles/k3s/tasks/main.yml") if t["name"] == "Upgrade k3s")
    message = next(t["ansible.builtin.fail"]["msg"] for t in upgrade["rescue"] if "ansible.builtin.fail" in t)
    result = templar({
        "inventory_hostname": "sample-master-0", "k3s_installed_version": "v1.36.3+k3s1",
        "k3s_version": "v1.36.5+k3s1", "is_master": False, "k3s_service_name": "k3s",
        "ansible_failed_task": {"name": "Run installer with target version"},
        "ansible_failed_result": {"_ansible_no_log": True, "msg": "sentinel-secret", "stdout": "sentinel-secret", "stderr": "sentinel-secret"},
        "upgrade_failure_logs": {"stdout": "test service log"},
    }).template(trust_as_template(message))
    assert "sentinel-secret" not in result
    assert "sensitive task output hidden" in result


def test_tag_filtered_infrastructure_runs_include_join_key_tasks():
    tasks = load("roles/hetzner-server/tasks/main.yml")
    mint = next(t for t in tasks if t["name"] == "Generate join keys only for new private servers")
    assert mint["ansible.builtin.include_tasks"]["apply"]["tags"] == "infrastructure"
    for path in ["roles/hetzner-server/tasks/mint-join-key.yml", "roles/tailscale/tasks/main.yml"]:
        role = next(t["ansible.builtin.include_role"] for t in walk(load(path)) if t.get("ansible.builtin.include_role", {}).get("name") == "tailscale-auth")
        assert "infrastructure" in role["apply"]["tags"]


@pytest.mark.parametrize("count,allowed", [(0, True), (1, False), (2, False), (3, True)])
def test_partial_gateway_api_installation_cannot_be_overwritten(count, allowed):
    tasks = load("roles/cert-manager/tasks/preflight.yml")
    guard = next(t for t in tasks if t["name"] == "Refuse to overwrite a partially installed Gateway API")
    expression = guard["ansible.builtin.assert"]["that"][0]
    assert templar({"cert_manager_gateway_crd_count": count}).evaluate_expression(trust_as_template(expression)) is allowed


@pytest.mark.parametrize("filename", ["install_with_helm.yml", "install_with_k3s_helm.yml"])
def test_cert_manager_leaves_cluster_owned_gateway_crds_alone(filename):
    tasks = load("roles/cert-manager/tasks/" + filename)
    for task in tasks[:2]:
        for existing, expected in [(0, True), (3, False)]:
            variables = {"cert_manager_install_cluster_wide": True, "cert_manager_gateway_crd_count": existing}
            assert all(templar(variables).evaluate_expression(trust_as_template(e)) for e in task["when"]) is expected


@pytest.mark.parametrize('role,template', [
    ('hetzner-cloud-controller-manager', 'helm-chart-config.yml'),
    ('hetzner-csi-provider', 'helm-chart.yml'),
    ('cert-manager', 'webhook-helmchart.yaml.j2'),
])
def test_optional_charts_render_an_explicit_published_version(role, template):
    # GIVEN role defaults, WHEN a real HelmChart is rendered, THEN installs are pinned.
    variables = load(f'roles/{role}/defaults/main.yml')
    manifest = yaml.safe_load(render(f'roles/{role}/templates/{template}', variables))
    assert manifest['spec']['version']


def test_deploy_action_uses_pipeable_cli_credentials_and_complete_exports(tmp_path):
    # GIVEN the actual composite action, WHEN its shell steps are parsed,
    # THEN CI keeps Vault credentials out of argv and exports the full runtime.
    import subprocess
    action = load('.github/actions/deploy/action.yml')
    scripts = [step['run'] for step in action['runs']['steps'] if 'run' in step]
    for index, script in enumerate(scripts):
        path = tmp_path / f'step-{index}.sh'
        path.write_text(script)
        subprocess.run(['bash', '-n', str(path)], check=True)
    combined = '\n'.join(scripts)
    assert '--vault_password' not in combined
    assert 'ansible-vault view' not in combined
    assert 'startup secrets get-file --file ci_ssh_key | ssh-add -' in combined
    # WHEN the actual export script runs against a real checkout,
    # THEN every root playbook/config and role byte reaches the CI workspace.
    export = next(step['run'] for step in action['runs']['steps']
                  if step.get('name') == 'Export shared Ansible roles')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    export = export.replace('${{ github.workspace }}', str(workspace))
    import os
    subprocess.run(['bash', '-c', export], check=True,
                   env={**os.environ, 'ACTION_REPO_ROOT': str(ROOT / '.github/actions/deploy')})
    target = workspace / 'deployment/.shared-roles'
    expected = [p for p in ROOT.glob('*playbook.yml')]
    expected += [ROOT / p for p in ['ansible.cfg', 'requirements.yml', 'inventory.ini', 'inventory.hcloud.yml']]
    expected += [p for p in (ROOT / 'roles').rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix != '.pyc']
    for source in expected:
        assert (target / source.relative_to(ROOT)).read_bytes() == source.read_bytes()
    join = (ROOT / '.github/actions/join-tailnet/read-credentials.sh').read_text()
    assert ' -p ' not in join
    subprocess.run(['bash', '-n'], input=join, text=True, check=True)


def test_kpis_allowlist_uses_exact_encoded_session_emails():
    import urllib.parse
    # GIVEN an explicit list including a plus-address and the real Ansible guard,
    variables = kpis_variables(kpis_access_mode='oauth2_proxy', oauth2_proxy_enabled=True,
                               kpis_allowed_emails=['owner@example.test', 'analyst+metrics@example.test'])
    assert kpis_guard_allows(variables)
    # WHEN rendering the shipped ForwardAuth manifest, THEN it sends a fixed
    # exact-email constraint to the existing service without adding a proxy pod.
    manifest = yaml.safe_load(render('roles/kpis/templates/oauth-middlewares.yml', variables))
    auth = next(item['spec']['forwardAuth'] for item in manifest['items']
                if item['metadata']['name'] == 'kpis-auth')
    address = urllib.parse.urlsplit(auth['address'])
    assert address.netloc == 'oauth2-proxy.sample.svc.cluster.local:80'
    assert urllib.parse.parse_qs(address.query) == {
        'allowed_emails': ['owner@example.test,analyst+metrics@example.test']}
    assert auth['authRequestHeaders'] == ['Cookie']
