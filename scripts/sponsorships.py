#!/usr/bin/env python3
"""Audit and opt-in GitHub Sponsor buttons for Ponchia's own public repositories.

Requirements: Python 3.10+ and an authenticated GitHub CLI (gh).
Read-only by default; --apply only toggles hasSponsorshipsEnabled after verifying
the repository is public, not a fork/archived, and resolves Ponchia's Ko-fi link.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

OWNER = "Ponchia"
EXPECTED_KO_FI_URL = "https://ko-fi.com/ponchia"

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id
    nameWithOwner
    visibility
    isFork
    isArchived
    hasSponsorshipsEnabled
    fundingLinks { platform url }
  }
}
"""

ENABLE_MUTATION = """
mutation($id: ID!) {
  updateRepository(input: {
    repositoryId: $id
    hasSponsorshipsEnabled: true
  }) {
    repository { nameWithOwner hasSponsorshipsEnabled }
  }
}
"""

PROBLEM_STATUSES = {
    "needs_activation",
    "missing_funding",
    "verification_failed",
    "error",
}


class GitHubError(RuntimeError):
    pass


class GitHub:
    def _run(self, *args: str) -> Any:
        try:
            process = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=40,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError(str(exc)) from exc
        if process.returncode:
            raise GitHubError(process.stderr.strip() or "gh returned a failure")
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("GitHub CLI did not return JSON") from exc

    def public_repositories(self) -> list[str]:
        data = self._run(
            "repo", "list", OWNER, "--visibility", "public",
            "--limit", "1000", "--json", "nameWithOwner",
        )
        if not isinstance(data, list):
            raise GitHubError("Unexpected repository-list response")
        return sorted(item["nameWithOwner"] for item in data)

    def repository(self, full_name: str) -> dict[str, Any]:
        owner, name = full_name.split("/", 1)
        response = self._run(
            "api", "graphql",
            "-f", f"query={REPO_QUERY}",
            "-f", f"owner={owner}",
            "-f", f"name={name}",
        )
        errors = response.get("errors")
        if errors:
            raise GitHubError(str(errors))
        repo = response.get("data", {}).get("repository")
        if not repo:
            raise GitHubError(f"Repository not found: {full_name}")
        return repo

    def enable_sponsorship(self, node_id: str) -> None:
        response = self._run(
            "api", "graphql",
            "-f", f"query={ENABLE_MUTATION}",
            "-f", f"id={node_id}",
        )
        if response.get("errors"):
            raise GitHubError(str(response["errors"]))
        updated = (
            response.get("data", {})
            .get("updateRepository", {})
            .get("repository", {})
        )
        if not updated.get("hasSponsorshipsEnabled"):
            raise GitHubError("GitHub did not confirm Sponsorships activation")


def has_expected_funding(repo: dict[str, Any]) -> bool:
    return any(
        link.get("platform") == "KO_FI"
        and str(link.get("url", "")).rstrip("/").casefold()
        == EXPECTED_KO_FI_URL.casefold()
        for link in (repo.get("fundingLinks") or [])
    )


def audit_one(
    client: GitHub, full_name: str, *, apply: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {"repository": full_name}
    owner, sep, name = full_name.partition("/")
    if not sep or not name or owner.casefold() != OWNER.casefold():
        result["status"] = "skipped_owner"
        return result

    try:
        repo = client.repository(full_name)
        result["visibility"] = repo["visibility"]
        result["fork"] = repo["isFork"]
        result["archived"] = repo["isArchived"]
        result["sponsorshipEnabled"] = repo["hasSponsorshipsEnabled"]
        result["expectedFunding"] = has_expected_funding(repo)

        if name == ".github":
            result["status"] = "skipped_defaults_repository"
        elif repo["isFork"]:
            result["status"] = "skipped_fork"
        elif repo["isArchived"]:
            result["status"] = "skipped_archived"
        elif repo["visibility"] != "PUBLIC":
            result["status"] = "skipped_private"
        elif not result["expectedFunding"]:
            result["status"] = "missing_funding"
        elif repo["hasSponsorshipsEnabled"]:
            result["status"] = "ready"
        elif not apply:
            result["status"] = "needs_activation"
        else:
            client.enable_sponsorship(repo["id"])
            verified = client.repository(full_name)
            result["sponsorshipEnabled"] = verified["hasSponsorshipsEnabled"]
            result["expectedFunding"] = has_expected_funding(verified)
            result["status"] = (
                "enabled"
                if result["sponsorshipEnabled"] and result["expectedFunding"]
                else "verification_failed"
            )
    except GitHubError as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    return result


def main(argv: list[str] | None = None, client: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repositories", nargs="*", metavar="Ponchia/repository",
        help="One or more explicit repositories (same-owner only)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Audit all public repositories owned by Ponchia, skipping forks",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Enable Sponsor buttons when the expected Ko-fi link is confirmed",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON, for agents and checks",
    )
    args = parser.parse_args(argv)

    if args.all == bool(args.repositories):
        parser.error("Specify either --all or one or more repositories")

    client = client or GitHub()
    try:
        names = (
            client.public_repositories()
            if args.all else list(dict.fromkeys(args.repositories))
        )
    except GitHubError as exc:
        print(f"GitHub error: {exc}", file=sys.stderr)
        return 2

    results = [audit_one(client, name, apply=args.apply) for name in names]
    issues = sum(item["status"] in PROBLEM_STATUSES for item in results)
    summary = {
        "total": len(results),
        "ready": sum(item["status"] == "ready" for item in results),
        "enabled": sum(item["status"] == "enabled" for item in results),
        "skipped": sum(item["status"].startswith("skipped_") for item in results),
        "issues": issues,
    }

    if args.json:
        print(json.dumps({
            "schemaVersion": 1,
            "owner": OWNER,
            "mode": "apply" if args.apply else "audit",
            "repositories": results,
            "summary": summary,
        }, indent=2))
    else:
        print(f"Ponchia sponsorships ({'apply' if args.apply else 'audit'})")
        for item in results:
            details = f" — {item['error']}" if item.get("error") else ""
            print(f"  {item['repository']:<39} {item['status']}{details}")
        print(
            f"Results: {summary['ready']} ready, {summary['enabled']} enabled, "
            f"{summary['skipped']} skipped, {issues} need attention"
        )

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
