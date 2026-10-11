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
import urllib.parse
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
        yield {"address": address, "name": name, "docker": docker}
    finally:
        for container in reversed(created):
            docker('rm', '-f', '-v', container, check=False)


def execute_api_tasks(values):
    executed = []
    tasks = yaml.safe_load((ROOT / 'roles/kpis/tasks/main.yml').read_text())
    for task in (task for task in tasks if 'ansible.builtin.uri' in task):
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
        try:
            payload = json.loads(body or '{}')
        except ValueError:
            payload = None
        result = {'status': status, 'json': payload}
        if 'register' in task:
            values[task['register']] = result
        if 'failed_when' in task:
            assert not Templar(loader=DataLoader(), variables=values).evaluate_expression(
                trust_as_template(task['failed_when'])), task['name']
        executed.append(task['name'])
    return executed


def test_real_kpis_bootstrap_creates_the_website_and_can_be_repeated(umami):
    # GIVEN the actual URI task bodies and Ansible conditions, a fresh real Umami,
    # and only disposable credentials. Kubernetes Service discovery is the boundary.
    values = {**trusted(yaml.safe_load((ROOT / 'roles/kpis/defaults/main.yml').read_text())), 'kpis_service': {'resources': [{'spec': {'clusterIP': umami['address']}}]},
              'kpis_admin_password': secrets.token_urlsafe(24), 'kpis_website_id': str(uuid.uuid4()),
              'project_name': 'integration-startup', 'base_domain': 'example.test'}
    tasks = yaml.safe_load((ROOT / 'roles/kpis/tasks/main.yml').read_text())
    uri_tasks = [task for task in tasks if 'ansible.builtin.uri' in task]
    creation = next(task for task in uri_tasks if task['name'] == 'Create the configured website if missing')
    for attempt in range(2):
        executed = []
        # WHEN the shipped API requests run on both initial deployment and retry.
        executed = execute_api_tasks(values)
        # THEN the fixed public ID exists, the default login fails, and retry never
        # recreates the website or resets the configured admin password.
        assert values['kpis_verified_website']['json']['id'] == values['kpis_website_id']
        assert 'Verify the default admin password is rejected privately' in executed
        assert (creation['name'] in executed) == (attempt == 0)
        if attempt == 0:
            assert values['kpis_website'] == {'status': 200, 'json': None}
        else:
            assert 'Replace the default admin password before publishing the UI' not in executed


