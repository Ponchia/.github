#!/usr/bin/env python3
"""Declarative, cautious GitHub governance for Ponchia-owned public repositories.

Read-only by default. The apply mode has an explicit owner gate and a tightly
limited set of operations. It never changes files, licenses, visibility,
existing branch-protection rules, CI definitions, release configuration,
secrets, or fork/private/archived repository settings.

Requires Python 3.10+ and an authenticated gh CLI. No third-party Python deps.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from sponsorships import EXPECTED_KO_FI_URL

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policy" / "repositories.json"
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
KNOWN_PROFILES = {"project", "shared-defaults", "profile"}
KNOWN_REQUIREMENTS = {
    "readme", "license", "securityPolicy", "contributingGuide",
    "dependabotConfig", "ciWorkflow", "requireDescription",
    "recommendAgentInstructions", "recommendTopics", "branchProtection",
    "requirePullRequest", "requireAdmins", "requireChecks",
    "secretScanning", "pushProtection", "vulnerabilityAlerts",
    "dependabotSecurityUpdates",
    "deleteBranchOnMerge", "sponsorButton",
}
AUTO_ACTIONS = {
    "security.vulnerability_alerts",
    "security.dependabot_updates",
    "settings.delete_merged_branches",
    "branch.initial_protection",
    "sponsor.button",
}


class PolicyError(RuntimeError):
    pass


class ApiError(PolicyError):
    def __init__(self, detail: str, status: int | None = None):
        self.status = status
        super().__init__(detail)


def read_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    obj = json.loads(path.read_text())
    if not isinstance(obj, dict) or obj.get("schemaVersion") != 1:
        raise PolicyError("Unsupported policy schema version")
    if obj.get("owner") != "Ponchia":
        raise PolicyError("Policy must be scoped to Ponchia")
    profiles = obj.get("profiles")
    repos = obj.get("repositories")
    if not isinstance(profiles, dict) or not isinstance(repos, dict):
        raise PolicyError("Missing profiles or repositories mapping")
    if set(profiles) != KNOWN_PROFILES:
        raise PolicyError("Unexpected or missing repository profiles")
    for key, values in profiles.items():
        if not isinstance(values, dict) or set(values) != KNOWN_REQUIREMENTS:
            raise PolicyError(f"Invalid requirements for profile {key}")
        if any(not isinstance(value, bool) for value in values.values()):
            raise PolicyError(f"Profile {key} must use booleans")
    for name, cfg in repos.items():
        if not NAME.fullmatch(name) or not isinstance(cfg, dict):
            raise PolicyError(f"Invalid repository name/config: {name}")
        if cfg.get("profile") not in profiles:
            raise PolicyError(f"Invalid profile for {name}")
        checks = cfg.get("requiredChecks", [])
        if not isinstance(checks, list) or any(not isinstance(c, str) or not c.strip() for c in checks):
            raise PolicyError(f"Invalid required checks for {name}")
        if len(checks) != len(set(checks)):
            raise PolicyError(f"Duplicate required check for {name}")
        if profiles[cfg["profile"]]["requireChecks"] and not checks:
            raise PolicyError(f"Required check contexts missing for {name}")
        waivers = cfg.get("waivers", {})
        if not isinstance(waivers, dict) or any(
            not isinstance(code, str) or not isinstance(reason, str) or len(reason.strip()) < 12
            for code, reason in waivers.items()
        ):
            raise PolicyError(f"Each waiver must give a meaningful reason for {name}")
    return obj


class GitHub:
    """Minimal gh CLI adapter; never shells out via a shell or prints credentials."""

    @staticmethod
    def _run(args: list[str], *, payload: Any | None = None) -> Any:
        try:
            response = subprocess.run(
                ["gh", *args],
                input=json.dumps(payload) if payload is not None else None,
                text=True, capture_output=True, timeout=35, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApiError(str(exc)) from exc
        if response.returncode:
            match = re.search(r"\bHTTP (\d{3})\b", response.stderr)
            status = int(match.group(1)) if match else None
            raise ApiError(response.stderr.strip() or "gh command failed", status)
        if not response.stdout.strip():
            return {}
        try:
            return json.loads(response.stdout)
        except json.JSONDecodeError as exc:
            raise ApiError("GitHub CLI returned invalid JSON") from exc

    def whoami(self) -> str:
        data = self._run(["api", "user"])
        return str(data.get("login", ""))

    def list_public(self, owner: str) -> list[str]:
        data = self._run([
            "repo", "list", owner, "--visibility", "public",
            "--limit", "1000", "--json", "nameWithOwner",
        ])
        if not isinstance(data, list) or len(data) >= 1000:
            raise ApiError("Repository inventory missing or truncated")
        return sorted(item["nameWithOwner"] for item in data)

    def get(self, path: str, *, not_found_ok: bool = False) -> Any:
        try:
            return self._run(["api", path])
        except ApiError as exc:
            if not_found_ok or exc.status == 404:
                if exc.status == 404:
                    return None
            raise

    def write(self, method: str, path: str, value: dict[str, Any] | None = None) -> Any:
        if method not in {"PUT", "PATCH"}:
            raise PolicyError("Unsupported write method")
        args = ["api", "-X", method, path]
        if value is not None:
            args += ["--input", "-"]
        return self._run(args, payload=value)

    def funding(self, owner: str, name: str) -> dict[str, Any]:
        query = """query($owner:String!,$name:String!) {
            repository(owner:$owner,name:$name) {
                id nameWithOwner isFork isArchived visibility
                hasSponsorshipsEnabled fundingLinks {platform url}
            }
        }"""
        answer = self._run([
            "api", "graphql", "-f", "query=" + query,
            "-f", "owner=" + owner, "-f", "name=" + name,
        ])
        if answer.get("errors"):
            raise ApiError(str(answer["errors"]))
        result = answer.get("data", {}).get("repository")
        if not isinstance(result, dict):
            raise ApiError("GitHub GraphQL repository missing")
        return result

    def verify_checks(self, full: str, branch: str, required: list[str]) -> list[dict[str, Any]]:
        """Only pin a status check observed as successful on this exact branch."""
        doc = self.get(f"repos/{full}/commits/{branch}/check-runs?per_page=100")
        runs = doc.get("check_runs", [])
        if doc.get("total_count", 0) > len(runs):
            raise PolicyError("Check run list was truncated; refusing protection setup")
        selected: list[dict[str, Any]] = []
        for check in required:
            matches = [
                r for r in runs if r.get("name") == check and
                r.get("status") == "completed" and
                r.get("conclusion") == "success" and
                isinstance((r.get("app") or {}).get("id"), int)
            ]
            if len(matches) != 1:
                raise PolicyError(
                    f"Required status check {check!r} is missing/ambiguous or "
                    f"not successful on {full}@{branch}"
                )
            selected.append({
                "context": check, "app_id": matches[0]["app"]["id"],
            })
        return selected


def _file_exists(paths: set[str], variants: tuple[str, ...]) -> bool:
    return any(name in paths for name in variants)


def snapshot(client: GitHub, full: str) -> dict[str, Any]:
    if not full.startswith("Ponchia/") or not NAME.fullmatch(full.removeprefix("Ponchia/")):
        raise PolicyError("Only Ponchia repositories with safe names may be inspected")
    name = full.split("/", 1)[1]
    repo = client.get(f"repos/{full}")
    if repo is None or (repo.get("owner") or {}).get("login", "").casefold() != "ponchia":
        raise PolicyError(f"Repository ownership could not be verified: {full}")
    if repo.get("private") or repo.get("visibility") != "public" or repo.get("fork") or repo.get("archived"):
        return {"repository": full, "repo": repo, "skipped": True}
    branch = repo["default_branch"]
    tree = client.get(f"repos/{full}/git/trees/{branch}?recursive=1")
    if tree is None or tree.get("truncated"):
        raise PolicyError(f"Tree for {full} missing or truncated")
    paths = {
        item["path"] for item in tree.get("tree", [])
        if item.get("type") == "blob"
    }
    protection = client.get(
        f"repos/{full}/branches/{branch}/protection",
        not_found_ok=True
    )
    rules = client.get(
        f"repos/{full}/rules/branches/{branch}", not_found_ok=True
    )
    if rules is None or not isinstance(rules, list):
        raise PolicyError(
            f"Cannot inspect effective branch rules for {full}; "
            "refusing to assume no protection"
        )
    # GitHub exposes vulnerability alerts through a dedicated REST endpoint:
    # 204 = enabled, 404 = disabled. It is a prerequisite for Dependabot fixes.
    vulnerability_alerts = client.get(
        f"repos/{full}/vulnerability-alerts", not_found_ok=True
    ) is not None
    funding = client.funding("Ponchia", name)
    if funding["nameWithOwner"].casefold() != full.casefold():
        raise PolicyError("Funding lookup returned a different repository")
    return {
        "repository": full,
        "repo": repo,
        "paths": paths,
        "protection": protection,
        "rules": rules,
        "funding": funding,
        "vulnerability_alerts": vulnerability_alerts,
        "skipped": False,
    }


def finding(code: str, actual: Any, expected: Any, *,
            severity: str = "error", action: str | None = None,
            detail: str = "") -> dict[str, Any]:
    return {
        "code": code, "severity": severity,
        "actual": actual, "expected": expected,
        "action": action, "detail": detail,
    }


def resolve_findings(
    state: dict[str, Any],
    cfg: dict[str, Any],
    req: dict[str, bool],
) -> list[dict[str, Any]]:
    if state["skipped"]:
        return []
    repo, files = state["repo"], state["paths"]
    branch, rules, funding = state["protection"], state["rules"], state["funding"]
    observed = []
    def require(code: str, actual: Any, expected: Any = True,
                *, severity: str = "error", action: str | None = None,
                detail: str = "") -> None:
        if actual != expected:
            observed.append(finding(
                code, actual, expected, severity=severity, action=action, detail=detail
            ))
    if req["requireDescription"]:
        require("metadata.description", bool(str(repo.get("description") or "").strip()))
    if req["readme"]:
        require("files.readme", _file_exists(files, ("README.md", ".github/README.md")))
    if req["license"]:
        require("files.license", any(
            f == "LICENSE" or f.startswith(("LICENSE.", "COPYING"))
            for f in files if "/" not in f
        ))
    if req["securityPolicy"]:
        require("files.security", _file_exists(files, ("SECURITY.md", ".github/SECURITY.md")))
    if req["contributingGuide"]:
        require("files.contributing", _file_exists(files, ("CONTRIBUTING.md", ".github/CONTRIBUTING.md")))
    if req["dependabotConfig"]:
        require("files.dependabot", _file_exists(files, (".github/dependabot.yml", ".github/dependabot.yaml")))
    if req["ciWorkflow"]:
        require("files.ci", any(
            f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))
            for f in files
        ))
    if req["recommendAgentInstructions"]:
        require("files.agents", "AGENTS.md" in files, severity="advisory",
                detail="Local instructions for coding agents are useful, but not required.")
    if req["recommendTopics"]:
        require("metadata.topics", bool(repo.get("topics")), severity="advisory")
    features = repo.get("security_and_analysis") or {}
    if req["secretScanning"]:
        value = (features.get("secret_scanning") or {}).get("status")
        require("security.secret_scanning", value, "enabled")
    if req["pushProtection"]:
        value = (features.get("secret_scanning_push_protection") or {}).get("status")
        require("security.push_protection", value, "enabled")
    if req["vulnerabilityAlerts"]:
        require(
            "security.vulnerability_alerts", state["vulnerability_alerts"], True,
            action="security.vulnerability_alerts"
            if state["vulnerability_alerts"] is False else None,
        )
    if req["dependabotSecurityUpdates"]:
        value = (features.get("dependabot_security_updates") or {}).get("status")
        require("security.dependabot_updates", value, "enabled",
                action="security.dependabot_updates" if value == "disabled" else None)
    if req["deleteBranchOnMerge"]:
        require(
            "settings.delete_merged_branches", repo.get("delete_branch_on_merge"),
            action="settings.delete_merged_branches"
            if repo.get("delete_branch_on_merge") is False else None,
        )

    if req["branchProtection"]:
        branch_rules = {r.get("type") for r in rules}
        if branch is None and not branch_rules:
            require(
                "branch.protection", False,
                action="branch.initial_protection",
                detail="Bootstrap only with explicitly declared successful CI contexts."
            )
        else:
            if req["requirePullRequest"]:
                via_branch = branch is not None and branch.get("required_pull_request_reviews") is not None
                require("branch.pull_request", via_branch or "pull_request" in branch_rules,
                        detail="Existing branch protection is never replaced automatically.")
            if req["requireAdmins"]:
                require(
                    "branch.enforce_admins",
                    (branch or {}).get("enforce_admins", {}).get("enabled") is True,
                    detail="A ruleset alone does not prove there is no bypass."
                )
            if req["requireChecks"]:
                configured = cfg.get("requiredChecks", [])
                actual = {
                    c.get("context") for c in
                    ((branch or {}).get("required_status_checks") or {}).get("checks", [])
                }
                # Older APIs may expose the contexts but no checks array.
                if not actual:
                    actual = set(
                        ((branch or {}).get("required_status_checks") or {}).get("contexts", [])
                    )
                rules_checks = [
                    r for r in rules if r.get("type") == "required_status_checks"
                ]
                if not actual and rules_checks:
                    # Rulesets have independent per-rule schemas. Do not
                    # infer missing checks merely because branch protection is absent.
                    pass
                else:
                    require(
                        "branch.required_checks",
                        sorted(actual), sorted(configured),
                        detail="Exact expected names are recorded in policy; verify before changing."
                    )
    if req["sponsorButton"]:
        links = funding.get("fundingLinks") or []
        good_link = any(
            link.get("platform") == "KO_FI" and
            str(link.get("url", "")).rstrip("/").casefold() == EXPECTED_KO_FI_URL.casefold()
            for link in links
        )
        require("sponsor.funding", good_link)
        require(
            "sponsor.button", funding.get("hasSponsorshipsEnabled"), True,
            action="sponsor.button" if good_link and funding.get("hasSponsorshipsEnabled") is False else None
        )
    waivers = cfg.get("waivers", {})
    for entry in observed:
        if entry["code"] in waivers:
            entry["severity"] = "waived"
            entry["action"] = None
            entry["detail"] = f"Policy exception: {waivers[entry['code']]}"
    return observed


def apply_supported(
    client: GitHub,
    state: dict[str, Any],
    cfg: dict[str, Any],
    found: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Narrow opt-in mutations. Existing protections and files are immutable."""
    if state["skipped"]:
        return [], []
    full = state["repository"]
    repo = state["repo"]
    branch = repo["default_branch"]
    actions = {
        item["action"] for item in found
        if item.get("action") in AUTO_ACTIONS and item["severity"] == "error"
    }
    applied: list[str] = []
    failures: list[str] = []

    def attempt(code: str, func) -> None:
        if code not in actions:
            return
        try:
            func()
            applied.append(code)
        except (PolicyError, ApiError) as exc:
            failures.append(f"{code}: {exc}")

    def enable_vulnerability_alerts() -> None:
        client.write("PUT", f"repos/{full}/vulnerability-alerts")
        if client.get(
            f"repos/{full}/vulnerability-alerts", not_found_ok=True
        ) is None:
            raise PolicyError("Vulnerability alerts were not confirmed as enabled")

    def enable_dependabot() -> None:
        if client.get(
            f"repos/{full}/vulnerability-alerts", not_found_ok=True
        ) is None:
            raise PolicyError(
                "Cannot enable Dependabot security fixes while "
                "vulnerability alerts are disabled"
            )
        client.write("PUT", f"repos/{full}/automated-security-fixes")
        check = client.get(f"repos/{full}")
        if (check.get("security_and_analysis") or {}).get(
            "dependabot_security_updates", {}
        ).get("status") != "enabled":
            raise PolicyError("Security updates were not confirmed as enabled")

    def delete_merged_branches() -> None:
        client.write("PATCH", f"repos/{full}", {"delete_branch_on_merge": True})
        check = client.get(f"repos/{full}")
        if check.get("delete_branch_on_merge") is not True:
            raise PolicyError("Merged branch deletion setting did not persist")

    def sponsor() -> None:
        current = client.funding("Ponchia", full.split("/", 1)[1])
        if current.get("isFork") or current.get("isArchived") or current.get("visibility") != "PUBLIC":
            raise PolicyError("Repository is no longer eligible for sponsorship")
        good = any(
            item.get("platform") == "KO_FI" and
            str(item.get("url", "")).rstrip("/").casefold() == EXPECTED_KO_FI_URL.casefold()
            for item in (current.get("fundingLinks") or [])
        )
        if not good:
            raise PolicyError("Ko-fi destination changed; refusing sponsorship")
        query = """mutation($id:ID!) {
          updateRepository(input: {repositoryId:$id, hasSponsorshipsEnabled:true}) {
            repository {nameWithOwner hasSponsorshipsEnabled}
          }
        }"""
        result = client._run([
            "api", "graphql", "-f", "query=" + query,
            "-f", "id=" + current["id"],
        ])
        changed = result.get("data", {}).get("updateRepository", {}).get("repository", {})
        if result.get("errors") or changed.get("hasSponsorshipsEnabled") is not True:
            raise PolicyError("GitHub did not confirm sponsorship activation")
        after = client.funding("Ponchia", full.split("/", 1)[1])
        if after.get("hasSponsorshipsEnabled") is not True:
            raise PolicyError("Sponsorship verification failed")

    def initialize_protection() -> None:
        # All checks are literal configuration values, never guessed.
        if state["protection"] is not None or state["rules"]:
            raise PolicyError("Existing protection/rules detected; refusing replacement")
        checks = cfg["requiredChecks"]
        if not checks:
            raise PolicyError("No explicit status checks configured")
        # Re-read current state immediately before a potentially disruptive write.
        latest = client.get(f"repos/{full}")
        if not latest or latest.get("private") or latest.get("fork") or latest.get("archived"):
            raise PolicyError("Repository visibility/ownership changed")
        if latest["default_branch"] != branch:
            raise PolicyError("Default branch changed during audit")
        protection_path = f"repos/{full}/branches/{branch}/protection"
        if client.get(protection_path, not_found_ok=True) is not None:
            raise PolicyError("Branch protection appeared during audit")
        active_rules = client.get(f"repos/{full}/rules/branches/{branch}", not_found_ok=True)
        if active_rules is None or active_rules:
            raise PolicyError("Branch rules changed or cannot be inspected")
        verified = client.verify_checks(full, branch, checks)
        # Do not weaken existing protections or impose invented required checks.
        client.write("PUT", protection_path, {
            "required_status_checks": {
                "strict": True, "checks": verified,
            },
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": False,
                "required_approving_review_count": 0,
            },
            "restrictions": None,
            "required_linear_history": True,
            "required_conversation_resolution": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "lock_branch": False,
        })
        after = client.get(protection_path)
        if not after:
            raise PolicyError("Protection was not readable after update")
        after_checks = (
            (after.get("required_status_checks") or {}).get("contexts") or []
        )
        if not after_checks:
            after_checks = [
                v.get("context") for v in
                (after.get("required_status_checks") or {}).get("checks", [])
            ]
        if not (
            after.get("enforce_admins", {}).get("enabled") is True
            and after.get("required_pull_request_reviews") is not None
            and set(checks) == set(after_checks)
            and after.get("allow_force_pushes", {}).get("enabled") is False
            and after.get("allow_deletions", {}).get("enabled") is False
        ):
            raise PolicyError("Branch protection verification was incomplete")

    attempt("security.vulnerability_alerts", enable_vulnerability_alerts)
    attempt("security.dependabot_updates", enable_dependabot)
    attempt("settings.delete_merged_branches", delete_merged_branches)
    attempt("sponsor.button", sponsor)
    attempt("branch.initial_protection", initialize_protection)
    return applied, failures


