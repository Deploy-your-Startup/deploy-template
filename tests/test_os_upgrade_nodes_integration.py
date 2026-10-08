"""Run the complete shared playbook on disposable Ubuntu Docker nodes.

Ansible, apt, dpkg, remote file installation and async execution are real.
Release upgrades, reboots and Kubernetes are VM/cluster boundary stand-ins:
containers cannot reboot a kernel or host a production k3s control plane.
"""

import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, **kwargs):
    return subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=True, **kwargs
    )


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    if not shutil.which("docker"):
        if os.environ.get("STARTUP_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("Docker is required for OS upgrade node integration in CI")
        pytest.skip("Docker is required for disposable Ubuntu node integration")
    availability = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    if availability.returncode:
        if os.environ.get("STARTUP_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail(
                "Docker daemon is required for OS upgrade node integration in CI"
            )
        pytest.skip("Docker daemon is unavailable")
    root = tmp_path_factory.mktemp("os-upgrade-image")
    (root / "Dockerfile").write_text("""FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y python3 python3-apt && mkdir -p /etc/update-manager && printf '[DEFAULT]\\nPrompt=lts\\n' > /etc/update-manager/release-upgrades
COPY boundary.py /usr/local/bin/do-release-upgrade
RUN chmod 755 /usr/local/bin/do-release-upgrade && ln -s /usr/local/bin/do-release-upgrade /usr/local/bin/k3s && ln -s /usr/local/bin/do-release-upgrade /usr/local/bin/systemctl && ln -s /usr/local/bin/do-release-upgrade /usr/local/sbin/shutdown
CMD ["sleep", "infinity"]
""")
    (root / "boundary.py").write_text("""#!/usr/bin/python3
import fcntl, json, os, pathlib, sys, uuid
node = os.environ['NODE_NAME']
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
shared = pathlib.Path('/test')
def event(action, host=node):
    with (shared / 'events.jsonl').open('a') as log:
        fcntl.flock(log, fcntl.LOCK_EX)
        log.write(json.dumps([action, host]) + '\\n')
if name == 'do-release-upgrade':
    if '-c' in args:
        print("New release '26.04.1 LTS' available.")
    else:
        event('upgrade')
        pathlib.Path('/etc/os-release').write_text('ID=ubuntu\\nVERSION="26.04.1 LTS"\\nVERSION_ID="26.04"\\n')
        pathlib.Path('/var/run/reboot-required').touch()
        if (shared / 'break-after-first-upgrade').exists() and node == 'node-a':
            (shared / 'unhealthy-node').touch()
elif name == 'shutdown':
    event('reboot')
    pathlib.Path('/node-boot-id').write_text(str(uuid.uuid4()))
    pathlib.Path('/var/run/reboot-required').unlink(missing_ok=True)
elif name == 'systemctl':
    event('service')
    print('active')
elif name == 'k3s':
    if 'get' in args:
        print(json.dumps({'items': [{'metadata': {'name': n}, 'spec': {}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}} for n in ['node-a', 'node-b']]}))
    elif 'drain' in args or 'uncordon' in args:
        event(args[1], args[2])
    elif 'wait' in args:
        event('health')
        target = next((a.split('/', 1)[1] for a in args if a.startswith('node/')), None)
        if target and (shared / 'transient-api-on-reboot').exists() and not pathlib.Path('/var/run/reboot-required').exists() and pathlib.Path('/var/lib/startup/os-upgrade/result.json').exists():
            marker = pathlib.Path('/api-recovered-' + target)
            if not marker.exists():
                marker.touch()
                event('api-unavailable', target)
                print('Error from server (ServiceUnavailable)', file=sys.stderr)
                sys.exit(1)
        if (shared / 'unhealthy-node').exists():
            sys.exit(1)
""")
    tag = "startup-os-upgrade-integration:local"
    built = docker("build", "-t", tag, str(root), timeout=300)
    assert "ERROR" not in built.stderr, built.stdout + built.stderr
    return tag


@pytest.fixture
def https_health(tmp_path):
    certificate = tmp_path / "certificate.pem"
    key = tmp_path / "certificate-key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        capture_output=True,
        check=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"healthy")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("localhost", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_port}/health", str(certificate)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def cluster(image, tmp_path, https_health):
    containers = {}
    try:
        for node in ["node-a", "node-b"]:
            identifier = docker(
                "run", "-d", "-v", f"{tmp_path}:/test", "-e", f"NODE_NAME={node}", image
            ).stdout.strip()
            containers[node] = identifier
            docker("exec", identifier, "sh", "-c", "printf initial > /node-boot-id")
        inventory = {
            "all": {
                "children": {
                    "production": {
                        "hosts": {
                            node: {"ansible_host": identifier}
                            for node, identifier in containers.items()
                        }
                    },
                    "hcloud_type_master": {"hosts": {"node-a": {}}},
                },
                "vars": {
                    "ansible_connection": "community.docker.docker",
                    "ansible_python_interpreter": "/usr/bin/python3",
                    "ansible_user": "root",
                },
            }
        }
        (tmp_path / "inventory.yml").write_text(yaml.safe_dump(inventory))
        url, certificate = https_health
        (tmp_path / "vars.json").write_text(
            json.dumps(
                {
                    "os_upgrade_environment": "production",
                    "os_upgrade_target": "26.04",
                    "os_upgrade_execute": True,
                    "os_upgrade_backup_confirmed": True,
                    "os_upgrade_health_urls": [url],
                    "os_upgrade_health_ca_path": certificate,
                    "os_upgrade_boot_time_command": "cat /node-boot-id",
                    "os_upgrade_health_timeout": 10,
                }
            )
        )
        (tmp_path / "ansible.cfg").write_text("[defaults]\nhost_key_checking = True\n")
        yield tmp_path, containers
    finally:
        for identifier in containers.values():
            docker("rm", "-f", identifier)


