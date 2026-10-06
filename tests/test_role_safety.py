"""Exercise role guards with Ansible's expression engine and rendered manifests."""
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
