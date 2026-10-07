"""Restore the actual playbook shell scripts into a disposable PostgreSQL database."""

import gzip
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest
import yaml


def test_restore_preserves_data_and_owner_without_password_arguments(tmp_path):
    # GIVEN a real isolated database and a dump, with Kubernetes as the external boundary.
    if not shutil.which("docker"):
        pytest.skip("Docker is required for the disposable PostgreSQL integration test")
    if subprocess.run(["docker", "info"], capture_output=True).returncode:
        pytest.skip("Docker daemon is unavailable")
    container = "startup-restore-check-" + uuid.uuid4().hex[:12]
    docker = lambda *args, **kwargs: subprocess.run(
        ["docker", *args], capture_output=True, check=True, timeout=120, **kwargs
    )
    try:
        docker("run", "--detach", "--network", "none", "--name", container,
               "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_USER=admin",
               "-e", "POSTGRES_DB=restore_check", os.environ.get("RESTORE_POSTGRES_IMAGE", "postgres:18.6"))
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-U", "admin"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("Disposable Postgres did not become ready")
        docker("exec", container, "psql", "-v", "ON_ERROR_STOP=1", "-U", "admin", "-d", "restore_check",
               "-c", "CREATE ROLE restore_user LOGIN; ALTER SCHEMA public OWNER TO restore_user; SET ROLE restore_user; CREATE TABLE evidence (value integer); INSERT INTO evidence VALUES (1),(2),(3);")
        dump = docker("exec", container, "pg_dump", "-U", "admin", "-d", "restore_check", "--no-owner", "--no-acl").stdout
        backup = tmp_path / "restore.sql.gz"
        backup.write_bytes(gzip.compress(dump))
        trace = tmp_path / "kubectl-arguments.jsonl"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        adapter = bin_dir / "kubectl"
        adapter.write_text("""#!/usr/bin/env python3
import base64,json,os,subprocess,sys
args=sys.argv[1:]
with open(os.environ['RESTORE_TEST_TRACE'],'a') as file:file.write(json.dumps(args)+'\\n')
if args[0]=='get':
 values={'backend_db_name':'restore_check','backend_db_user':'restore_user','backend_db_password':'synthetic-password'}
 field=next(key for key in values if key in ' '.join(args))
 print(base64.b64encode(values[field].encode()).decode(),end='')
elif args[0]=='exec':
 command=args[args.index('--')+1:]
 result=subprocess.run(['docker','exec',*(['-i'] if '-i' in args else []),os.environ['RESTORE_TEST_CONTAINER'],*command])
 raise SystemExit(result.returncode)
else:raise SystemExit('Unexpected Kubernetes request')
""")
        adapter.chmod(0o755)
        environment = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                       "RESTORE_TEST_CONTAINER": container, "RESTORE_TEST_TRACE": str(trace)}
        playbook = yaml.safe_load((Path(__file__).resolve().parents[1] / "restore-playbook.yml").read_text())
        block = next(task["block"] for task in playbook[0]["tasks"] if task.get("name") == "Restore application backup")
        names = ["Reset database schema before restore", "Restore database dump into postgres deployment", "Verify restored schema ownership"]
        # WHEN the actual restore scripts reset and restore the disposable database.
        for name in names:
            script = next(task["shell"] for task in block if task.get("name") == name)
            script = script.replace("{{ k8s_namespace | default('default') }}", "default")
            script = script.replace("{{ remote_db_backup_file }}", str(backup))
            result = subprocess.run(["/bin/bash", "-c", script], env=environment, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
        # THEN actual rows and role ownership survive; no database password reaches argv.
        count = docker("exec", container, "psql", "-U", "admin", "-d", "restore_check", "-tAc", "SELECT count(*) FROM evidence;").stdout.strip()
        owner = docker("exec", container, "psql", "-U", "admin", "-d", "restore_check", "-tAc", "SELECT tableowner FROM pg_tables WHERE tablename='evidence';").stdout.strip()
        assert count == b"3"
        assert owner == b"restore_user"
        assert "synthetic-password" not in trace.read_text()
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True)
