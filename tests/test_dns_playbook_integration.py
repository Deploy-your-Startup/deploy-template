"""GIVEN a project's domain vars, WHEN the DNS-only playbook runs against a Hetzner
API stand-in, THEN the zone and A records point at the cluster and nothing else
is provisioned.

The Hetzner Cloud API is the provider boundary. A local HTTP stand-in speaks its
zone/action protocol; ansible-playbook, the hcloud collection and the
hetzner-dns role run unchanged.
"""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, unquote, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
CREATED = "2026-01-01T00:00:00+00:00"


def zone_body(zone_id, name):
    return {
        "id": zone_id,
        "name": name,
        "created": CREATED,
        "mode": "primary",
        "primary_nameservers": [],
        "labels": {},
        "protection": {"delete": False},
        "ttl": 3600,
        "status": "ok",
        "record_count": 0,
        "authoritative_nameservers": {
            "assigned": ["hydrogen.ns.hetzner.com."],
            "delegated": [],
            "delegation_last_check": None,
            "delegation_status": "unknown",
        },
        "registrar": "other",
    }


def action_body(action_id, command):
    return {
        "id": action_id,
        "command": command,
        "status": "success",
        "progress": 100,
        "started": CREATED,
        "finished": CREATED,
        "resources": [],
        "error": None,
    }


@pytest.fixture
def hetzner():
    state = {"zones": {}, "rrsets": {}, "requests": [], "next_id": 1}

    class Api(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def not_found(self):
            self.reply(404, {"error": {"code": "not_found", "message": "not found"}})

        def find_zone(self, key):
            for zone in state["zones"].values():
                if str(zone["id"]) == key or zone["name"] == key:
                    return zone
            return None

        def new_id(self):
            state["next_id"] += 1
            return state["next_id"]

        def do_GET(self):
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p][1:]
            state["requests"].append(("GET", "/".join(parts)))
            if parts == ["zones"]:
                name = parse_qs(url.query).get("name", [None])[0]
                zones = [z for z in state["zones"].values() if name in (None, z["name"])]
                return self.reply(200, {"zones": zones, "meta": {"pagination": {
                    "page": 1, "per_page": 50, "previous_page": None,
                    "next_page": None, "last_page": 1, "total_entries": len(zones)}}})
            if parts[:1] == ["actions"]:
                return self.reply(200, {"action": action_body(int(parts[1]), "done")})
            if parts[:1] == ["zones"] and len(parts) == 2:
                zone = self.find_zone(parts[1])
                return self.reply(200, {"zone": zone}) if zone else self.not_found()
            if parts[:1] == ["zones"] and parts[2:3] == ["rrsets"] and len(parts) == 5:
                zone = self.find_zone(parts[1])
                rrset = state["rrsets"].get((zone["name"], parts[3], parts[4])) if zone else None
                return self.reply(200, {"rrset": rrset}) if rrset else self.not_found()
            return self.not_found()

        def do_POST(self):
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p][1:]
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            state["requests"].append(("POST", "/".join(parts)))
            if parts == ["zones"]:
                zone = zone_body(self.new_id(), body["name"])
                state["zones"][body["name"]] = zone
                return self.reply(201, {"zone": zone, "action": action_body(self.new_id(), "create_zone")})
            if parts[:1] == ["zones"] and parts[2:] == ["rrsets"]:
                zone = self.find_zone(parts[1])
                rrset = {
                    "id": f"{body['name']}/{body['type']}",
                    "name": body["name"],
                    "type": body["type"],
                    "ttl": body.get("ttl"),
                    "labels": body.get("labels") or {},
                    "protection": {"change": False},
                    "records": [{"value": r["value"], "comment": r.get("comment")} for r in body["records"]],
                    "zone": zone["id"],
                }
                state["rrsets"][(zone["name"], body["name"], body["type"])] = rrset
                return self.reply(201, {"rrset": rrset, "action": action_body(self.new_id(), "create_rrset")})
            return self.not_found()

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["endpoint"] = f"http://127.0.0.1:{server.server_port}/v1"
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


def run_playbook(hetzner, tmp_path, extra_vars):
    vars_file = tmp_path / "vars.json"
    vars_file.write_text(json.dumps(extra_vars))
    env = {
        **os.environ,
        "HCLOUD_TOKEN": "stand-in-token",
        "HCLOUD_ENDPOINT": hetzner["endpoint"],
        "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
        "ANSIBLE_CONFIG": str(tmp_path / "none.cfg"),
    }
    return subprocess.run(
        ["ansible-playbook", str(ROOT / "dns-playbook.yml"), "-i", "localhost,",
         "--extra-vars", f"@{vars_file}"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )


def test_attached_startup_gets_zone_and_records_for_the_cluster(hetzner, tmp_path):
    # GIVEN an attached startup's domain and the shared cluster's address.
    project = {"base_domain": "sample.de", "additional_domains": [], "dns_target_ip": "203.0.113.10"}
    # WHEN the DNS-only playbook runs.
    result = run_playbook(hetzner, tmp_path, project)
    # THEN the zone exists and apex and wildcard point at the cluster.
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(hetzner["zones"]) == ["sample.de"]
    records = {(name, kind): [r["value"] for r in rrset["records"]]
               for (_, name, kind), rrset in hetzner["rrsets"].items()}
    assert records == {("@", "A"): ["203.0.113.10"], ("*", "A"): ["203.0.113.10"]}
    # AND only zone, record and action endpoints were used - no servers or networks.
    assert {path.split("/")[0] for _, path in hetzner["requests"]} <= {"zones", "actions"}


def test_missing_cluster_address_stops_before_any_api_call(hetzner, tmp_path):
    # GIVEN a project without the cluster address.
    # WHEN the playbook runs.
    result = run_playbook(hetzner, tmp_path, {"base_domain": "sample.de", "additional_domains": []})
    # THEN it fails before talking to Hetzner.
    assert result.returncode != 0
    assert "dns_target_ip must be the cluster's public IPv4 address" in result.stdout
    assert hetzner["requests"] == []
