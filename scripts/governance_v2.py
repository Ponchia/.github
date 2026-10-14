#!/usr/bin/env python3
"""Reviewed plan/apply and change-only drift watch for Ponchia GitHub governance.

Read-only by default. A plan is bound to policy/code versions and observed
repository state. Applying requires its exact digest and fresh verification.
Scheduled watch only reads repository settings; it may create/update one issue
in Ponchia/.github when explicitly configured with --notify issue.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Any

import repository_policy as rp

OWNER = "Ponchia"
ROOT = pathlib.Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
STATE_DIR = pathlib.Path.home() / ".local" / "state" / "ponchia-governance"
PLAN_LIFETIME_HOURS = 24
MAX_WATCH_HISTORY = 40
REPO_URL = "https://github.com/Ponchia/.github"
ISSUE_TITLE = "Repository governance drift — Ponchia"


def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso(value: dt.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise rp.PolicyError("Missing timezone in plan timestamp")
    return result.astimezone(UTC)


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_hash(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    return {
        name: file_hash(ROOT / name)
        for name in (
            "policy/repositories.json",
            "scripts/repository_policy.py",
            "scripts/governance_v2.py",
        )
    }


def mkdir_secure(directory: pathlib.Path) -> None:
    # Never chmod pre-existing parents such as /tmp, /home or shared state.
    # Directories this tool creates are private; existing parents are left alone.
    if directory.exists():
        if not directory.is_dir():
            raise rp.PolicyError(f"Not a directory: {directory}")
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)


def write_json(path: pathlib.Path, value: Any, *, exclusive: bool = False) -> None:
    mkdir_secure(path.parent)
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return
    descriptor, tmp = tempfile.mkstemp(prefix=".atomic-", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text())


class ExclusiveLock:
    def __init__(self, state_dir: pathlib.Path):
        self.path = state_dir / ".lock"
        self.file: Any = None

    def __enter__(self):
        mkdir_secure(self.path.parent)
        self.file = open(self.path, "a+", encoding="utf-8")
        self.path.chmod(0o600)
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.file.close()
            raise
        return self

    def __exit__(self, *_):
        fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def eligible_snapshot(client: rp.GitHub, full: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = rp.snapshot(client, full)
    if state["skipped"]:
        raise rp.PolicyError(f"Refusing skipped repository: {full}")
    repo = state["repo"]
    branch = repo["default_branch"]
    branch_meta = client.get(f"repos/{full}/branches/{branch}")
    head = ((branch_meta or {}).get("commit") or {}).get("sha")
    if not isinstance(head, str) or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise rp.PolicyError(f"Cannot verify default-branch commit of {full}")
    security = repo.get("security_and_analysis") or {}
    protect = state["protection"] or {}
    required = protect.get("required_status_checks") or {}
    view = {
        "repository": full,
        "id": repo.get("id"),
        "visibility": repo.get("visibility"),
        "fork": repo.get("fork"),
        "archived": repo.get("archived"),
        "branch": branch,
        "branchHead": head,
        "description": repo.get("description"),
        "topics": sorted(repo.get("topics") or []),
        "filesSha256": digest(sorted(state["paths"])),
        "security": {
            key: (security.get(key) or {}).get("status")
            for key in (
                "secret_scanning", "secret_scanning_push_protection",
                "dependabot_security_updates"
            )
        },
        "vulnerabilityAlerts": state["vulnerability_alerts"],
        "deleteBranchOnMerge": repo.get("delete_branch_on_merge"),
        "protection": {
            "exists": state["protection"] is not None,
            "requiredChecks": sorted(required.get("contexts") or []),
            "checkDefinitions": sorted(
                [dict(context=c.get("context"), app_id=c.get("app_id")) for c in
                 (required.get("checks") or [])],
                key=lambda c: (str(c["context"]), str(c["app_id"])),
            ),
            "pullRequest": protect.get("required_pull_request_reviews") is not None,
            "enforceAdmins": (protect.get("enforce_admins") or {}).get("enabled"),
            "forcePushes": (protect.get("allow_force_pushes") or {}).get("enabled"),
            "deletions": (protect.get("allow_deletions") or {}).get("enabled"),
        },
        "rulesSha256": digest(state["rules"]),
        "funding": {
            "enabled": state["funding"]["hasSponsorshipsEnabled"],
            "links": sorted(
                state["funding"].get("fundingLinks") or [],
                key=lambda x: (str(x.get("platform")), str(x.get("url"))),
            ),
        },
    }
    if not isinstance(view["id"], int):
        raise rp.PolicyError(f"Missing stable numeric repository ID for {full}")
    return state, view


def actions_from(findings: list[dict[str, Any]]) -> list[str]:
    return sorted({
        f["action"] for f in findings
        if f.get("action") in rp.AUTO_ACTIONS and f.get("severity") == "error"
    })


def make_plan(
    client: rp.GitHub,
    names: list[str],
    policy: dict[str, Any],
    *,
    all_repositories: bool = False,
    clock: dt.datetime | None = None,
) -> dict[str, Any]:
    names = sorted(set(names))
    report = rp.audit(client, policy, names, apply=False)
    if report["summary"]["errors"]:
        raise rp.PolicyError("Live audit contains errors; cannot create a reliable plan")
    entries = []
    for row in report["repositories"]:
        actions = actions_from(row.get("findings", []))
        if not actions:
            continue
        full = row["repository"]
        state, observed = eligible_snapshot(client, full)
        name = full.split("/", 1)[1]
        cfg = policy["repositories"][name]
        current = rp.resolve_findings(
            state, cfg, policy["profiles"][cfg["profile"]]
        )
        if actions_from(current) != actions:
            raise rp.PolicyError(f"Repository changed during planning: {full}")
        entries.append({
            "repository": full,
            "profile": cfg["profile"],
            "actions": actions,
            "precondition": observed,
            "preconditionSha256": digest(observed),
        })
    timestamp = clock or now()
    data = {
        "schemaVersion": 2,
        "kind": "ponchia-governance-plan",
        "owner": OWNER,
        "createdAt": iso(timestamp),
        "expiresAt": iso(timestamp + dt.timedelta(hours=PLAN_LIFETIME_HOURS)),
        "scope": "all" if all_repositories else "explicit",
        "inventory": names,
        "sources": source_hashes(),
        "audit": report,
        "changes": entries,
    }
    data["planSha256"] = digest(data)
    return data


def validate_plan(plan: dict[str, Any], *, clock: dt.datetime | None = None) -> None:
    if plan.get("schemaVersion") != 2 or plan.get("kind") != "ponchia-governance-plan":
        raise rp.PolicyError("Unrecognized plan document")
    if plan.get("owner") != OWNER:
        raise rp.PolicyError("Wrong plan owner")
    hash_value = plan.get("planSha256")
    raw = {k: v for k, v in plan.items() if k != "planSha256"}
    if hash_value != digest(raw):
        raise rp.PolicyError("Plan digest does not match its contents")
    instant = clock or now()
    created = parse_time(plan["createdAt"])
    if created > instant + dt.timedelta(minutes=2):
        raise rp.PolicyError("Plan timestamp is in the future")
    if instant >= parse_time(plan["expiresAt"]):
        raise rp.PolicyError("Plan expired; generate a new live plan")
    if plan.get("sources") != source_hashes():
        raise rp.PolicyError("Policy or implementation changed; regenerate the plan")
    if plan.get("inventory") != sorted(set(plan["inventory"])):
        raise rp.PolicyError("Plan inventory is not canonical")
    for row in plan.get("changes", []):
        full = row.get("repository", "")
        if (not isinstance(full, str) or not full.startswith(OWNER + "/")
                or not rp.NAME.fullmatch(full.split("/", 1)[1])):
            raise rp.PolicyError("Invalid repository in plan")
        if row.get("actions") != sorted(set(row["actions"])):
            raise rp.PolicyError("Noncanonical actions")
        if any(action not in rp.AUTO_ACTIONS for action in row["actions"]):
            raise rp.PolicyError("Plan contains unsupported action")
        if row.get("preconditionSha256") != digest(row["precondition"]):
            raise rp.PolicyError("Plan state fingerprint is invalid")
    if len({x["repository"] for x in plan["changes"]}) != len(plan["changes"]):
        raise rp.PolicyError("Duplicate repository in plan")


def apply_plan(
    client: rp.GitHub,
    plan: dict[str, Any],
    *,
    approve: str,
    state_dir: pathlib.Path,
    clock: dt.datetime | None = None,
) -> dict[str, Any]:
    validate_plan(plan, clock=clock)
    if approve != plan["planSha256"]:
        raise rp.PolicyError("Explicit approval must equal the reviewed planSha256")
    if not plan["changes"]:
        raise rp.PolicyError("Plan contains no applicable changes")
    if client.whoami().casefold() != OWNER.casefold():
        raise rp.PolicyError("Authenticated GitHub account is not Ponchia")

    policy = rp.read_policy()
    with ExclusiveLock(state_dir):
        receipt_path = state_dir / "receipts" / (plan["planSha256"] + ".json")
        if receipt_path.exists():
            raise rp.PolicyError("Plan has already been attempted; never replay a write receipt")

        if plan["scope"] == "all" and client.list_public(OWNER) != plan["inventory"]:
            raise rp.PolicyError("Repository inventory changed; regenerate the plan")
        live_states = []
        # Validate ALL target preconditions before the first change.
        for entry in plan["changes"]:
            name = entry["repository"].split("/", 1)[1]
            cfg = policy["repositories"].get(name)
            if not cfg or cfg["profile"] != entry["profile"]:
                raise rp.PolicyError(f"Repository policy profile changed: {name}")
            state, view = eligible_snapshot(client, entry["repository"])
            if digest(view) != entry["preconditionSha256"]:
                raise rp.PolicyError(
                    f"Stale GitHub settings or branch head for {entry['repository']}; regenerate plan"
                )
            current = rp.resolve_findings(
                state, cfg, policy["profiles"][cfg["profile"]]
            )
            if actions_from(current) != entry["actions"]:
                raise rp.PolicyError(f"Live required actions changed for {name}")
            live_states.append((entry, cfg, state, current))
        receipt = {
            "schemaVersion": 1,
            "planSha256": plan["planSha256"],
            "startedAt": iso(clock or now()),
            "status": "started",
            "executed": [],
        }
        # Exclusive create acts as a one-use/idempotency boundary.
        write_json(receipt_path, receipt, exclusive=True)
        for entry, cfg, state, current in live_states:
            row = {"repository": entry["repository"], "planned": entry["actions"]}
            try:
                applied, failures = rp.apply_supported(client, state, cfg, current)
                row["applied"], row["failures"] = applied, failures
                if set(applied) != set(entry["actions"]) or failures:
                    raise rp.PolicyError(f"Partial or failed application for {entry['repository']}: {failures}")
                after, observed = eligible_snapshot(client, entry["repository"])
                row["postconditionSha256"] = digest(observed)
                row["remaining"] = rp.resolve_findings(
                    after, cfg, policy["profiles"][cfg["profile"]]
                )
                if any(a in actions_from(row["remaining"]) for a in entry["actions"]):
                    raise rp.PolicyError(f"Planned correction did not persist for {entry['repository']}")
                row["status"] = "verified"
            except (rp.PolicyError, rp.ApiError, KeyError, ValueError) as exc:
                row["status"] = "failed"
                row["error"] = str(exc)
                receipt["executed"].append(row)
                receipt["status"] = "failed"
                receipt["finishedAt"] = iso(now())
                write_json(receipt_path, receipt)
                raise rp.PolicyError(
                    f"Apply stopped; inspect receipt {receipt_path}: {exc}"
                ) from exc
            receipt["executed"].append(row)
            write_json(receipt_path, receipt)
        receipt["status"] = "completed"
        receipt["finishedAt"] = iso(now())
        write_json(receipt_path, receipt)
        return {"status": "completed", "receipt": str(receipt_path),
                "planSha256": plan["planSha256"], "executed": receipt["executed"]}


def noteworthy(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Only actionable changes: errors, unmanaged repositories and policy drift."""
    items = []
    for row in report.get("repositories", []):
        full = row["repository"]
        if row["status"] == "error":
            items.append({"repository": full, "code": "audit.error",
                          "detail": str(row.get("error", "Unable to audit"))[:300]})
        elif row["status"] == "unmanaged":
            items.append({"repository": full, "code": "repository.unmanaged"})
        for finding in row.get("findings", []):
            if finding.get("severity") != "error":
                continue
            # An unregistered repo already has an unmanaged status. The
            # policy engine also emits repository.unmanaged as a finding;
            # report it once rather than notifying twice for one event.
            if row["status"] == "unmanaged" and finding["code"] == "repository.unmanaged":
                continue
            items.append({
                "repository": full,
                "code": finding["code"],
                "actual": finding.get("actual"),
                "expected": finding.get("expected"),
            })
    return sorted(items, key=lambda x: (x["repository"], x["code"], canonical(x)))