def free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture
def reader_edge(umami, tmp_path):
    # GIVEN the existing pinned OAuth2 Proxy, a local OIDC provider boundary,
    # real Umami, and the same Traefik version deployed by the factory.
    docker = umami['docker']
    name = 'kpis-reader-' + uuid.uuid4().hex[:8]
    oidc, proxy, edge = (name + suffix for suffix in ('-oidc', '-proxy', '-edge'))
    oidc_port, proxy_port, kpis_port, app_port = (free_port() for _ in range(4))
    origin = f'https://localhost:{kpis_port}'
    app_origin = f'https://localhost:{app_port}'
    config = {'interactiveLogin': True, 'tokenCallbacks': [{'issuerId': 'default',
              'requestMappings': [{'requestParam': 'grant_type', 'match': 'authorization_code',
                                   'claims': {'email': 'reader@example.test', 'aud': ['startup-web']}}]}]}
    (tmp_path / 'oidc.json').write_text(json.dumps(config))
    created = []
    values = {**trusted(yaml.safe_load((ROOT / 'roles/kpis/defaults/main.yml').read_text())),
              'kpis_service': {'resources': [{'spec': {'clusterIP': umami['address']}}]},
              'kpis_access_mode': 'oauth2_proxy', 'oauth2_proxy_enabled': True,
              'kpis_admin_password': secrets.token_urlsafe(24), 'kpis_website_id': str(uuid.uuid4()),
              'project_name': 'reader-startup', 'base_domain': 'example.test',
              'kpis_host': f'localhost:{kpis_port}', 'k8s_namespace': 'sample',
              'kpis_proxy_service': {'resources': [{'spec': {'clusterIP': '127.0.0.1'}}]},
              'kpis_oauth2_proxy_service': 'oauth2-proxy', 'kpis_oauth2_proxy_port': proxy_port}
    try:
        docker('run', '-d', '--name', oidc, '--network', 'bridge',
               '-p', f'127.0.0.1:{oidc_port}:8080', '-e', 'JSON_CONFIG_PATH=/config.json',
               '-v', f'{tmp_path}/oidc.json:/config.json:ro', 'ghcr.io/navikt/mock-oauth2-server:2.1.10')
        created.append(oidc)
        docker('run', '-d', '--name', proxy, '--network', 'bridge', '--link', oidc + ':oidc',
               '--link', umami['name'] + ':umami', '-p', f'127.0.0.1:{proxy_port}:4180',
               'quay.io/oauth2-proxy/oauth2-proxy:v7.13.0',
               '--http-address=0.0.0.0:4180', '--provider=oidc', '--skip-oidc-discovery=true',
               '--oidc-issuer-url=http://oidc:8080/default', '--redeem-url=http://oidc:8080/default/token',
               '--oidc-jwks-url=http://oidc:8080/default/jwks',
               f'--login-url=http://localhost:{oidc_port}/default/authorize',
               '--client-id=startup-web', '--client-secret=disposable-local-test',
               '--cookie-secret=YWJvdXQtcGhpbC1sb2NhbC1kZXYtY29va2llLWtleSE=',
               '--cookie-secure=true', '--email-domain=*', '--reverse-proxy=true',
               f'--redirect-url={app_origin}/oauth2/callback', '--whitelist-domain=localhost:*',
               '--upstream=http://umami:3000', '--skip-jwt-bearer-tokens=true',
               '--extra-jwt-issuers=http://oidc:8080/default=startup-api',
               '--pass-authorization-header=true', '--skip-auth-route=!=^/private_api',
               '--skip-auth-route=OPTIONS=^/private_api')
        created.append(proxy)
        for _ in range(60):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{proxy_port}/ping', timeout=1):
                    break
            except OSError:
                time.sleep(1)
        else:
            pytest.fail('The real OAuth2 Proxy did not become ready')
        execute_api_tasks(values)
        rendered_values = {**values, 'kpis_oauth2_proxy_service': 'oauth2-proxy', 'kpis_oauth2_proxy_port': 4180}
        templar = Templar(loader=DataLoader(), variables=rendered_values)
        render = lambda file: yaml.safe_load(templar.template(trust_as_template(
            (ROOT / 'roles/kpis/templates' / file).read_text())))
        middlewares = {}
        for item in render('oauth-middlewares.yml')['items']:
            spec = item['spec']
            if 'chain' in spec:
                spec['chain']['middlewares'] = [entry['name'] for entry in spec['chain']['middlewares']]
            if 'errors' in spec:
                spec['errors']['service'] = 'oauth2-proxy'
            middlewares[item['metadata']['name']] = spec
        assert middlewares['kpis-auth']['forwardAuth']['address'] == (
            'http://oauth2-proxy.sample.svc.cluster.local:4180/oauth2/auth')
        routers = {'reader': {'rule': 'PathPrefix(`/`)', 'entryPoints': ['kpis'],
                              'service': 'kpis', 'middlewares': ['kpis-reader'], 'tls': {}},
                   'existing-app': {'rule': 'PathPrefix(`/`)', 'entryPoints': ['app'],
                                    'service': 'oauth2-proxy', 'tls': {}}}
        public = render('public-ingress.yml')['spec']['rules'][0]['http']['paths']
        for index, route in enumerate(public):
            routers[f'public-{index}'] = {'rule': ('Path' if route['pathType'] == 'Exact' else 'PathPrefix')
                                        + f"(`{route['path']}`)", 'entryPoints': ['kpis'],
                                        'service': route['backend']['service']['name'], 'tls': {}}
        configuration = {'http': {'routers': routers, 'middlewares': middlewares,
                                  'services': {service: {'loadBalancer': {'servers': [{'url': url}]}}
                                               for service, url in [('kpis', 'http://umami:3000'),
                                                                    ('oauth2-proxy', 'http://oauth2-proxy:4180')]}},
                         'tls': {'certificates': [{'certFile': '/config/cert.pem', 'keyFile': '/config/key.pem'}]}}
        (tmp_path / 'dynamic.yml').write_text(yaml.safe_dump(configuration))
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(tmp_path / 'key.pem'), '-out', str(tmp_path / 'cert.pem'),
                        '-days', '1', '-subj', '/CN=localhost'], check=True, capture_output=True)
        docker('run', '-d', '--name', edge, '--network', 'bridge',
               '--link', proxy + ':oauth2-proxy',
               '--link', proxy + ':oauth2-proxy.sample.svc.cluster.local',
               '--link', umami['name'] + ':umami',
               '-p', f'127.0.0.1:{kpis_port}:8443', '-p', f'127.0.0.1:{app_port}:8444',
               '-v', f'{tmp_path}:/config:ro', 'rancher/mirrored-library-traefik:3.7.13',
               '--entrypoints.kpis.address=:8443', '--entrypoints.app.address=:8444',
               '--providers.file.filename=/config/dynamic.yml')
        created.append(edge)
        import ssl
        context = ssl._create_unverified_context()
        for _ in range(60):
            try:
                with urllib.request.urlopen(origin + '/api/heartbeat', context=context, timeout=1):
                    break
            except OSError:
                time.sleep(1)
        else:
            pytest.fail('The rendered Traefik reader edge did not become ready')
        yield {'origin': origin, 'app_origin': app_origin, 'values': values,
               'configuration': configuration, 'config_path': tmp_path / 'dynamic.yml'}
    finally:
        for container in reversed(created):
            docker('rm', '-f', '-v', container, check=False)


