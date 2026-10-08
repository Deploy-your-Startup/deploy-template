"""Run real Ansible roles with a file-backed Kubernetes provider boundary."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

PROVIDER = '''
import json, os
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule
module = AnsibleModule(argument_spec=dict(
    kind=dict(type='str'), namespace=dict(type='str'), name=dict(type='str'),
    api_version=dict(type='str'), label_selectors=dict(type='list'),
    state=dict(type='str'), definition=dict(type='raw'),
))
path = Path(os.environ['TEST_KUBERNETES_STATE'])
objects = json.loads(path.read_text())
params = module.params
definition = params['definition']
if definition is not None:
    import yaml
    if isinstance(definition, str): definition = yaml.safe_load(definition)
    metadata = definition['metadata']
    key = '/'.join([definition['kind'], metadata.get('namespace', ''), metadata['name']])
    changed = objects.get(key) != definition
    objects[key] = definition
    path.write_text(json.dumps(objects))
    module.exit_json(changed=changed, result=definition)
resources = [obj for obj in objects.values()
    if obj['kind'] == params['kind']
    and (not params['namespace'] or obj['metadata'].get('namespace') == params['namespace'])
    and (not params['name'] or obj['metadata']['name'] == params['name'])]
module.exit_json(changed=False, resources=resources)
'''


@pytest.fixture
def cluster_boundary(tmp_path):
    modules = tmp_path / "collections/ansible_collections/kubernetes/core/plugins/modules"
    modules.mkdir(parents=True)
    for name in ("k8s", "k8s_info"):
        (modules / f"{name}.py").write_text(PROVIDER)
    state = tmp_path / "cluster.json"
    state.write_text("{}")
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "roles": ["project-namespace"],
    }]))
    env = {
        **os.environ, "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
        "ANSIBLE_COLLECTIONS_PATH": str(tmp_path / "collections"),
        "TEST_KUBERNETES_STATE": str(state),
        "ANSIBLE_PYTHON_INTERPRETER": str(Path(os.sys.executable)),
    }
    def deploy(name, *, managed=False, identity="a" * 32):
        variables = {
            "project_name": name, "k8s_namespace": name,
            "startup_cluster_id": identity, "startup_cluster_owner": "sample/owner",
            "startup_project_owner": "sample/" + name,
            "startup_cluster_managed": managed, "startup_namespace_policy": True,
        }
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook), "--extra-vars", json.dumps(variables)],
            cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=45,
        )
    return deploy, state


def test_two_startups_receive_separate_owned_namespaces_and_policies(cluster_boundary):
    # GIVEN a new cluster and the actual namespace role.
    deploy, state = cluster_boundary
    # WHEN the owner deploys and a second startup attaches through the real playbook.
    for name, managed in (("owner", True), ("second", False)):
        result = deploy(name, managed=managed)
        assert result.returncode == 0, result.stdout + result.stderr
    objects = json.loads(state.read_text())
    # THEN both have their own defaults, quotas, network policies and ownership.
    for name in ("owner", "second"):
        assert objects[f"Namespace//{name}"]["metadata"]["annotations"]["startup.deploy/owner"] == f"sample/{name}"
        assert objects[f"ResourceQuota/{name}/startup-budget"]["spec"]["hard"]["pods"] == "20"
        policy = objects[f"NetworkPolicy/{name}/startup-boundary"]["spec"]
        assert policy["policyTypes"] == ["Ingress", "Egress"]
        assert policy["ingress"][0]["from"][1]["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "kube-system"}
    snapshot = state.read_bytes()
    assert deploy("second").returncode == 0
    assert state.read_bytes() == snapshot


def test_attached_startup_cannot_claim_an_unregistered_cluster(cluster_boundary):
    # GIVEN an empty cluster, WHEN an attached startup runs its deploy.
    deploy, state = cluster_boundary
    result = deploy("second")
    # THEN no identity, namespace or policy is created.
    assert result.returncode != 0
    assert "server is not the registered shared cluster" in result.stdout
    assert json.loads(state.read_text()) == {}


def test_wrong_cluster_identity_is_rejected_without_changes(cluster_boundary):
    # GIVEN an owner's registered cluster, WHEN a foreign descriptor is used.
    deploy, state = cluster_boundary
    assert deploy("owner", managed=True).returncode == 0
    snapshot = state.read_bytes()
    result = deploy("second", identity="b" * 32)
    # THEN the foreign startup creates nothing and the owner is untouched.
    assert result.returncode != 0
    assert state.read_bytes() == snapshot


def test_foreign_namespace_is_not_adopted(cluster_boundary):
    # GIVEN a cluster with an existing unrelated namespace of the requested name.
    deploy, state = cluster_boundary
    assert deploy("owner", managed=True).returncode == 0
    objects = json.loads(state.read_text())
    objects["Namespace//second"] = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "second"}}
    state.write_text(json.dumps(objects))
    snapshot = state.read_bytes()
    # WHEN the new startup deploys, THEN it is rejected without changing that namespace.
    result = deploy("second")
    assert result.returncode != 0
    assert "namespace already exists" in result.stdout
    assert state.read_bytes() == snapshot
