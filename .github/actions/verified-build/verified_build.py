"""Reuse immutable PR artifacts only after verifying their source, runtime and run.

The GitHub API is the trust boundary. A cache lookup never decides which checks
are required: the reusable workflow supplies its complete configuration. Lookup
failures run the normal pipeline; restore failures stop before publication.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

SCHEMA = 1
MAX_AGE = timedelta(days=1)
MAX_PROOF_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 16 * 1024 ** 3


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        redirected = super().redirect_request(request, response, code, message, headers, url)
        if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(request.full_url).netloc:
            redirected.remove_header('Authorization')
        return redirected


def api(path, destination=None, limit=MAX_PROOF_BYTES):
    base = os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')
    request = urllib.request.Request(base + '/repos/' + os.environ['GITHUB_REPOSITORY'] + '/' + path,
                                     headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                                              'Accept': 'application/vnd.github+json',
                                              'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=30) as response:
        if destination is None:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('API response exceeds limit')
            return json.loads(data)
        digest = hashlib.sha256()
        size = 0
        with destination.open('wb') as output:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise ValueError('Artifact exceeds limit')
                digest.update(block)
                output.write(block)
        return 'sha256:' + digest.hexdigest()


def output(**values):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        for key, value in values.items():
            stream.write(f'{key}={value}\n')


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=os.environ['GITHUB_WORKSPACE'], text=True).strip()


def runtime_matches(run, revision):
    expected = os.environ['BUILD_SHARED_REPOSITORY'] + '/.github/workflows/build-and-deploy-service-parallel.yml@'
    refs = [item for item in run.get('referenced_workflows', []) if item['path'].startswith(expected)]
    return len(refs) == 1 and refs[0]['sha'] == revision


def identity():
    configuration = json.loads(os.environ['BUILD_CONFIGURATION'])
    matrix = json.loads(os.environ['BUILD_MATRIX'])
    revision = os.environ['BUILD_REVISION']
    # Additional contexts may point outside the tracked tree or resolve mutable URLs.
    if (not configuration.get('reuse_pr_build', True)
            or not re.fullmatch('[0-9a-f]{40}', revision)
            or any(item['additional_build_context'] for item in matrix['include'])):
        return None, None, None
    run = api('actions/runs/' + str(int(os.environ['GITHUB_RUN_ID'])))
    if not runtime_matches(run, revision):
        return None, None, None
    value = {
        'schema': SCHEMA, 'repository': os.environ['GITHUB_REPOSITORY'],
        'tree': git('rev-parse', 'HEAD^{tree}'), 'runtime': revision,
        'configuration': configuration, 'matrix': matrix,
        'workflow_id': run['workflow_id'], 'workflow_path': run['path'].split('@')[0],
    }
    key = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return value, key, run


def artifact(artifact_id, run_id, name, expected_digest=None):
    item = api('actions/artifacts/' + str(int(artifact_id)))
    if (item['expired'] or item['name'] != name or item['workflow_run']['id'] != run_id
            or not re.fullmatch('sha256:[0-9a-f]{64}', item.get('digest', ''))
            or (expected_digest is not None and item['digest'] != expected_digest)):
        raise ValueError('Artifact identity mismatch')
    return item


def download(item, destination, limit):
    digest = api(f"actions/artifacts/{int(item['id'])}/zip", destination, limit)
    if digest != item['digest']:
        raise ValueError('Artifact digest mismatch')


def validate(proof_id, expected, key):
    metadata = api('actions/artifacts/' + str(int(proof_id)))
    run_id = metadata['workflow_run']['id']
    metadata = artifact(proof_id, run_id, 'verified-pr-' + key)
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / 'proof.zip'
        download(metadata, archive, MAX_PROOF_BYTES)
        with zipfile.ZipFile(archive) as zipped:
            if zipped.namelist() != ['proof.json'] or zipped.getinfo('proof.json').file_size > MAX_PROOF_BYTES:
                raise ValueError('Invalid proof archive')
            proof = json.loads(zipped.read('proof.json'))
    if proof['identity'] != expected or proof['run_id'] != run_id:
        raise ValueError('Proof does not match this source and configuration')
    run = api('actions/runs/' + str(int(run_id)))
    created = datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
    if (run['event'] != 'pull_request' or run['status'] != 'completed' or run['conclusion'] != 'success'
            or run['run_attempt'] != proof['attempt'] or run['workflow_id'] != expected['workflow_id']
            or run['path'].split('@')[0] != expected['workflow_path']
            or run['repository']['full_name'] != expected['repository']
            or run['head_repository']['full_name'] != expected['repository']
            or not timedelta(0) <= datetime.now(timezone.utc) - created <= MAX_AGE
            or not runtime_matches(run, expected['runtime'])):
        raise ValueError('PR run is not eligible')
    source_sha = proof['source_sha']
    if not re.fullmatch('[0-9a-f]{40}', source_sha):
        raise ValueError('Invalid source commit')
    commit = api('git/commits/' + source_sha)
    pulls = run.get('pull_requests', [])
    if len(pulls) != 1:
        raise ValueError('Missing original PR merge identity')
    base, head = pulls[0]['base']['sha'], pulls[0]['head']['sha']
    if (not all(re.fullmatch('[0-9a-f]{40}', sha) for sha in (base, head))
            or head != run['head_sha'] or commit['tree']['sha'] != expected['tree']
            or [parent['sha'] for parent in commit['parents']] != [base, head]):
        raise ValueError('Proof is not the checked PR source')
    # The proof itself is untrusted. Reconstruct the merge tree from GitHub's
    # recorded base/head; never accept an arbitrary commit supplied in a JSON file.
    comparison = api(f'compare/{base}...{head}')
    ancestor = comparison['merge_base_commit']['sha']
    if not re.fullmatch('[0-9a-f]{40}', ancestor):
        raise ValueError('Invalid merge base')
    git('fetch', '--quiet', '--no-tags', '--depth=1', 'origin', base, head, ancestor)
    reconstructed = git('merge-tree', '--write-tree', '--merge-base=' + ancestor, base, head).splitlines()[0]
    if reconstructed != expected['tree']:
        raise ValueError('PR merge tree differs from this source')
    services = {item['service'] for item in expected['matrix']['include']}
    if set(proof['images']) != services:
        raise ValueError('Incomplete service images')
    for service, item in proof['images'].items():
        artifact(item['id'], run_id, f"{service}-production-image-{proof['attempt']}", item['digest'])
    return proof


def prepare():
    output(reuse='false', record='false')
    try:
        expected, key, _ = identity()
        if expected is None:
            print('Full checks: reuse disabled or runtime/context not eligible.')
            return
        output(key=key)
        if os.environ['GITHUB_EVENT_NAME'] != 'push':
            print('Full checks: PR and manual runs always execute the complete pipeline.')
            return
        query = urllib.parse.urlencode({'name': 'verified-pr-' + key, 'per_page': 100})
        candidates = api('actions/artifacts?' + query)['artifacts']
        for item in candidates:
            try:
                proof = validate(item['id'], expected, key)
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError):
                continue
            output(reuse='true', proof_id=item['id'])
            message = f"Reuse verified PR run {proof['run_id']} for tree {expected['tree']}."
            print(message)
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
                    summary.write(message + '\n')
            return
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # API errors, unavailable artifacts and direct pushes must not bypass tests.
        pass
    print('Full checks: no verifiable equivalent PR build found.')


def record():
    output(record='false')
    try:
        expected, key, run = identity()
        if expected is None or os.environ['GITHUB_EVENT_NAME'] != 'pull_request':
            return
        run_id = int(os.environ['GITHUB_RUN_ID'])
        attempt = int(os.environ['GITHUB_RUN_ATTEMPT'])
        if run['head_repository']['full_name'] != expected['repository']:
            return  # Forks keep their full checks, without becoming reusable evidence.
        items = api(f'actions/runs/{run_id}/artifacts?per_page=100')['artifacts']
        images = {}
        for service in expected['matrix']['include']:
            name = f"{service['service']}-production-image-{attempt}"
            matches = [item for item in items if item['name'] == name]
            if len(matches) != 1:
                raise ValueError('Image missing (including partial reruns)')
            item = artifact(matches[0]['id'], run_id, name)
            images[service['service']] = {'id': item['id'], 'digest': item['digest']}
        proof = {'identity': expected, 'source_sha': git('rev-parse', 'HEAD'),
                 'run_id': run_id, 'attempt': attempt, 'images': images}
        directory = Path(os.environ['RUNNER_TEMP']) / 'verified-build'
        directory.mkdir(exist_ok=True)
        (directory / 'proof.json').write_text(json.dumps(proof, sort_keys=True))
        output(key=key, record='true')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Checks passed; reusable evidence unavailable. A push will run full checks.')


def restore():
    expected, key, _ = identity()
    if expected is None:
        raise ValueError('Reuse no longer eligible')
    proof = validate(os.environ['BUILD_PROOF_ID'], expected, key)
    service = os.environ['BUILD_SERVICE']
    item = proof['images'][service]
    metadata = artifact(item['id'], proof['run_id'], f"{service}-production-image-{proof['attempt']}", item['digest'])
    with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as directory:
        archive = Path(directory) / 'image.zip'
        download(metadata, archive, MAX_IMAGE_BYTES)
        with zipfile.ZipFile(archive) as zipped:
            if (zipped.namelist() != ['production-image.tar']
                    or zipped.getinfo('production-image.tar').file_size > MAX_IMAGE_BYTES):
                raise ValueError('Unexpected image archive contents')
            # Never extract paths, permissions or symlinks supplied by a PR artifact.
            with zipped.open('production-image.tar') as source, (Path(directory) / 'image.tar').open('wb') as target:
                shutil.copyfileobj(source, target)
        (Path(directory) / 'image.tar').replace(Path(os.environ['RUNNER_TEMP']) / 'production-image.tar')
    print(f"Restored verified image for {service} from PR run {proof['run_id']}.")


if __name__ == '__main__':
    {'prepare': prepare, 'record': record, 'restore': restore}[os.environ['BUILD_MODE']]()