def test_oauth_reader_reuses_session_blocks_bypasses_and_keeps_tracking_public(reader_edge):
    from playwright.sync_api import sync_playwright, expect
    values, origin = reader_edge['values'], reader_edge['origin']
    # GIVEN the role has created and verified its private reader share twice.
    execute_api_tasks(values)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        # WHEN an anonymous browser tries both the UI and all sensitive API routes,
        # including a forged forwarded URI matching the proxy's public allowlist.
        for path in ('/', '/share/' + values['kpis_website_id'],
                     '/api/share/' + values['kpis_website_id'], '/api/websites/' + values['kpis_website_id']):
            for headers in ({}, {'X-Forwarded-Uri': '/public', 'X-Forwarded-Method': 'OPTIONS'}):
                response = context.request.get(origin + path, headers=headers)
                assert response.status in (401, 403)
                assert 'Sign in' in response.text()
                assert '"token"' not in response.text()
        # THEN the collector remains public, but neighboring API paths do not.
        assert context.request.get(origin + '/script.js').status == 200
        assert context.request.get(origin + '/api/heartbeat').status == 200
        assert context.request.get(origin + '/api/send/other').status in (401, 403)
        assert context.request.post(origin + '/api/send', data={
            'type': 'event', 'payload': {'website': values['kpis_website_id'], 'hostname': 'example.test',
                                      'screen': '1440x900', 'language': 'en-US', 'url': '/reader-test',
                                      'title': 'Reader test'}}).status == 200
        # WHEN the user signs into the EXISTING application's proxy first.
        page.goto(reader_edge['app_origin'] + '/oauth2/start?rd=' + urllib.parse.quote(
            reader_edge['app_origin'] + '/private_api', safe=''))
        page.locator('input[name="username"]').fill('reader')
        page.locator('button[type="submit"], input[type="submit"]').click()
        page.wait_for_url(reader_edge['app_origin'] + '/private_api')
        assert any(cookie['name'].startswith('_oauth2_proxy') for cookie in context.cookies())
        # THEN opening KPIs on a different origin reuses the existing cookie and
        # renders the read-only overview without a second password or login screen.
        page.goto(origin + '/')
        page.wait_for_url(origin + '/share/' + values['kpis_website_id'])
        expect(page.get_by_text('reader-startup', exact=True).first).to_be_visible()
        expect(page.get_by_text('Visitors', exact=True).first).to_be_visible()
        assert page.locator('input[name="password"]').count() == 0
        # Umami's own bearer token must stay at Umami; forwarding it to the
        # OIDC proxy would reject legitimate administration as an invalid JWT.
        admin_headers = {'Authorization': 'Bearer ' + values['kpis_login']['json']['token']}
        assert context.request.get(origin + '/api/websites', headers=admin_headers).status == 200
        share = context.request.get(origin + '/api/share/' + values['kpis_website_id']).json()
        assert share['websiteId'] == values['kpis_website_id']
        assert context.request.post(origin + '/api/websites/' + values['kpis_website_id'],
            headers={'x-umami-share-token': share['token'], 'x-umami-share-context': 'website'},
            data={'name': 'unauthorized-write', 'domain': 'example.test'}).status == 401
        # WHEN the user starts directly at the KPI host without an app session,
        # THEN the existing callback returns them to the reader after one login.
        fresh_context = browser.new_context(ignore_https_errors=True)
        fresh_page = fresh_context.new_page()
        fresh_page.goto(origin + '/')
        fresh_page.get_by_role('button', name='Sign in with OpenID Connect').click()
        fresh_page.locator('input[name="username"]').fill('reader')
        fresh_page.locator('button[type="submit"], input[type="submit"]').click()
        fresh_page.wait_for_url(origin + '/share/' + values['kpis_website_id'])
        expect(fresh_page.get_by_text('Visitors', exact=True).first).to_be_visible()
        fresh_context.close()
        # Preserve a separately managed public share when changing access mode.
        custom_share = context.request.post(origin + '/api/websites/' + values['kpis_website_id'] + '/shares',
            headers={'Authorization': 'Bearer ' + values['kpis_login']['json']['token']},
            data={'name': 'Custom share', 'parameters': {'overview': True}}).json()
        # WHEN returning to password mode, only the managed reader share is
        # revoked before the normal ingress is restored; no OAuth is required.
        values['kpis_access_mode'] = 'password'
        execute_api_tasks(values)
        assert context.request.get(origin + '/api/share/' + values['kpis_website_id']).status == 404
        configuration = reader_edge['configuration']
        configuration['http']['routers']['reader']['middlewares'] = []
        reader_edge['config_path'].write_text(yaml.safe_dump(configuration))
        context.clear_cookies()
        page.goto(origin + '/login')
        # Traefik coalesces file-provider updates before applying them.
        for _ in range(40):
            if page.locator('input[name="password"]').count():
                break
            time.sleep(0.25)
            page.reload()
        expect(page.locator('input[name="password"]')).to_be_visible()
        assert context.request.get(origin + '/api/share/' + custom_share['slug']).status == 200
        page.locator('input[name="username"]').fill('admin')
        page.locator('input[name="password"]').fill(values['kpis_admin_password'])
        page.locator('button[type="submit"], input[type="submit"]').click()
        page.wait_for_url(lambda url: '/login' not in url)
        browser.close()
