"""Run the real check entrypoint and pytest scheduler against isolated scenarios."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', ['none', 'parallel', 'browser'])
def test_browser_checks_wait_for_parallel_teardown_and_preserve_failures(tmp_path, failure):
    # GIVEN the shipped entrypoint and real pytest workers sharing a network boundary.
    for name in ('make.sh', 'pyproject.toml', 'uv.lock'):
        shutil.copyfile(ROOT / name, tmp_path / name)
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_parallel.py').write_text('''
import os
from pathlib import Path
import time

def test_container_lifecycle():
    Path('container-started').touch()
    try:
        deadline = time.monotonic() + 2
        while not Path('browser-probed').exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert os.environ['CHECK_PHASE_FAILURE'] != 'parallel', 'parallel failure'
    finally:
        Path('container-removed').touch()
''')
    (tests / 'test_kpis_runtime_integration.py').write_text('''
import os
from pathlib import Path
import time

def test_browser_navigation():
    deadline = time.monotonic() + 5
    while not Path('container-started').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    teardown_finished = Path('container-removed').exists()
    Path('browser-probed').touch()
    assert teardown_finished, 'browser overlapped container lifecycle'
    Path('browser-after-teardown').touch()
    assert os.environ['CHECK_PHASE_FAILURE'] != 'browser', 'browser failure'
''')
    # WHEN make.sh runs the real locked pytest, with two workers available.
    result = subprocess.run(['bash', str(tmp_path / 'make.sh'), 'test'], cwd=tmp_path,
        env={**os.environ, 'UV_PROJECT_ENVIRONMENT': str(ROOT / '.venv'),
             'PYTEST_XDIST_AUTO_NUM_WORKERS': '2', 'CHECK_PHASE_FAILURE': failure},
        text=True, capture_output=True, timeout=60)
    # THEN browser checks start after container teardown, and either phase can fail CI.
    assert result.returncode == (0 if failure == 'none' else 1), result.stdout + result.stderr
    assert (tmp_path / 'container-removed').exists(), result.stdout + result.stderr
    assert (tmp_path / 'browser-probed').exists() == (failure != 'parallel'), result.stdout + result.stderr
    assert (tmp_path / 'browser-after-teardown').exists() == (failure != 'parallel'), result.stdout + result.stderr
    if failure != 'none':
        assert failure + ' failure' in result.stdout
