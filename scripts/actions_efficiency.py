#!/usr/bin/env python3
"""Bounded read-only GitHub Actions run counts from reviewed Ponchia repositories."""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

POLICY = Path(__file__).resolve().parents[1] / "policy/repositories.json"
PAGE_SIZE = 100
MAX_PAGES = 30


class AuditError(RuntimeError):
    """Inventory is incomplete; never report a partial total."""


def iso_day(value: str) -> dt.date:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD")
    return parsed


def api_page(owner: str, repo: str, start: str, end: str, page: int) -> dict:
    endpoint = (
        f"/repos/{owner}/{repo}/actions/runs"
        f"?created={start}..{end}&per_page={PAGE_SIZE}&page={page}"
    )
    try:
        proc = subprocess.run(
            ["gh", "api", endpoint], text=True, capture_output=True, timeout=35,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f"{owner}/{repo}: GitHub API unavailable") from exc
    if proc.returncode != 0:
        raise AuditError(f"{owner}/{repo}: GitHub API request failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AuditError(f"{owner}/{repo}: unexpected API response") from exc
    if not isinstance(data, dict):
        raise AuditError(f"{owner}/{repo}: unexpected API shape")
    return data


def collect_runs(fetch, max_pages: int = MAX_PAGES) -> list[dict]:
    first = fetch(1)
    count = first.get("total_count")
    if type(count) is not int or count < 0:
        raise AuditError("Actions run total_count missing")
    if count > PAGE_SIZE * max_pages:
        raise AuditError("Too many runs; narrow the date window")
    all_runs = []
    page = 1
    while True:
        response = first if page == 1 else fetch(page)
        entries = response.get("workflow_runs")
        if not isinstance(entries, list):
            raise AuditError("Actions run page missing")
        if response.get("total_count") != count:
            raise AuditError("Actions changed during pagination")
        all_runs.extend(entries)
        if len(all_runs) >= count:
            break
        if not entries or page >= max_pages:
            raise AuditError("Actions run inventory incomplete")
        page += 1
    ids = [item.get("id") for item in all_runs]
    if len(all_runs) != count or any(type(x) is not int for x in ids):
        raise AuditError("Actions run inventory incomplete or invalid")
    if len(ids) != len(set(ids)):
        raise AuditError("Overlapping run pages")
    return all_runs


def summarize(repo: str, runs: list[dict]) -> dict:
    workflows = Counter(str(run.get("name") or "unnamed") for run in runs)
    events = Counter(str(run.get("event") or "unknown") for run in runs)
    outcomes = Counter(str(run.get("conclusion") or "incomplete") for run in runs)
    by_pr = Counter()
    unbound_pr = 0
    for run in runs:
        if run.get("event") != "pull_request":
            continue
        prs = run.get("pull_requests")
        if not isinstance(prs, list) or not prs:
            unbound_pr += 1
            continue
        for pr in prs:
            if isinstance(pr, dict) and type(pr.get("number")) is int:
                by_pr[(pr["number"], run.get("name") or "unnamed")] += 1
    repeated = [
        {"pr": number, "workflow": name, "runs": value}
        for (number, name), value in by_pr.items() if value > 1
    ]
    return {
        "repository": repo, "runs": len(runs),
        "events": dict(sorted(events.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "workflows": dict(sorted(workflows.items())),
        "repeatAttempts": sorted(
            repeated, key=lambda item: (-item["runs"], item["pr"], item["workflow"])
        )[:20],
        "unboundPrRuns": unbound_pr,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=iso_day, required=True)
    parser.add_argument("--end", type=iso_day, required=True)
    parser.add_argument("--repo", action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end must not precede --start")

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    names = args.repo or sorted(policy["repositories"])
    if any(name not in policy["repositories"] for name in names):
        print("Only policy-listed repositories can be queried", file=sys.stderr)
        return 2

    try:
        repos = [
            summarize(
                f"{policy['owner']}/{name}",
                collect_runs(lambda page, name=name: api_page(
                    policy["owner"], name, args.start.isoformat(),
                    args.end.isoformat(), page
                )),
            )
            for name in names
        ]
    except AuditError as exc:
        print(f"Actions audit unavailable: {exc}", file=sys.stderr)
        return 2

    report = {
        "start": args.start.isoformat(), "end": args.end.isoformat(),
        "unit": "workflow runs, not jobs or billable minutes",
        "totalRuns": sum(item["runs"] for item in repos), "repositories": repos,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"GitHub Actions {report['start']}..{report['end']}: {report['totalRuns']} runs")
        for item in repos:
            popular = sorted(item["workflows"].items(), key=lambda x: -x[1])[:3]
            print(item["repository"], item["runs"], popular)
        print("Run counts do not establish job counts or billable minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