def issue_body(findings: list[dict[str, Any]], evidence: str) -> str:
    lines = [
        "## Ponchia GitHub governance drift",
        "",
        "An authenticated, read-only settings audit found the following changes.",
        "No repository settings have been modified by this scheduled job.",
        "",
        f"Evidence SHA-256: {evidence}",
        "",
    ]
    for row in findings[:50]:
        lines.append(f"- **{row['repository']}** — {row['code']}")
    if len(findings) > 50:
        lines.append(f"- ...and {len(findings) - 50} more findings")
    lines.extend([
        "",
        "Review the [repository policy]("
        "https://github.com/Ponchia/.github/blob/main/policy/repositories.json"
        ") and run governance_v2.py plan --all on the authenticated devbox "
        "for a fresh reviewable change plan.",
        "",
        "This issue changes only when meaningful findings change. "
        "Detailed evidence is retained locally on the devbox.",
    ])
    return "\n".join(lines)


class IssueNotifier:
    """Only GitHub issue writes in Ponchia/.github; no configuration mutations."""

    def __init__(self, client: rp.GitHub):
        self.client = client

    def _call(self, method: str, path: str, payload: dict[str, Any]) -> Any:
        return self.client._run(
            ["api", "-X", method, path, "--input", "-"], payload=payload
        )

    def issue(self, number: int) -> dict[str, Any] | None:
        return self.client.get(f"repos/Ponchia/.github/issues/{number}",
                               not_found_ok=True)

    def create(self, body: str) -> int:
        result = self._call(
            "POST", "repos/Ponchia/.github/issues",
            {"title": ISSUE_TITLE, "body": body, "assignees": [OWNER]},
        )
        value = result.get("number")
        if not isinstance(value, int):
            raise rp.PolicyError("Could not verify GitHub governance issue creation")
        return value

    def comment(self, number: int, body: str) -> None:
        result = self._call(
            "POST", f"repos/Ponchia/.github/issues/{number}/comments",
            {"body": body},
        )
        if not isinstance(result.get("id"), int):
            raise rp.PolicyError("Could not verify GitHub issue comment")

    def close(self, number: int) -> None:
        result = self._call(
            "PATCH", f"repos/Ponchia/.github/issues/{number}",
            {"state": "closed", "state_reason": "completed"},
        )
        if result.get("state") != "closed":
            raise rp.PolicyError("Could not verify resolution of governance issue")


