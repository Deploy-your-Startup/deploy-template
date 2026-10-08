"""GIVEN disposable nodes, WHEN the real driver/playbook runs, THEN upgrades are safe.

Ubuntu's package manager, release upgrader and reboot are OS/provider boundaries.
Their local stand-ins operate on real node files; our driver and Ansible tasks
run unchanged. No production node, Keychain or cloud account is contacted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "roles/os-upgrade/files/upgrade.py"


@pytest.fixture
def node(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    release_file = tmp_path / "os-release"
    release_file.write_text(
        'ID=ubuntu\nVERSION="24.04.5 LTS (Noble Numbat)"\nVERSION_ID="24.04"\n'
    )
    config = tmp_path / "release-upgrades"
    config.write_text("[DEFAULT]\nPrompt=lts\n")
    commands = tmp_path / "commands.jsonl"
    program = """#!/usr/bin/env python3
import json, os, pathlib, sys, time
root = pathlib.Path(os.environ['NODE_ROOT'])
name = pathlib.Path(sys.argv[0]).name
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'dpkg':
    print(os.environ.get('NODE_DPKG_AUDIT', ''), end='')
elif name == 'do-release-upgrade':
    if '-c' in sys.argv:
        offered = os.environ.get('NODE_OFFERED', '26.04.1 LTS')
        print("New release '%s' available." % offered if offered else 'No new release found.')
        sys.exit(0 if offered else 1)
    (root / 'started').touch()
    time.sleep(float(os.environ.get('NODE_DELAY', '0')))
    if os.environ.get('NODE_FAIL'):
        sys.exit(1)
    target = os.environ.get('NODE_TARGET', '26.04')
    (root / 'os-release').write_text('ID=ubuntu\\nVERSION="%s.1 LTS"\\nVERSION_ID="%s"\\n' % (target, target))
