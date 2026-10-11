#!/usr/bin/env python3
"""Report Cobertura coverage files in the job summary and a sticky PR comment.

Usage: report.py [--title TITLE] [--key KEY] NAME=PATH [NAME=PATH ...]

Reads only Cobertura XML, the file every service's `./make.sh test` may write
to `<service>/coverage/cobertura.xml`; it never learns which language or tool
produced it. A missing file is skipped silently, so services without coverage
need no configuration. Reporting never fails the job: an unreadable file or a
refused GitHub API call becomes a workflow warning.

Environment (set by GitHub Actions): GITHUB_STEP_SUMMARY, GITHUB_EVENT_PATH,
GITHUB_REPOSITORY, GITHUB_API_URL, GITHUB_SHA, GITHUB_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class Rate:
    percent: float
    covered: int | None
    valid: int | None

    def render(self) -> str:
        if self.valid == 0:
            return "–"
        if self.covered is None or self.valid is None:
            return f"{self.percent:.1f}%"
        return f"{self.percent:.1f}% ({self.covered}/{self.valid})"


@dataclass(frozen=True)
class Coverage:
    name: str
    lines: Rate
    branches: Rate


def warn(message: str) -> None:
    print(f"::warning title=Coverage report::{message}")


def read_rate(root: ElementTree.Element, kind: str, rate_attribute: str) -> Rate:
    """Prefer the counts (Cobertura 04 DTD); some writers only give the rate."""
    covered, valid = root.get(f"{kind}-covered"), root.get(f"{kind}-valid")
    if covered is not None and valid is not None:
        covered_count, valid_count = int(covered), int(valid)
        return Rate(100 * covered_count / valid_count if valid_count else 0.0, covered_count, valid_count)
    rate = root.get(rate_attribute)
    return Rate(100 * float(rate), None, None) if rate is not None else Rate(0.0, None, 0)


def read_cobertura(name: str, path: Path) -> Coverage | None:
    try:
        root = ElementTree.parse(path).getroot()
        if root.tag != "coverage":
            raise ValueError(f"root element is <{root.tag}>, not <coverage>")
        return Coverage(name, read_rate(root, "lines", "line-rate"), read_rate(root, "branches", "branch-rate"))
    except (ElementTree.ParseError, ValueError) as error:
        warn(f"{name}: {path} is not a Cobertura file ({error}); skipped.")
        return None
    except OSError as error:
        warn(f"{name}: {path} cannot be read ({error}); skipped.")
        return None


def render(title: str, reports: list[Coverage]) -> str:
    rows = "\n".join(f"| {report.name} | {report.lines.render()} | {report.branches.render()} |" for report in reports)
    commit = os.environ.get("GITHUB_SHA", "")[:7]
    footer = f"\n\n<sub>Cobertura report for {commit}. No threshold is enforced.</sub>" if commit else ""
    return f"### {title}\n\n| Service | Lines | Branches |\n|---|---:|---:|\n{rows}{footer}\n"


def pull_request_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).is_file():
        return None
    event = json.loads(Path(event_path).read_text())
    number = (event.get("pull_request") or {}).get("number")
    return int(number) if number else None


def github(method: str, url: str, token: str, body: dict | None = None) -> list | dict:
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def upsert_comment(number: int, marker: str, body: str) -> None:
    """Create the PR comment, or update the one carrying this report's marker."""
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not token or not repository:
        warn("No GITHUB_TOKEN or GITHUB_REPOSITORY; pull request comment skipped.")
        return
    comments_url = f"{api}/repos/{repository}/issues/{number}/comments"
    try:
        page = 1
        while True:
            comments = github("GET", f"{comments_url}?per_page=100&page={page}", token)
            existing = next((comment for comment in comments if marker in (comment.get("body") or "")), None)
            if existing or len(comments) < 100:
                break
            page += 1
        if existing:
            github("PATCH", f"{api}/repos/{repository}/issues/comments/{existing['id']}", token, {"body": body})
        else:
            github("POST", comments_url, token, {"body": body})
    except (OSError, ValueError) as error:
        # Pull requests from forks get a read-only token; the summary remains.
        warn(f"Pull request comment not written ({error}). The job summary has the report.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default="Coverage")
    parser.add_argument("--key", help="identifies the sticky comment; defaults to the title")
    parser.add_argument("files", nargs="*", metavar="NAME=PATH")
    arguments = parser.parse_args(argv)

    reports = []
    for entry in arguments.files:
        name, separator, path = entry.partition("=")
        if not separator or not name or not path:
            parser.error(f"expected NAME=PATH, got {entry!r}")
        if Path(path).is_file():
            report = read_cobertura(name, Path(path))
            if report:
                reports.append(report)
    if not reports:
        return 0

    markdown = render(arguments.title, reports)
    print(markdown)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    number = pull_request_number()
    if number:
        marker = f"<!-- deploy-your-startup-coverage: {arguments.key or arguments.title} -->"
        upsert_comment(number, marker, f"{marker}\n{markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
