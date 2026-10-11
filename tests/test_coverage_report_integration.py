"""Run the shipped coverage report against a local stand-in for the GitHub API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / ".github/actions/coverage-report/report.py"

COBERTURA = """<?xml version="1.0" ?>
<coverage version="7.16.2" lines-valid="{lines_valid}" lines-covered="{lines_covered}"
 line-rate="0" branches-valid="{branches_valid}" branches-covered="{branches_covered}" branch-rate="0">
 <sources><source>.</source></sources><packages/>
</coverage>
"""


class FakeGitHub:
    """Serves the issue-comment endpoints the report uses and records calls."""

    def __init__(self, comments=None, status=200):
        self.comments = list(comments or [])
        self.status = status
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, payload, status=200):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def handle_call(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                fake.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
                if fake.status != 200:
                    return self.respond({"message": "Resource not accessible by integration"}, fake.status)
                if self.command == "GET":
                    page = int(parse_qs(urlsplit(self.path).query)["page"][0])
                    return self.respond(fake.comments[(page - 1) * 100 : page * 100])
                if self.command == "POST":
                    fake.comments.append({"id": 900, "body": body["body"]})
                    return self.respond(fake.comments[-1], 201)
                comment_id = int(self.path.rsplit("/", 1)[1])
                comment = next(c for c in fake.comments if c["id"] == comment_id)
                comment["body"] = body["body"]
                return self.respond(comment)

            do_GET = do_POST = do_PATCH = handle_call

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def github():
    servers = []

    def start(**kwargs):
        servers.append(FakeGitHub(**kwargs))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def write_cobertura(path, lines=(159, 233), branches=(22, 44)):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(COBERTURA.format(lines_covered=lines[0], lines_valid=lines[1],
                                     branches_covered=branches[0], branches_valid=branches[1]))
    return path


def require_docker():
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode:
        if os.environ.get("STARTUP_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("Docker is required for the docker-test integration")
        pytest.skip("Docker is required for the docker-test integration")


def report(tmp_path, api, *files, event="pull_request", title="Coverage: backend", key="backend"):
    event_file = tmp_path / "event.json"
    payload = {"pull_request": {"number": 7}} if event == "pull_request" else {"ref": "refs/heads/main"}
    event_file.write_text(json.dumps(payload))
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        [sys.executable, str(REPORT), "--title", title, "--key", key, *files],
        cwd=tmp_path, text=True, capture_output=True, timeout=30,
        env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_EVENT_PATH": str(event_file),
             "GITHUB_EVENT_NAME": event, "GITHUB_REPOSITORY": "example/startup",
             "GITHUB_API_URL": api, "GITHUB_SHA": "0123456789abcdef", "GITHUB_TOKEN": "test-token"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result, summary.read_text() if summary.exists() else ""


def test_pull_request_gets_summary_table_and_one_comment(tmp_path, github):
    # GIVEN a backend Cobertura file and a pull request without a coverage comment
    api = github(comments=[{"id": 1, "body": "Looks good"}])
    write_cobertura(tmp_path / "backend/coverage/cobertura.xml")
    # WHEN the report runs
    result, summary = report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml")
    # THEN the job summary shows the line and branch rates with their counts
    assert "### Coverage: backend" in summary
    assert "| backend | 68.2% (159/233) | 50.0% (22/44) |" in summary
    assert "0123456" in summary
    # AND exactly one comment is created, authenticated and carrying the marker
    posts = [r for r in api.requests if r[0] == "POST"]
    assert len(posts) == 1
    method, path, authorization, body = posts[0]
    assert path == "/repos/example/startup/issues/7/comments"
    assert authorization == "Bearer test-token"
    assert body["body"].startswith("<!-- deploy-your-startup-coverage: backend -->")
    assert "| backend | 68.2% (159/233) | 50.0% (22/44) |" in body["body"]
    assert api.comments[0] == {"id": 1, "body": "Looks good"}


def test_second_run_updates_the_sticky_comment(tmp_path, github):
    # GIVEN a pull request whose coverage comment sits on the second page
    marker = "<!-- deploy-your-startup-coverage: backend -->"
    other = [{"id": n, "body": f"comment {n}"} for n in range(1, 101)]
    frontend = {"id": 150, "body": "<!-- deploy-your-startup-coverage: frontend -->\nold"}
    api = github(comments=[*other, frontend, {"id": 151, "body": f"{marker}\nold"}])
    write_cobertura(tmp_path / "backend/coverage/cobertura.xml", lines=(200, 233))
    # WHEN the report runs again
    report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml")
    # THEN the existing comment is edited instead of adding a new one
    assert not [r for r in api.requests if r[0] == "POST"]
    patches = [r for r in api.requests if r[0] == "PATCH"]
    assert [p[1] for p in patches] == ["/repos/example/startup/issues/comments/151"]
    assert "85.8% (200/233)" in api.comments[-1]["body"]
    # AND another service's comment is left alone
    assert frontend["body"].endswith("old")


def test_several_services_share_one_table(tmp_path, github):
    # GIVEN coverage for a backend and a frontend, where the frontend has no branches
    api = github()
    write_cobertura(tmp_path / "backend/coverage/cobertura.xml")
    write_cobertura(tmp_path / "frontend/coverage/cobertura.xml", lines=(93, 98), branches=(0, 0))
    # WHEN both are reported
    _, summary = report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml",
                        "frontend=frontend/coverage/cobertura.xml", title="Coverage", key="e2e")
    # THEN each service has a row; a service without branches shows a dash
    assert "| backend | 68.2% (159/233) | 50.0% (22/44) |" in summary
    assert "| frontend | 94.9% (93/98) | – |" in summary


def test_service_without_coverage_file_is_skipped_silently(tmp_path, github):
    # GIVEN a service whose tests wrote no coverage file
    api = github()
    # WHEN the report runs
    result, summary = report(tmp_path, api.url, "frontend=frontend/coverage/cobertura.xml")
    # THEN nothing is reported, no API is called and there is no warning
    assert summary == ""
    assert api.requests == []
    assert "::warning" not in result.stdout


def test_push_reports_only_the_job_summary(tmp_path, github):
    # GIVEN a push to main instead of a pull request
    api = github()
    write_cobertura(tmp_path / "backend/coverage/cobertura.xml")
    # WHEN the report runs
    _, summary = report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml", event="push")
    # THEN the summary has the table and no comment is attempted
    assert "| backend |" in summary
    assert api.requests == []


def test_refused_comment_keeps_the_job_green(tmp_path, github):
    # GIVEN a read-only token, as on pull requests from forks
    api = github(status=403)
    write_cobertura(tmp_path / "backend/coverage/cobertura.xml")
    # WHEN the report runs
    result, summary = report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml")
    # THEN the job continues with a warning and the summary still has the table
    assert "::warning title=Coverage report::Pull request comment not written" in result.stdout
    assert "| backend |" in summary


def test_unreadable_file_is_skipped_with_a_warning(tmp_path, github):
    # GIVEN a coverage file the runner may not read
    if os.geteuid() == 0:
        pytest.skip("root reads every file")
    api = github()
    unreadable = write_cobertura(tmp_path / "backend/coverage/cobertura.xml")
    unreadable.chmod(0)
    # WHEN it is reported
    result, summary = report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml")
    # THEN the job stays green and the warning names the service
    assert summary == ""
    assert "::warning title=Coverage report::backend:" in result.stdout
    assert "cannot be read" in result.stdout


def test_file_that_is_not_cobertura_is_skipped_with_a_warning(tmp_path, github):
    # GIVEN one valid report and one file in another format
    api = github()
    write_cobertura(tmp_path / "backend/coverage/cobertura.xml")
    broken = tmp_path / "worker/coverage/cobertura.xml"
    broken.parent.mkdir(parents=True)
    broken.write_text("<report><counter/></report>")
    # WHEN both are reported
    result, summary = report(tmp_path, api.url, "backend=backend/coverage/cobertura.xml",
                             "worker=worker/coverage/cobertura.xml")
    # THEN the valid service is reported and the other one is named in a warning
    assert "| backend |" in summary
    assert "worker" not in summary
    assert "::warning title=Coverage report::worker:" in result.stdout


def test_docker_test_brings_the_coverage_file_out_of_the_container(tmp_path):
    # GIVEN a test image whose make.sh recreates coverage/ as a non-root user
    require_docker()
    service = tmp_path / "service"
    service.mkdir()
    (service / "make.sh").write_text(
        "#!/bin/sh\nset -e\ntest \"$1\" = test\ntest -n \"$DATABASE_URL\"\n"
        # Like many coverage tools: delete and recreate the report directory,
        # then write a file only its owner may read.
        "rm -rf coverage\nmkdir coverage\numask 077\n"
        "printf '<coverage lines-valid=\"4\" lines-covered=\"3\" line-rate=\"0.75\"/>' > coverage/cobertura.xml\n"
    )
    (service / "make.sh").chmod(0o755)
    (service / "Dockerfile").write_text(
        "FROM busybox:1.37\nWORKDIR /srv/app\nCOPY make.sh .\nRUN chown 1234 /srv/app\nUSER 1234\n")
    image = f"startup-coverage-check:{os.getpid()}"
    built = subprocess.run(["docker", "build", "-q", "-t", image, str(service)], capture_output=True, text=True, timeout=240)
    assert built.returncode == 0, built.stderr
    try:
        # WHEN the action's test script runs it
        coverage_dir = tmp_path / "out"
        result = subprocess.run(
            ["bash", str(ROOT / ".github/actions/docker-test/run-tests.sh"), image, "postgres://db/test", str(coverage_dir)],
            capture_output=True, text=True, timeout=240,
        )
        # THEN the Cobertura file is on the host and the report reads it
        assert result.returncode == 0, result.stdout + result.stderr
        assert (coverage_dir / "cobertura.xml").read_text().startswith("<coverage")
        summary = subprocess.run([sys.executable, str(REPORT), f"service={coverage_dir}/cobertura.xml"],
                                 capture_output=True, text=True, env={**os.environ, "GITHUB_EVENT_PATH": ""})
        assert "| service | 75.0% (3/4) | – |" in summary.stdout
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True)


def test_failing_tests_still_fail_the_step(tmp_path):
    # GIVEN a test image whose tests fail
    require_docker()
    service = tmp_path / "service"
    service.mkdir()
    (service / "make.sh").write_text("#!/bin/sh\necho 'FAILED test_login'\nexit 1\n")
    (service / "make.sh").chmod(0o755)
    (service / "Dockerfile").write_text("FROM busybox:1.37\nWORKDIR /app\nCOPY make.sh .\n")
    image = f"startup-coverage-fail:{os.getpid()}"
    assert subprocess.run(["docker", "build", "-q", "-t", image, str(service)], capture_output=True, timeout=240).returncode == 0
    try:
        # WHEN the action's test script runs it
        result = subprocess.run(
            ["bash", str(ROOT / ".github/actions/docker-test/run-tests.sh"), image, "postgres://db/test", str(tmp_path / "out")],
            capture_output=True, text=True, timeout=240,
        )
        # THEN the failure reaches the workflow, no coverage file appears and
        # the container is removed
        assert result.returncode == 1
        leftover = subprocess.run(["docker", "ps", "-aq", "--filter", f"ancestor={image}"], capture_output=True, text=True)
        assert leftover.stdout.strip() == ""
        assert "FAILED test_login" in result.stdout
        assert not (tmp_path / "out/cobertura.xml").exists()
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True)