def audit(client: GitHub, policy: dict[str, Any], names: list[str],
          *, apply: bool = False) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    repo_configs = policy["repositories"]
    owner = policy["owner"]

    for full in names:
        item: dict[str, Any] = {"repository": full}
        try:
            prefix, _, name = full.partition("/")
            if prefix.casefold() != owner.casefold() or not NAME.fullmatch(name):
                raise PolicyError(f"Refusing repository outside {owner}")
            # Unknown forks are still skipped, not treated as owned projects.
            # Newly created original repositories are deliberately surfaced
            # for classification and never mutated automatically.
            if name not in repo_configs:
                metadata = client.get(f"repos/{full}")
                if metadata is None or (
                    (metadata.get("owner") or {}).get("login", "").casefold()
                    != owner.casefold()
                ):
                    raise PolicyError("Repository ownership could not be verified")
                if metadata.get("fork") or metadata.get("archived") or (
                    metadata.get("private") or metadata.get("visibility") != "public"
                ):
                    item["status"] = (
                        "skipped_fork" if metadata.get("fork") else
                        "skipped_archived" if metadata.get("archived") else
                        "skipped_private"
                    )
                    item["findings"] = []
                    records.append(item)
                    continue
                item["status"] = "unmanaged"
                item["findings"] = [finding(
                    "repository.unmanaged", False, True,
                    detail="Add an intentional profile and check contexts to policy."
                )]
                records.append(item)
                continue
            cfg = repo_configs[name]
            item["profile"] = cfg["profile"]
            req = policy["profiles"][cfg["profile"]]
            before = snapshot(client, full)
            if before["skipped"]:
                reason = (
                    "private" if before["repo"].get("private") else
                    "fork" if before["repo"].get("fork") else
                    "archived" if before["repo"].get("archived") else "nonpublic"
                )
                item.update(status=f"skipped_{reason}", findings=[])
                records.append(item)
                continue
            current_findings = resolve_findings(before, cfg, req)
            item["applied"] = []
            item["failures"] = []
            if apply:
                item["applied"], item["failures"] = apply_supported(
                    client, before, cfg, current_findings
                )
                after = snapshot(client, full)
                current_findings = resolve_findings(after, cfg, req)
            item["findings"] = current_findings
            item["status"] = (
                "error" if item["failures"] else
                "needs_attention" if any(
                    f["severity"] == "error" for f in current_findings
                ) else
                "advisory" if any(
                    f["severity"] == "advisory" for f in current_findings
                ) else "ready"
            )
            records.append(item)
        except (PolicyError, ApiError, KeyError, TypeError, ValueError) as exc:
            item.update(status="error", error=str(exc), findings=[])
            records.append(item)

    findings = [f for row in records for f in row.get("findings", [])]
    summary = {
        "repositories": len(records),
        "ready": sum(r["status"] == "ready" for r in records),
        "advisoryRepositories": sum(r["status"] == "advisory" for r in records),
        "attentionRepositories": sum(r["status"] == "needs_attention" for r in records),
        "skipped": sum(r["status"].startswith("skipped_") for r in records),
        "unmanaged": sum(r["status"] == "unmanaged" for r in records),
        "errors": sum(r["status"] == "error" for r in records),
        "driftFindings": sum(f["severity"] == "error" for f in findings),
        "advisories": sum(f["severity"] == "advisory" for f in findings),
        "waivers": sum(f["severity"] == "waived" for f in findings),
        "applied": sum(len(r.get("applied", [])) for r in records),
    }
    return {
        "schemaVersion": 1, "owner": owner,
        "mode": "apply" if apply else "audit",
        "summary": summary, "repositories": records,
    }


