#!/usr/bin/env python3
"""Remote Ubuntu upgrade driver. Preview never creates state or changes packages.

The lock and durable result survive controller disconnections. A rerun waits
for the original process instead of starting a second distribution upgrade.
Paths are supplied by the role so the real driver can also run in disposable
node fixtures without modifying the controller's operating system.
"""

import argparse
import configparser
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def release(path):
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = shlex.split(value)[0] if value else ""
    if values.get("ID") != "ubuntu" or "LTS" not in values.get("VERSION", ""):
        raise ValueError("Only Ubuntu LTS nodes are supported")
    return values["VERSION_ID"]


def running(state_dir):
    lock_path = state_dir / "lock"
    if not lock_path.exists():
        return False
    with lock_path.open("r") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def result(state_dir):
    path = state_dir / "result.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save(state_dir, value):
    temporary = state_dir / "result.tmp"
    temporary.write_text(json.dumps(value) + "\n")
    temporary.replace(state_dir / "result.json")


def probe(args):
    current = release(args.release_file)
    active = running(args.state_dir)
    previous = result(args.state_dir)
    if active:
        return {"current": current, "target": args.target, "running": True}
    if previous.get("status") == "running":
        raise ValueError(
            "Previous upgrade was interrupted on the node; inspect /var/log/dist-upgrade and the upgrade state before recovery"
        )
    if previous.get("status") == "failed":
        raise ValueError(
            "Previous upgrade failed; inspect /var/log/dist-upgrade and the upgrade state before recovery"
        )
    # A changed OS version alone is not proof that an interrupted upgrade finished.
    audit = subprocess.run(
        ["dpkg", "--audit"], capture_output=True, text=True, check=True
    )
    if audit.stdout.strip():
        raise ValueError(
            "dpkg reports unfinished package operations; repair them before upgrading"
        )
    config = configparser.ConfigParser()
    config.read(args.config_file)
    if config.get("DEFAULT", "Prompt", fallback="") != "lts":
        raise ValueError("/etc/update-manager/release-upgrades must have Prompt=lts")
    allowed = (
        current == args.target or f"{current}:{args.target}" in args.supported_path
    )
    if current == args.target:
        return {
            "current": current,
            "target": args.target,
            "running": False,
            "already_upgraded": True,
            "allowed": True,
            "available": False,
            "completed_upgrade": previous.get("status") == "completed"
            and previous.get("target") == args.target,
        }
    if not re.fullmatch(r"[0-9]{2}\.04", current) or int(current[:2]) % 2:
        raise ValueError("Source release must be an even-year Ubuntu LTS")
    sequential = args.target == f"{int(current[:2]) + 2:02d}.04"
    check = subprocess.run(
        ["do-release-upgrade", "-c"],
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    output = check.stdout + check.stderr
    if check.returncode not in (0, 1):
        raise ValueError(
            "Ubuntu release availability check failed; check network access and do-release-upgrade -c"
        )
    found = re.search(
        r"New release '([0-9]{2}\.[0-9]{2})(?:\.[0-9]+)?[^']*' available", output
    )
    offered = found.group(1) if found else None
    return {
        "current": current,
        "target": args.target,
        "running": False,
        "already_upgraded": False,
        "allowed": allowed and sequential,
        "available": offered == args.target,
        "offered": offered,
    }


def upgrade(args):
    plan = probe(args)
    if plan.get("running"):
        raise ValueError("An upgrade is already running; rerun the CLI to wait for it")
    if plan.get("already_upgraded"):
        return
    if not plan.get("allowed") or not plan.get("available"):
        raise ValueError("Target is not a reviewed path offered by Ubuntu")
    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (args.state_dir / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Probe before taking the lock; inside it repeat all destructive guards
        # except its own running detection.
        current = release(args.release_file)
        if current == args.target:
            return
        if (
            f"{current}:{args.target}" not in args.supported_path
            or args.target != f"{int(current[:2]) + 2:02d}.04"
        ):
            raise ValueError(
                "Upgrade path is not in the reviewed supported-path policy"
            )
        previous = result(args.state_dir)
        if previous.get("status") in ("running", "failed"):
            raise ValueError("Unfinished or failed upgrade requires operator recovery")
        save(
            args.state_dir,
            {"status": "running", "source": current, "target": args.target},
        )
        with (args.state_dir / "upgrade.log").open("a") as log:
            completed = subprocess.run(
                ["do-release-upgrade", "-f", "DistUpgradeViewNonInteractive"],
                stdout=log,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "DEBIAN_FRONTEND": "noninteractive",
                    "LC_ALL": "C",
                    "LANG": "C",
                },
            )
        success = (
            completed.returncode == 0 and release(args.release_file) == args.target
        )
        save(
            args.state_dir,
            {
                "status": "completed" if success else "failed",
                "source": current,
                "target": args.target,
                "exit_code": completed.returncode,
            },
        )
        if not success:
            raise ValueError(
                f"Release upgrade failed; inspect {args.state_dir / 'upgrade.log'} and /var/log/dist-upgrade"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "upgrade", "verified"])
    parser.add_argument("--target", required=True)
    parser.add_argument("--release-file", type=Path, default=Path("/etc/os-release"))
    parser.add_argument(
        "--config-file", type=Path, default=Path("/etc/update-manager/release-upgrades")
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/startup/os-upgrade")
    )
    parser.add_argument("--supported-path", action="append", default=[])
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{2}\.04", args.target) or int(args.target[:2]) % 2:
        parser.error("Target must be an even-year Ubuntu LTS version")
    if args.action == "probe":
        print(json.dumps(probe(args)))
    elif args.action == "upgrade":
        upgrade(args)
    elif args.state_dir.exists():
        with (args.state_dir / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = result(args.state_dir)
            if (
                previous.get("status") == "completed"
                and previous.get("target") == args.target
            ):
                if release(args.release_file) != args.target:
                    raise ValueError("Cannot verify a node on the wrong release")
                save(args.state_dir, {**previous, "status": "verified"})


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