elif name == 'k3s':
    if 'get' in sys.argv:
        print(json.dumps({'items': [{'metadata': {'name': 'node-a'}, 'spec': {}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]}))
    elif os.environ.get('NODE_K3S_FAIL'):
        sys.exit(1)
elif name == 'systemctl':
    print('active')
"""
    for command in ["dpkg", "do-release-upgrade", "k3s", "systemctl"]:
        path = binary / command
        path.write_text(program)
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "NODE_ROOT": str(tmp_path),
    }
    args = [
        str(DRIVER),
        "--target",
        "26.04",
        "--release-file",
        str(release_file),
        "--config-file",
        str(config),
        "--state-dir",
        str(tmp_path / "state"),
        "--supported-path",
        "24.04:26.04",
    ]
    return tmp_path, env, args


def drive(node, action, **environment):
    root, env, args = node
    return subprocess.run(
        [sys.executable, args[0], action, *args[1:]],
        env={**env, **environment},
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_preview_only_reads_release_and_availability(node):
    # GIVEN an eligible LTS node, WHEN preview runs, THEN no persistent upgrade
    # state or OS changes are made and the Ubuntu offer matches the target.
    root, _, _ = node
    before = (root / "os-release").read_bytes()
    preview = drive(node, "probe")
    assert preview.returncode == 0, preview.stderr
    plan = json.loads(preview.stdout)
    assert plan["allowed"] and plan["available"] and plan["current"] == "24.04"
    assert (root / "os-release").read_bytes() == before
    assert not (root / "state").exists()
    assert json.loads((root / "commands.jsonl").read_text().splitlines()[-1]) == [
        "do-release-upgrade",
        "-c",
    ]


@pytest.mark.parametrize(
    "environment,expected",
    [
        ({"NODE_OFFERED": ""}, "offered"),
        ({"NODE_OFFERED": "28.04.1 LTS"}, "offered"),
        ({"NODE_DPKG_AUDIT": "unfinished package"}, "unfinished"),
    ],
)
def test_unavailable_targets_and_broken_packages_never_start(
    node, environment, expected
):
    # GIVEN an unavailable target or unfinished packages, WHEN execution is
    # requested, THEN the real driver refuses without starting an upgrader.
    root, _, _ = node
    result = drive(node, "upgrade", **environment)
    assert result.returncode != 0
    assert expected in result.stderr
    assert not (root / "started").exists()
    assert not (root / "state").exists()


def test_execute_and_rerun_do_not_upgrade_twice(node):
    # GIVEN an eligible node, WHEN execution and a rerun finish, THEN the target
    # release and durable result agree and only one release upgrade was launched.
    root, _, _ = node
    result = drive(node, "upgrade")
    assert result.returncode == 0, result.stderr
    state = json.loads((root / "state/result.json").read_text())
    assert state["status"] == "completed" and state["target"] == "26.04"
    assert drive(node, "upgrade").returncode == 0
    commands = [
        json.loads(line) for line in (root / "commands.jsonl").read_text().splitlines()
    ]
    assert (
        commands.count(["do-release-upgrade", "-f", "DistUpgradeViewNonInteractive"])
        == 1
    )


def test_failed_upgrade_is_persisted_and_never_silently_retried(node):
    # GIVEN the Ubuntu upgrader fails, WHEN the owner reruns the command, THEN
    # the failure remains visible and recovery is required rather than a retry.
    root, _, _ = node
    assert drive(node, "upgrade", NODE_FAIL="1").returncode != 0
    assert json.loads((root / "state/result.json").read_text())["status"] == "failed"
    retry = drive(node, "upgrade")
    assert retry.returncode != 0 and "Previous upgrade failed" in retry.stderr


def test_disconnected_controller_cannot_launch_a_second_upgrade(node):
    # GIVEN an upgrade continues independently, WHEN another controller probes
    # or executes, THEN the lock reports progress and rejects a duplicate.
    import time

    root, env, args = node
    child = subprocess.Popen(
        [sys.executable, args[0], "upgrade", *args[1:]],
        env={**env, "NODE_DELAY": "2"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not (root / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (root / "started").exists()
        preview = drive(node, "probe")
        assert json.loads(preview.stdout)["running"]
        duplicate = drive(node, "upgrade")
        assert duplicate.returncode != 0 and "already running" in duplicate.stderr
        _, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        assert json.loads(drive(node, "probe").stdout)["already_upgraded"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_future_lts_uses_same_driver_but_needs_reviewed_policy(node):
    # GIVEN a future consecutive LTS offer, WHEN the reviewed path is extended,
    # THEN the same driver works; before review execution is blocked.
    root, env, args = node
    (root / "os-release").write_text(
        'ID=ubuntu\nVERSION="26.04.1 LTS"\nVERSION_ID="26.04"\n'
    )
    args[args.index("--target") + 1] = "28.04"
    env.update(NODE_OFFERED="28.04.1 LTS", NODE_TARGET="28.04")
    blocked = drive(node, "upgrade")
    assert blocked.returncode != 0 and "reviewed" in blocked.stderr
    args.extend(["--supported-path", "26.04:28.04"])
    upgraded = drive(node, "upgrade")
    assert upgraded.returncode == 0, upgraded.stderr
    assert json.loads(drive(node, "probe").stdout)["already_upgraded"]


def test_non_lts_and_non_lts_channel_are_rejected(node):
    # GIVEN an interim node or the normal upgrade channel, WHEN preview runs,
    # THEN it fails before checking for or starting an upgrade.
    root, _, _ = node
    (root / "release-upgrades").write_text("[DEFAULT]\nPrompt=normal\n")
    assert "Prompt=lts" in drive(node, "probe").stderr
    (root / "os-release").write_text('ID=debian\nVERSION="13"\nVERSION_ID="13"\n')
    assert "Only Ubuntu LTS" in drive(node, "probe").stderr


def playbook(node, **variables):
    root, env, _ = node
    inventory = root / "inventory.yml"
    inventory.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "children": {
                        "production": {
                            "hosts": {
                                "node-a": {
                                    "ansible_connection": "local",
                                    "ansible_become": False,
                                    "ansible_python_interpreter": sys.executable,
                                }
                            }
                        },
                        "hcloud_type_master": {"hosts": {"node-a": {}}},
                    }
                }
            }
        )
    )
    config = root / "ansible.cfg"
    config.write_text("[defaults]\n")
    extra = root / "vars.json"
    extra.write_text(
        json.dumps(
            {
                "os_upgrade_target": "26.04",
                "os_upgrade_environment": "production",
                "os_upgrade_release_file": str(root / "os-release"),
                "os_upgrade_config_file": str(root / "release-upgrades"),
                "os_upgrade_state_dir": str(root / "state"),
                "os_upgrade_python": sys.executable,
                **variables,
            }
        )
    )
    return subprocess.run(
        [
            str(Path(sys.executable).parent / "ansible-playbook"),
            str(ROOT / "os-upgrade-playbook.yml"),
            "-i",
            str(inventory),
            "-l",
            "production",
            "-e",
            f"@{extra}",
        ],
        env={**env, "ANSIBLE_CONFIG": str(config)},
        cwd=root,
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_real_ansible_preview_leaves_node_unchanged(node):
    # GIVEN a disposable VM boundary, WHEN the actual playbook previews, THEN
    # a user sees the plan and no upgrade or reboot occurs.
    root, _, _ = node
    result = playbook(node)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ubuntu 24.04 -> 26.04" in result.stdout and "mode=preview" in result.stdout
    assert not (root / "state").exists() and not (root / "started").exists()


def test_real_ansible_blocks_unreviewed_target_before_mutation(node):
    # GIVEN an Ubuntu offer with no reviewed path, WHEN execution is requested,
    # THEN the entire preflight stops before package preparation or upgrades.
    root, env, _ = node
    env["NODE_OFFERED"] = "28.04.1 LTS"
    result = playbook(
        node,
        os_upgrade_target="28.04",
        os_upgrade_execute=True,
        os_upgrade_backup_confirmed=True,
        os_upgrade_health_urls=["https://example.com"],
    )
    assert result.returncode != 0 and "reviewed consecutive LTS" in result.stdout
    assert not (root / "started").exists()


def test_export_action_includes_os_upgrade_playbook(tmp_path):
    # GIVEN the real composite export action, WHEN its shell step executes,
    # THEN a CI export includes the playbook and the unchanged real driver.
    action_path = ROOT / ".github/actions/export-shared-roles/action.yml"
    action = yaml.safe_load(action_path.read_text())
    result = subprocess.run(
        ["bash", "-c", action["runs"]["steps"][0]["run"]],
        env={
            **os.environ,
            "ACTION_REPO_ROOT": str(action_path.parent),
            "GITHUB_WORKSPACE": str(tmp_path),
            "DESTINATION_DIR": ".shared-roles",
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    exported = tmp_path / ".shared-roles"
    assert (exported / "os-upgrade-playbook.yml").read_bytes() == (
        ROOT / "os-upgrade-playbook.yml"
    ).read_bytes()
    assert (
        exported / "roles/os-upgrade/files/upgrade.py"
    ).read_bytes() == DRIVER.read_bytes()
