"""Check freshness after acquiring the application's publication lock."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def api(path: str) -> dict:
    endpoint = os.environ.get('GITHUB_API_URL', 'https://api.github.com')
    request = Request(
        f"{endpoint}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json'},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    current = True
    # Manual runs deliberately support redeploying a selected historical ref.
    if os.environ['GITHUB_EVENT_NAME'] == 'push':
        run = api('actions/runs/' + os.environ['GITHUB_RUN_ID'])
        page = 1
        while True:
            query = urlencode({'branch': run['head_branch'], 'event': 'push',
                               'per_page': 100, 'page': page})
            runs = api(f"actions/workflows/{run['workflow_id']}/runs?{query}")['workflow_runs']
            if any(item['run_number'] > run['run_number'] for item in runs):
                current = False
                break
            if any(item['id'] == run['id'] for item in runs):
                break
            if len(runs) < 100:
                raise ValueError('Current push missing from workflow history')
            page += 1
    message = ('Current run may publish checked images.' if current else
               'Publication skipped: a newer push to this workflow and branch exists.')
    print(message)
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
        output.write('current=' + str(current).lower() + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as summary:
            summary.write(message + '\n')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Exception messages can include URLs; freshness failures must block publication.
        raise SystemExit('Cannot verify deployment freshness: ' + type(error).__name__) from None