def run_upgrade(cluster):
    root, _ = cluster
    return subprocess.run(
        [
            str(Path(sys.executable).parent / "ansible-playbook"),
            str(ROOT / "os-upgrade-playbook.yml"),
            "-i",
            str(root / "inventory.yml"),
            "-l",
            "production",
            "-e",
            f"@{root / 'vars.json'}",
        ],
        env={**os.environ, "ANSIBLE_CONFIG": str(root / "ansible.cfg")},
        text=True,
        capture_output=True,
        timeout=180,
    )


def events(cluster):
    root, _ = cluster
    return [
        json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()
    ]


def test_serial_upgrade_verifies_each_node_and_is_idempotent(cluster):
    # GIVEN two Ubuntu nodes, WHEN the complete real playbook executes, THEN
    # each node is drained, upgraded, rebooted and verified before the next.
    root, _ = cluster
    (root / "transient-api-on-reboot").touch()
    result = run_upgrade(cluster)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = events(cluster)
    assert ["api-unavailable", "node-a"] in calls
    assert ["api-unavailable", "node-b"] in calls
    assert (
        calls.index(["upgrade", "node-a"])
        < calls.index(["reboot", "node-a"])
        < calls.index(["uncordon", "node-a"])
        < calls.index(["upgrade", "node-b"])
    )
    assert ["drain", "node-b"] in calls and ["reboot", "node-b"] in calls
    _, containers = cluster
    for identifier in containers.values():
        journal = json.loads(
            docker(
                "exec", identifier, "cat", "/var/lib/startup/os-upgrade/result.json"
            ).stdout
        )
        assert journal["status"] == "verified" and journal["target"] == "26.04"
    # WHEN the owner reruns, THEN no release upgrade or reboot repeats.
    result = run_upgrade(cluster)
    assert result.returncode == 0, result.stdout + result.stderr
    assert events(cluster).count(["upgrade", "node-a"]) == 1
    assert events(cluster).count(["upgrade", "node-b"]) == 1
    assert events(cluster).count(["reboot", "node-a"]) == 1


def test_preflight_checks_entire_selection_before_upgrading_first_node(cluster):
    # GIVEN the second node has an invalid release channel, WHEN execution is
    # requested, THEN even the eligible first node remains unchanged.
    root, containers = cluster
    docker(
        "exec",
        containers["node-b"],
        "sh",
        "-c",
        "printf '[DEFAULT]\\nPrompt=normal\\n' > /etc/update-manager/release-upgrades",
    )
    result = run_upgrade(cluster)
    assert result.returncode != 0 and "Prompt=lts" in result.stdout
    assert not (root / "events.jsonl").exists()
    for identifier in containers.values():
        assert (
            'VERSION_ID="24.04"'
            in docker("exec", identifier, "cat", "/etc/os-release").stdout
        )


def test_failed_health_stops_fleet_and_rerun_resumes_verification(cluster):
    # GIVEN the first upgraded node fails its health check, WHEN the playbook
    # executes, THEN the second node stays untouched and a rerun verifies the
    # completed upgrade before proceeding, without upgrading the first twice.
    root, _ = cluster
    (root / "break-after-first-upgrade").touch()
    result = run_upgrade(cluster)
    assert result.returncode != 0, result.stdout + result.stderr
    assert ["upgrade", "node-a"] in events(cluster)
    assert ["upgrade", "node-b"] not in events(cluster)
    (root / "unhealthy-node").unlink()
    result = run_upgrade(cluster)
    assert result.returncode == 0, result.stdout + result.stderr
    assert events(cluster).count(["upgrade", "node-a"]) == 1
    assert events(cluster).count(["upgrade", "node-b"]) == 1