def prune_history(folder: pathlib.Path) -> None:
    logs = sorted(folder.glob("audit-*.json"))
    for old in logs[:-MAX_WATCH_HISTORY]:
        old.unlink()


def watch_once(
    client: rp.GitHub,
    policy: dict[str, Any],
    *,
    state_dir: pathlib.Path,
    notify: bool = False,
    notifier: IssueNotifier | None = None,
    clock: dt.datetime | None = None,
) -> dict[str, Any]:
    """A read-only repository audit with optional change-only issue messages."""
    instant = clock or now()
    mkdir_secure(state_dir)
    with ExclusiveLock(state_dir):
        names = client.list_public(OWNER)
        report = rp.audit(client, policy, names, apply=False)
        current = noteworthy(report)
        fingerprint = digest(current)
        audit_evidence = {
            "schemaVersion": 1,
            "observedAt": iso(instant),
            "owner": OWNER,
            "sources": source_hashes(),
            "audit": report,
            "noteworthy": current,
            "noteworthySha256": fingerprint,
        }
        audit_evidence["evidenceSha256"] = digest(audit_evidence)
        snapshot_file = state_dir / "snapshots" / (
            "audit-" + instant.strftime("%Y%m%dT%H%M%SZ") +
            "-" + audit_evidence["evidenceSha256"][:10] + ".json"
        )
        write_json(snapshot_file, audit_evidence, exclusive=True)
        prune_history(state_dir / "snapshots")

        state_path = state_dir / "watch-state.json"
        previous = load_json(state_path) if state_path.exists() else {}
        changed = previous.get("noteworthySha256") != fingerprint
        # Observing without notification must not silently acknowledge a
        # drift condition: keep the notification cursor independent.
        notify_changed = previous.get("lastNotifiedSha256") != fingerprint
        issue_number = previous.get("issueNumber")
        notified = False
        result = {
            "status": "drift" if current else "clean",
            "changed": changed,
            "findings": len(current),
            "evidence": str(snapshot_file),
            "evidenceSha256": audit_evidence["evidenceSha256"],
            "notification": "disabled" if not notify else "unchanged",
        }

        if notify and notify_changed:
            if client.whoami().casefold() != OWNER.casefold():
                raise rp.PolicyError("GitHub notification writes require Ponchia identity")
            notifier = notifier or IssueNotifier(client)
            if current:
                body = issue_body(current, audit_evidence["evidenceSha256"])
                prior_issue = notifier.issue(issue_number) if issue_number else None
                if prior_issue and prior_issue.get("state") == "open":
                    notifier.comment(issue_number, body)
                else:
                    issue_number = notifier.create(body)
                notified = True
                result["notification"] = "drift_reported"
            else:
                prior_issue = notifier.issue(issue_number) if issue_number else None
                if prior_issue and prior_issue.get("state") == "open":
                    notifier.comment(
                        issue_number,
                        "Governance drift resolved. The latest read-only audit is clean. "
                        f"Evidence SHA-256: {audit_evidence['evidenceSha256']}",
                    )
                    notifier.close(issue_number)
                    notified = True
                    result["notification"] = "resolution_reported"
                else:
                    result["notification"] = "clean_baseline"
        elif notify and not previous:
            result["notification"] = "clean_baseline" if not current else "unchanged"

        # Advance comparison state only after successful notification.
        write_json(state_path, {
            "schemaVersion": 1,
            "noteworthySha256": fingerprint,
            "lastNotifiedSha256": (
                fingerprint if notify and notify_changed
                else previous.get("lastNotifiedSha256")
            ),
            "issueNumber": issue_number,
            "lastAudit": iso(instant),
            "lastEvidenceSha256": audit_evidence["evidenceSha256"],
            "lastNotified": iso(instant) if notified else previous.get("lastNotified"),
        })
        result["issueUrl"] = (
            f"{REPO_URL}/issues/{issue_number}" if issue_number else None
        )
        return result


