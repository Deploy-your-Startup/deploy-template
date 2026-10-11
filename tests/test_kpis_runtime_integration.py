"""The shipped init script and API task contract against real Umami and Postgres."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {key: trusted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [trusted(item) for item in value]
    return value


@pytest.fixture
def umami():
    if not shutil.which('docker'):
        if os.environ.get('STARTUP_REQUIRE_DOCKER_TESTS') == '1':
            pytest.fail('Docker is required for the real KPI bootstrap test')
        pytest.skip('Docker not installed')
    name = 'kpis-integration-' + uuid.uuid4().hex[:10]
    db = name + '-db'
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_urlsafe(24), PGUSER='postgres',
               PGHOST=db, PGPORT='5432', PGDATABASE='postgres', KPIS_DB_NAME='kpis_db',
               KPIS_DB_USER='kpis_db_user', KPIS_DB_PASSWORD=secrets.token_urlsafe(24),
               APP_SECRET=secrets.token_urlsafe(32), DISABLE_TELEMETRY='1')
    env['PGPASSWORD'] = env['POSTGRES_PASSWORD']
    created = []

    def docker(*args, check=True, stdin=None):
        return subprocess.run(['docker', *args], input=stdin, capture_output=True,
                              text=True, env=env, check=check, timeout=120)

    try:
        # GIVEN the pinned database image and the role's actual SQL initializer.
        docker('run', '-d', '--name', db, '--network', 'bridge', '-e', 'POSTGRES_PASSWORD', 'postgres:18.6')
        created.append(db)
        for _ in range(60):
            if docker('exec', db, 'pg_isready', '-U', 'postgres', check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail('Postgres did not become ready')
        values = {'postgres_version': '18.6', 'postgres_host': db, 'postgres_port': 5432,
                  'kpis_db_name': 'kpis_db', 'kpis_db_user': 'kpis_db_user', 'kpis_version': '3.4.0',
                  'ansible_date_time': {'iso8601_basic': '20261011T000000'}}
        templar = Templar(loader=DataLoader(), variables=values)
        manifest = yaml.safe_load(templar.template(trust_as_template(
            (ROOT / 'roles/kpis/templates/deployment.yml').read_text())))
        init = manifest['spec']['template']['spec']['initContainers'][0]['command'][-1]
        args = ['run', '--rm', '-i', '--network', 'bridge', '--link', db + ':' + db]
        for key in ('PGUSER', 'PGPASSWORD', 'PGHOST', 'PGPORT', 'PGDATABASE',
                    'KPIS_DB_NAME', 'KPIS_DB_USER', 'KPIS_DB_PASSWORD'):
            args.extend(['-e', key])
        docker(*args, 'postgres:18.6', 'sh', '-e', stdin=init)
        env['DATABASE_URL'] = f"postgresql://kpis_db_user:{env['KPIS_DB_PASSWORD']}@{db}:5432/kpis_db"
        image = manifest['spec']['template']['spec']['containers'][0]['image']
        # Use loopback and a random host port; do not touch other jobs' networks.
        docker('run', '-d', '--name', name, '--network', 'bridge', '--link', db + ':' + db,
               '--memory', '512m', '-p', '127.0.0.1::3000', '-e', 'DATABASE_URL',
               '-e', 'APP_SECRET', '-e', 'DISABLE_TELEMETRY', image)
        created.append(name)
        port = docker('port', name, '3000/tcp').stdout.strip().split(':')[-1]
        address = '127.0.0.1:' + port
        for _ in range(120):
            try:
                with urllib.request.urlopen('http://' + address + '/api/heartbeat', timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        else:
            pytest.fail('The pinned Umami image did not become ready with the role memory limit')
        yield address
    finally:
        for container in reversed(created):
            docker('rm', '-f', '-v', container, check=False)


def test_real_kpis_bootstrap_creates_the_website_and_can_be_repeated(umami):
    # GIVEN the actual URI task bodies and Ansible conditions, a fresh real Umami,
    # and only disposable credentials. Kubernetes Service discovery is the boundary.
    values = {'kpis_service': {'resources': [{'spec': {'clusterIP': umami}}]},
              'kpis_admin_password': secrets.token_urlsafe(24), 'kpis_website_id': str(uuid.uuid4()),
              'project_name': 'integration-startup', 'base_domain': 'example.test'}
    tasks = yaml.safe_load((ROOT / 'roles/kpis/tasks/main.yml').read_text())
    uri_tasks = [task for task in tasks if 'ansible.builtin.uri' in task]
    creation = next(task for task in uri_tasks if task['name'] == 'Create the configured website if missing')
    for attempt in range(2):
        executed = []
        # WHEN the shipped API requests run on both initial deployment and retry.
        for task in uri_tasks:
            templar = Templar(loader=DataLoader(), variables=values)
            if 'when' in task and not templar.evaluate_expression(trust_as_template(task['when'])):
                continue
            uri = templar.template(trusted(task['ansible.builtin.uri']))
            data = json.dumps(uri['body']).encode() if 'body' in uri else None
            request = urllib.request.Request(uri['url'], data=data, method=uri.get('method', 'GET'),
                                             headers={'Content-Type': 'application/json', **uri.get('headers', {})})
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    status, body = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, body = error.code, error.read()
            expected = uri['status_code']
            assert status in (expected if isinstance(expected, list) else [expected]), task['name']
            result = {'status': status, 'json': json.loads(body or '{}')}
            if 'register' in task:
                values[task['register']] = result
            if 'failed_when' in task:
                assert not Templar(loader=DataLoader(), variables=values).evaluate_expression(
                    trust_as_template(task['failed_when'])), task['name']
            executed.append(task['name'])
        # THEN the fixed public ID exists, the default login fails, and retry never
        # recreates the website or resets the configured admin password.
        assert values['kpis_verified_website']['json']['id'] == values['kpis_website_id']
        assert 'Verify the default admin password is rejected privately' in executed
        assert (creation['name'] in executed) == (attempt == 0)
        if attempt == 0:
            assert values['kpis_website'] == {'status': 200, 'json': None}
        else:
            assert 'Replace the default admin password before publishing the UI' not in executed