def main(argv: list[str] | None = None, client: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="Audit all public Ponchia repositories")
    selection.add_argument(
        "--repo", action="append", metavar="Ponchia/name",
        help="Audit one named repo (repeatable)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply only narrowly supported safe changes")
    parser.add_argument(
        "--confirm-owner", default=None, metavar="Ponchia",
        help="Required for account-wide apply; explicit safety gate",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable structured report")
    parser.add_argument("--validate-policy", action="store_true", help="Offline policy-schema validation")
    args = parser.parse_args(argv)
    try:
        policy = read_policy()
    except (PolicyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Invalid policy: {exc}", file=sys.stderr)
        return 2
    if args.validate_policy:
        print(f"Valid policy with {len(policy['repositories'])} managed repositories")
        return 0
    if not (args.all or args.repo):
        parser.error("Choose --all or --repo")
    if args.apply and args.all and args.confirm_owner != policy["owner"]:
        parser.error("Account-wide --apply requires --confirm-owner Ponchia")
    client = client or GitHub()
    if args.apply:
        try:
            identity = client.whoami()
        except ApiError as exc:
            print(f"Cannot verify GitHub identity: {exc}", file=sys.stderr)
            return 2
        if identity.casefold() != policy["owner"].casefold():
            print(
                f"Refusing mutations: active GitHub user {identity} is not {policy['owner']}",
                file=sys.stderr
            )
            return 2
    try:
        repos = client.list_public(policy["owner"]) if args.all else sorted(set(args.repo))
    except ApiError as exc:
        print(f"Inventory error: {exc}", file=sys.stderr)
        return 2
    report = audit(client, policy, repos, apply=args.apply)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Ponchia repository policy ({report['mode']})")
        for row in report["repositories"]:
            print(f"\n{row['repository']} [{row['status']}]")
            for changed in row.get("applied", []):
                print(f"  APPLIED: {changed}")
            for item in row.get("findings", []):
                print(
                    f"  {item['severity'].upper()}: {item['code']} "
                    f"(current={item['actual']!r}, expected={item['expected']!r})"
                    + (" [auto-fix available]" if item.get("action") else "")
                )
            for error in row.get("failures", []):
                print(f"  FAILURE: {error}")
            if row.get("error"):
                print(f"  ERROR: {row['error']}")
        print("\nSummary:", json.dumps(report["summary"]))
    return 1 if (
        report["summary"]["driftFindings"] or
        report["summary"]["errors"] or
        report["summary"]["unmanaged"]
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