def main(argv: list[str] | None = None, client: rp.GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    plan_cmd = subs.add_parser("plan", help="Create a reviewable immutable change plan")
    plan_scope = plan_cmd.add_mutually_exclusive_group(required=True)
    plan_scope.add_argument("--all", action="store_true")
    plan_scope.add_argument("--repo", action="append", metavar="Ponchia/name")
    plan_cmd.add_argument("--out", type=pathlib.Path, help="Plan JSON output file")

    apply_cmd = subs.add_parser("apply", help="Execute one fresh, explicitly approved plan")
    apply_cmd.add_argument("--plan", type=pathlib.Path, required=True)
    apply_cmd.add_argument("--approve", required=True, metavar="SHA256")
    apply_cmd.add_argument("--state-dir", type=pathlib.Path, default=STATE_DIR)

    watch_cmd = subs.add_parser("watch", help="Read-only full audit and change-only notifications")
    watch_cmd.add_argument(
        "--notify", choices=("none", "issue"), default="none",
        help="Only 'issue' may write to a single issue in Ponchia/.github",
    )
    watch_cmd.add_argument("--state-dir", type=pathlib.Path, default=STATE_DIR)

    args = parser.parse_args(argv)
    client = client or rp.GitHub()
    try:
        policy = rp.read_policy()
        if args.command == "plan":
            names = client.list_public(OWNER) if args.all else args.repo
            data = make_plan(client, names, policy, all_repositories=args.all)
            output = args.out or (
                STATE_DIR / "plans" / (
                    "plan-" + data["createdAt"].replace(":", "").replace("-", "") +
                    "-" + data["planSha256"][:12] + ".json"
                )
            )
            write_json(output, data, exclusive=True)
            print(json.dumps({
                "status": "created", "plan": str(output),
                "planSha256": data["planSha256"],
                "expiresAt": data["expiresAt"],
                "changes": data["changes"],
                "auditSummary": data["audit"]["summary"],
            }, indent=2))
            return 0
        if args.command == "apply":
            data = load_json(args.plan)
            outcome = apply_plan(client, data, approve=args.approve,
                                 state_dir=args.state_dir)
            print(json.dumps(outcome, indent=2))
            return 0
        if args.command == "watch":
            outcome = watch_once(
                client, policy, state_dir=args.state_dir,
                notify=args.notify == "issue",
            )
            print(json.dumps(outcome, indent=2))
            return 0
    except (rp.PolicyError, rp.ApiError, ValueError, OSError, KeyError,
            TypeError, json.JSONDecodeError, BlockingIOError) as exc:
        print(f"Governance refused: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("Unhandled command")


if __name__ == "__main__":
    sys.exit(main())
