"""Bootstrap only: dispatch shared actions at the reusable workflow's revision."""
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    repository = os.environ['SHARED_REPOSITORY']
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
        raise SystemExit('Invalid shared repository')
    revision = os.environ.get('SHARED_REVISION', '')
    if not revision:
        try:
            result = subprocess.run(
                ['gh', 'api', f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"],
                check=True, capture_output=True, text=True, timeout=30,
            )
            refs = json.loads(result.stdout)['referenced_workflows']
            matches = {item['sha'] for item in refs if item['path'].startswith(
                repository + '/.github/workflows/build-and-deploy-service-parallel.yml@')}
            if len(matches) != 1:
                raise ValueError('Ambiguous reusable workflow revision')
            revision = matches.pop()
        except (subprocess.SubprocessError, ValueError, KeyError):
            # Preserve the pre-existing full pipeline when Actions metadata is unavailable.
            revision = 'unavailable'
    if revision != 'unavailable' and not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise SystemExit('Invalid shared workflow revision')
    reference = 'main' if revision == 'unavailable' else revision
    definitions = {
        'docker-test': {
            'cache_scope': 'test', 'context': '', 'dockerfile': '', 'image': '', 'tag': '',
            'database_url': '', 'run_tests': 'true', 'run_lint': 'false',
            'additional_build_context': '', 'require_coverage': 'false', 'coverage_dir': '',
        },
        'coverage-report': {'files': '', 'required': 'false', 'title': 'Coverage',
                            'measured_from': '', 'comment_key': '', 'github_token': ''},
        'container-e2e': {'directory': '', 'image': '', 'shard': '', 'total': ''},
        'lint-contract': {},
        'current-deployment': {},
        'verified-build': {'mode': '', 'configuration': '{}', 'matrix': '{}',
                           'revision': revision, 'shared_repository': repository,
                           'proof_id': '', 'service': ''},
    }
    target = Path(os.environ['GITHUB_WORKSPACE']) / '.git/startup-actions'
    for name, inputs in definitions.items():
        outputs = {
            'current-deployment': ['current'],
            'docker-test': ['coverage_file'],
            'verified-build': ['key', 'reuse', 'proof_id', 'record'],
        }.get(name, [])
        action = {
            'name': 'Pinned ' + name, 'description': 'Shared CI runtime at ' + reference,
            'inputs': {key: {'description': key, 'default': value} for key, value in inputs.items()},
            'outputs': {key: {'description': key, 'value': '${{ steps.action.outputs.' + key + ' }}'} for key in outputs},
            'runs': {'using': 'composite', 'steps': [{
                'id': 'action', 'uses': f'{repository}/.github/actions/{name}@{reference}',
                'with': {key: '${{ inputs.' + key + ' }}' for key in inputs},
            }]},
        }
        directory = target / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'action.yml').write_text(json.dumps(action))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('revision=' + revision + '\n')


if __name__ == '__main__':
    main()
