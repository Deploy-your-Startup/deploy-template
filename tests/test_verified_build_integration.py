"""Real Git histories and shipped CLI processes against a local GitHub API boundary."""
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import zipfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/actions/verified-build/verified_build.py'
REVISION = 'a' * 40


def git(directory, *args):
    return subprocess.check_output(['git', '-C', str(directory), *args], text=True, stderr=subprocess.PIPE).strip()


def zipped(name, data):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(name, data)
    return output.getvalue()


@pytest.fixture
def github(tmp_path):
    # GIVEN a real feature branch, GitHub-style test merge, and squash commit.
    source = tmp_path / 'source'
    source.mkdir()
    git(source, 'init', '-b', 'main')
    git(source, 'config', 'user.name', 'Integration Test')
    git(source, 'config', 'user.email', 'test@example.invalid')
    (source / 'app.txt').write_text('base\n')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'base')
    base = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', '-b', 'feature')
    (source / 'app.txt').write_text('tested feature\n')
    git(source, 'commit', '-am', 'feature')
    head = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', '-b', 'pr-merge', base)
    git(source, 'merge', '--no-ff', 'feature', '-m', 'test merge')
    merge = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', 'main')
    git(source, 'merge', '--squash', 'feature')
    git(source, 'commit', '-m', 'squash')
    squash = git(source, 'rev-parse', 'HEAD')
    workspace = tmp_path / 'workspace'
    git(tmp_path, 'clone', str(source), str(workspace))
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    routes = {}
    artifacts = {}
    archives = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = self.path.removeprefix('/repos/owner/app/')
            requests.append(path)
            if path.startswith('actions/artifacts?'):
                value = {'artifacts': list(artifacts.values())}
            elif path == 'actions/runs/100/artifacts?per_page=100':
                value = {'artifacts': list(artifacts.values())}
            elif path.startswith('actions/artifacts/'):
                artifact_id = int(path.split('/')[2])
                value = archives.get(artifact_id) if path.endswith('/zip') else artifacts.get(artifact_id)
            else:
                value = routes.get(path)
            if value is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(value if isinstance(value, bytes) else json.dumps(value).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    run = {
        'id': 100, 'event': 'pull_request', 'status': 'completed', 'conclusion': 'success',
        'workflow_id': 9, 'path': '.github/workflows/build.yml', 'run_attempt': 1,
        'repository': {'full_name': 'owner/app'}, 'head_repository': {'full_name': 'owner/app'},
        'created_at': datetime.now(timezone.utc).isoformat(), 'head_sha': head,
        'pull_requests': [{'base': {'sha': base}, 'head': {'sha': head}}],
        'referenced_workflows': [{'path': 'owner/shared/.github/workflows/build-and-deploy-service-parallel.yml@main', 'sha': REVISION}],
    }
    routes['actions/runs/100'] = run
    routes['actions/runs/200'] = {**run, 'id': 200, 'event': 'push', 'head_sha': squash}
    routes['git/commits/' + merge] = {'tree': {'sha': git(source, 'rev-parse', merge + '^{tree}')},
                                    'parents': [{'sha': base}, {'sha': head}]}
    routes[f'compare/{base}...{head}'] = {'merge_base_commit': {'sha': base}}
    configuration = {'service': 'app', 'reuse_pr_build': True, 'run_e2e': True, 'e2e_shards': 2}
    matrix = {'include': [{'service': 'backend', 'run_tests': True, 'run_lint': True,
                           'require_coverage': True, 'platforms': 'linux/amd64', 'additional_build_context': ''}]}
    env = {
        **os.environ, 'GITHUB_WORKSPACE': str(workspace), 'RUNNER_TEMP': str(runtime),
        'GITHUB_REPOSITORY': 'owner/app', 'GITHUB_RUN_ID': '200', 'GITHUB_RUN_ATTEMPT': '1',
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_API_URL': f'http://127.0.0.1:{server.server_port}',
        'GH_TOKEN': 'LOCAL_API_BOUNDARY', 'BUILD_CONFIGURATION': json.dumps(configuration),
        'BUILD_MATRIX': json.dumps(matrix), 'BUILD_REVISION': REVISION,
        'BUILD_SHARED_REPOSITORY': 'owner/shared', 'BUILD_SERVICE': 'backend',
    }

    def invoke(mode, **overrides):
        output = tmp_path / 'outputs'
        output.write_text('')
        result = subprocess.run([sys.executable, str(SCRIPT)],
                                env={**env, 'BUILD_MODE': mode, 'GITHUB_OUTPUT': str(output), **overrides},
                                text=True, capture_output=True, timeout=30)
        values = dict(line.split('=', 1) for line in output.read_text().splitlines())
        return result, values

    def upload(artifact_id, name, data):
        archives[artifact_id] = data
        artifacts[artifact_id] = {'id': artifact_id, 'name': name, 'expired': False,
                                  'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
                                  'workflow_run': {'id': 100}}

    image = b'the exact OCI archive built and checked in the PR'
    upload(901, 'backend-production-image-1', zipped('production-image.tar', image))

    def record():
        git(workspace, 'checkout', merge)
        result, values = invoke('record', GITHUB_RUN_ID='100', GITHUB_EVENT_NAME='pull_request')
        assert result.returncode == 0, result.stderr
        assert values['record'] == 'true', result.stdout
        upload(900, 'verified-pr-' + values['key'], zipped('proof.json', (runtime / 'verified-build/proof.json').read_bytes()))
        git(workspace, 'checkout', squash)
        return values['key']

    yield {'invoke': invoke, 'record': record, 'upload': upload, 'run': run, 'routes': routes,
           'artifacts': artifacts, 'archives': archives, 'workspace': workspace, 'source': source,
           'merge': merge, 'head': head, 'base': base, 'squash': squash, 'image': image,
           'runtime': runtime, 'configuration': configuration, 'matrix': matrix, 'requests': requests, 'env': env}
    server.shutdown()
    thread.join()


@pytest.mark.parametrize('merge_style', ['squash', 'merge'])
def test_matching_push_reuses_every_image_from_successful_pr(github, merge_style):
    # GIVEN a successful PR, whose tested merge tree survives a different commit SHA.
    key = github['record']()
    git(github['workspace'], 'checkout', github[merge_style])
    # WHEN the shipped selector and restore command run on the push.
    result, values = github['invoke']('prepare')
    assert result.returncode == 0, result.stderr
    assert values == {'reuse': 'true', 'record': 'false', 'key': key, 'proof_id': '900'}
    result, _ = github['invoke']('restore', BUILD_PROOF_ID='900')
    # THEN publication receives the exact immutable archive, not a rebuild.
    assert result.returncode == 0, result.stderr
    assert (github['runtime'] / 'production-image.tar').read_bytes() == github['image']


def test_direct_push_without_any_pr_runs_full_checks(github):
    # GIVEN a repository with no successful PR evidence (direct-to-main is allowed).
    # WHEN the actual prepare command runs on push.
    result, values = github['invoke']('prepare')
    # THEN no checks can be skipped and no branch-protection setting is required.
    assert result.returncode == 0
    assert values['reuse'] == 'false'
    assert 'proof_id' not in values


def test_a_parallel_main_change_cannot_reuse_the_old_pr_result(github):
    # GIVEN an approved PR and a direct main change made after its check.
    github['record']()
    workspace = github['workspace']
    git(workspace, 'config', 'user.name', 'Integration Test')
    git(workspace, 'config', 'user.email', 'test@example.invalid')
    (workspace / 'another-service.txt').write_text('concurrent main change\n')
    git(workspace, 'add', '.')
    git(workspace, 'commit', '-m', 'direct main change')
    # WHEN this combined state reaches the shared workflow.
    result, values = github['invoke']('prepare')
    # THEN the old PR cannot authorize skipping any current checks.
    assert result.returncode == 0
    assert values['reuse'] == 'false'


def test_forged_source_tree_cannot_be_used_as_test_evidence(github):
    # GIVEN a proof claiming a benign tree but a PR head with different source.
    github['record']()
    source = github['source']
    git(source, 'checkout', 'feature')
    (source / 'app.txt').write_text('different, unapproved code\n')
    git(source, 'commit', '-am', 'different source')
    forged_head = git(source, 'rev-parse', 'HEAD')
    github['run']['head_sha'] = forged_head
    github['run']['pull_requests'][0]['head']['sha'] = forged_head
    github['routes']['git/commits/' + github['merge']]['parents'][1]['sha'] = forged_head
    github['routes'][f"compare/{github['base']}...{forged_head}"] = {'merge_base_commit': {'sha': github['base']}}
    # WHEN the real selector reconstructs the tree instead of trusting the proof.
    result, values = github['invoke']('prepare')
    # THEN the forged source assertion cannot skip checks.
    assert result.returncode == 0
    assert values['reuse'] == 'false'


def test_all_service_images_are_required_together(github):
    # GIVEN a multi-service matrix whose second image has not been uploaded.
    matrix = github['matrix']
    matrix['include'].append({**matrix['include'][0], 'service': 'frontend'})
    git(github['workspace'], 'checkout', github['merge'])
    overrides = {'GITHUB_RUN_ID': '100', 'GITHUB_EVENT_NAME': 'pull_request', 'BUILD_MATRIX': json.dumps(matrix)}
    # WHEN the recorder is called after checks, then no partial proof is issued.
    result, values = github['invoke']('record', **overrides)
    assert result.returncode == 0
    assert values['record'] == 'false'
    # GIVEN both immutable images, WHEN recording and restoring the whole application,
    # THEN both services are bound to the same successful checks and configuration.
    github['upload'](902, 'frontend-production-image-1', zipped('production-image.tar', b'frontend image'))
    _, values = github['invoke']('record', **overrides)
    assert values['record'] == 'true'
    github['upload'](900, 'verified-pr-' + values['key'], zipped('proof.json', (github['runtime'] / 'verified-build/proof.json').read_bytes()))
    git(github['workspace'], 'checkout', github['squash'])
    _, values = github['invoke']('prepare', BUILD_MATRIX=json.dumps(matrix))
    assert values['reuse'] == 'true'
    result, _ = github['invoke']('restore', BUILD_PROOF_ID='900', BUILD_SERVICE='frontend', BUILD_MATRIX=json.dumps(matrix))
    assert result.returncode == 0, result.stderr
    assert (github['runtime'] / 'production-image.tar').read_bytes() == b'frontend image'


@pytest.mark.parametrize('resolved', [True, False])
def test_runtime_loader_pins_actions_or_disables_reuse(github, tmp_path, resolved):
    # GIVEN GitHub's current referenced-workflow metadata (or an unavailable API).
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    gh = bindir / 'gh'
    gh.write_text('#!' + sys.executable + '\nimport os, sys, urllib.request\n'
                  + ('sys.exit(1)\n' if not resolved else
                     'print(urllib.request.urlopen(os.environ["GITHUB_API_URL"] + "/" + sys.argv[2]).read().decode())\n'))
    gh.chmod(0o755)
    output = tmp_path / 'pin-output'
    # WHEN the real loader process dispatches the composite actions.
    result = subprocess.run([sys.executable, str(ROOT / '.github/actions/pin-ci-runtime/pin.py')],
        env={**github['env'], 'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
             'SHARED_REPOSITORY': 'owner/shared', 'SHARED_REVISION': '', 'GITHUB_OUTPUT': str(output)},
        text=True, capture_output=True)
    # THEN all shared check actions use the verified revision; lookup failure is explicit.
    assert result.returncode == 0, result.stderr
    revision = REVISION if resolved else 'unavailable'
    assert output.read_text() == 'revision=' + revision + '\n'
    for name in ('docker-test', 'coverage-report', 'container-e2e', 'verified-build'):
        action = json.loads((github['workspace'] / '.git/startup-actions' / name / 'action.yml').read_text())
        expected = REVISION if resolved else 'main'
        assert action['runs']['steps'][0]['uses'] == f'owner/shared/.github/actions/{name}@{expected}'
    verified = json.loads((github['workspace'] / '.git/startup-actions/verified-build/action.yml').read_text())
    assert verified['inputs']['revision']['default'] == revision


@pytest.mark.parametrize('change', [
    'tree', 'failed', 'cancelled', 'in_progress', 'rerun', 'foreign_repository', 'fork',
    'workflow_id', 'workflow_path', 'runtime', 'expired', 'missing_image', 'digest',
    'old', 'proof_bytes', 'proof_tree', 'source_parents', 'api_unavailable',
    'configuration', 'platform', 'untracked_context', 'forced', 'manual', 'pr',
])
def test_ineligible_evidence_falls_back_to_the_full_pipeline(github, change):
    # GIVEN a previously recorded PR build and one reason it is not valid for this push.
    github['record']()
    overrides = {}
    if change == 'tree':
        git(github['workspace'], 'checkout', github['base'])
    elif change in ('failed', 'cancelled'):
        github['run']['conclusion'] = 'failure' if change == 'failed' else 'cancelled'
    elif change == 'in_progress':
        github['run']['status'] = 'in_progress'
    elif change == 'rerun':
        github['run']['run_attempt'] = 2
    elif change == 'foreign_repository':
        github['run']['repository'] = {'full_name': 'other/app'}
    elif change == 'fork':
        github['run']['head_repository'] = {'full_name': 'fork/app'}
    elif change == 'workflow_id':
        github['run']['workflow_id'] = 10
    elif change == 'workflow_path':
        github['run']['path'] = '.github/workflows/forged.yml'
    elif change == 'runtime':
        overrides['BUILD_REVISION'] = 'b' * 40
    elif change == 'expired':
        github['artifacts'][901]['expired'] = True
    elif change == 'missing_image':
        del github['artifacts'][901]
    elif change == 'digest':
        github['artifacts'][901]['digest'] = 'sha256:' + '0' * 64
    elif change == 'old':
        github['run']['created_at'] = '2020-01-01T00:00:00Z'
    elif change == 'proof_bytes':
        github['archives'][900] = b'tampered'
    elif change == 'proof_tree':
        proof = json.loads((github['runtime'] / 'verified-build/proof.json').read_text())
        proof['identity']['tree'] = 'b' * 40
        github['upload'](900, github['artifacts'][900]['name'], zipped('proof.json', json.dumps(proof)))
    elif change == 'source_parents':
        github['routes']['git/commits/' + github['merge']]['parents'] = [{'sha': github['head']}]
    elif change == 'api_unavailable':
        del github['routes']['actions/runs/200']
    elif change in ('configuration', 'forced'):
        configuration = github['configuration'] | ({'run_e2e': False} if change == 'configuration' else {'reuse_pr_build': False})
        overrides['BUILD_CONFIGURATION'] = json.dumps(configuration)
    elif change in ('platform', 'untracked_context'):
        matrix = github['matrix']
        matrix['include'][0]['platforms' if change == 'platform' else 'additional_build_context'] = 'linux/arm64' if change == 'platform' else 'shared=../outside'
        overrides['BUILD_MATRIX'] = json.dumps(matrix)
    elif change in ('manual', 'pr'):
        overrides['GITHUB_EVENT_NAME'] = 'workflow_dispatch' if change == 'manual' else 'pull_request'
    # WHEN the real selection process encounters that evidence.
    result, values = github['invoke']('prepare', **overrides)
    # THEN normal tests/build/E2E remain required, without failing direct pushes.
    assert result.returncode == 0, result.stderr
    assert values['reuse'] == 'false'
    assert 'proof_id' not in values


@pytest.mark.parametrize('failure', ['tamper', 'deleted', 'zip_path', 'failed_run'])
def test_restore_fails_closed_if_evidence_changes_after_selection(github, failure):
    # GIVEN evidence selected successfully before a publishing job starts.
    github['record']()
    _, values = github['invoke']('prepare')
    assert values['reuse'] == 'true'
    if failure == 'tamper':
        github['archives'][901] = zipped('production-image.tar', b'tampered')
    elif failure == 'deleted':
        del github['artifacts'][901]
    elif failure == 'failed_run':
        github['run']['conclusion'] = 'failure'
    else:
        github['upload'](901, 'backend-production-image-1', zipped('../production-image.tar', b'unsafe'))
        proof = json.loads((github['runtime'] / 'verified-build/proof.json').read_text())
        proof['images']['backend']['digest'] = github['artifacts'][901]['digest']
        github['upload'](900, github['artifacts'][900]['name'], zipped('proof.json', json.dumps(proof)))
    # WHEN the actual privileged restore path revalidates the evidence.
    result, _ = github['invoke']('restore', BUILD_PROOF_ID='900')
    # THEN there is no image to publish and the process exits nonzero.
    assert result.returncode != 0
    assert not (github['runtime'] / 'production-image.tar').exists()


@pytest.mark.parametrize('reuse,prepare,proof,integration,image,e2e,expected', [
    ('true', 'success', '900', 'skipped', 'skipped', 'skipped', 0),
    ('true', 'failure', '900', 'skipped', 'skipped', 'skipped', 1),
    ('true', 'success', '', 'skipped', 'skipped', 'skipped', 1),
    ('false', 'success', '', 'skipped', 'skipped', 'skipped', 1),
    ('false', 'success', '', 'success', 'success', 'success', 0),
    ('false', 'success', '', 'success', 'success', 'failure', 1),
])
def test_real_workflow_gate_preserves_full_fallback(reuse, prepare, proof, integration, image, e2e, expected):
    # GIVEN the shipped gate, including skipped jobs from the Actions scheduler.
    workflow = yaml.load((ROOT / '.github/workflows/build-and-deploy-service-parallel.yml').read_text(), Loader=yaml.BaseLoader)
    gate = workflow['jobs']['checks']['steps'][0]['run']
    # WHEN its actual shell decides whether publication is allowed.
    result = subprocess.run(['bash', '-e', '-c', gate], env={**os.environ,
        'PREPARE_RESULT': prepare, 'REUSE': reuse, 'PROOF_ID': proof,
        'INTEGRATION_RESULT': integration, 'IMAGE_RESULT': image, 'E2E_RESULT': e2e, 'RUN_E2E': 'true'})
    # THEN only verified reuse or a completely green fresh pipeline can publish.
    assert result.returncode == expected
