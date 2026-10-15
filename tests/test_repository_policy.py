"""Offline governance tests. Fake API only: no GitHub account changes."""

from __future__ import annotations

import contextlib
import copy
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import repository_policy as policy


BASE_FILES = {
    "README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md",
    ".github/dependabot.yml", ".github/FUNDING.yml",
    ".github/workflows/ci.yml", "AGENTS.md",
}


def state(
    name="bronto-layout", *, protected=True, pr=True,
    sponsor=True, funding=True,
):
    checks = policy.read_policy()["repositories"][name]["requiredChecks"]
    branch = {
        "required_status_checks": {
            "contexts": checks,
            "checks": [{"context": c, "app_id": 15368} for c in checks],
        },
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": (
            {"required_approving_review_count": 0} if pr else None
        ),
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    } if protected else None
    return {
        "repository": f"Ponchia/{name}",
        "repo": {
            "owner": {"login": "Ponchia"}, "full_name": f"Ponchia/{name}",
            "name": name, "private": False, "visibility": "public",
            "fork": False, "archived": False, "default_branch": "main",
            "description": "Helpful open source library", "topics": ["developer-tools"],
            "delete_branch_on_merge": True,
            "security_and_analysis": {
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_push_protection": {"status": "enabled"},
                "dependabot_security_updates": {"status": "enabled"},
            },
        },
        "paths": set(BASE_FILES),
        "protection": branch,
        "rules": [],
        "vulnerability_alerts": True,
        "funding": {
            "id": "R_dummy", "nameWithOwner": f"Ponchia/{name}",
            "isFork": False, "isArchived": False, "visibility": "PUBLIC",
            "hasSponsorshipsEnabled": sponsor,
            "fundingLinks": (
                [{"platform": "KO_FI", "url": "https://ko-fi.com/ponchia"}]
                if funding else []
            ),
        },
        "skipped": False,
    }


class FakeGitHub:
    verify_checks = policy.GitHub.verify_checks

    def __init__(self, item):
        self.state = copy.deepcopy(item)
        self.writes = []
        self.identity = "Ponchia"
        self.checks_ok = True
        self.rule_failure = False

    def whoami(self):
        return self.identity

    def list_public(self, owner):
        return [self.state["repository"]]

    def get(self, path, *, not_found_ok=False):
        full = self.state["repository"]
        if path == f"repos/{full}":
            return self.state["repo"]
        if "/git/trees/" in path:
            return {
                "tree": [{"path": name, "type": "blob"} for name in self.state["paths"]],
                "truncated": False,
            }
        if path.endswith("/vulnerability-alerts"):
            return {} if self.state["vulnerability_alerts"] else None
        if "/rules/branches/" in path:
            return None if self.rule_failure else self.state["rules"]
        if "/branches/" in path and path.endswith("/protection"):
            return self.state["protection"]
        if "/commits/" in path and path.endswith("/check-runs?per_page=100"):
            checks = policy.read_policy()["repositories"][
                full.split("/", 1)[1]
            ]["requiredChecks"]
            if not self.checks_ok:
                checks = ["unrelated-check"]
            return {
                "total_count": len(checks),
                "check_runs": [
                    {
                        "name": name, "status": "completed", "conclusion": "success",
                        "app": {"id": 15368},
                    } for name in checks
                ],
            }
        raise AssertionError(f"Unexpected GET request: {path}")

    def funding(self, owner, name):
        return copy.deepcopy(self.state["funding"])

    def _run(self, args, *, payload=None):
        if "graphql" not in args:
            raise AssertionError("Unexpected mutation")
        self.state["funding"]["hasSponsorshipsEnabled"] = True
        return {"data": {"updateRepository": {"repository": {
            "nameWithOwner": self.state["repository"],
            "hasSponsorshipsEnabled": True,
        }}}}

    def write(self, method, path, value=None):
        self.writes.append((method, path, value))
        if path.endswith("/vulnerability-alerts"):
            self.state["vulnerability_alerts"] = True
        elif path.endswith("/automated-security-fixes"):
            if not self.state["vulnerability_alerts"]:
                raise policy.ApiError("Vulnerability alerts must be enabled", 422)
            self.state["repo"]["security_and_analysis"][
                "dependabot_security_updates"
            ]["status"] = "enabled"
        elif method == "PATCH" and path == "repos/" + self.state["repository"]:
            if value != {"delete_branch_on_merge": True}:
                raise AssertionError("Unexpected repository payload")
            self.state["repo"]["delete_branch_on_merge"] = True
        elif method == "PUT" and path.endswith("/protection"):
            self.state["protection"] = {
                "required_status_checks": {
                    "contexts": [
                        c["context"] for c in value["required_status_checks"]["checks"]
                    ],
                },
                "enforce_admins": {"enabled": value["enforce_admins"]},
                "required_pull_request_reviews": value["required_pull_request_reviews"],
                "allow_force_pushes": {"enabled": value["allow_force_pushes"]},
                "allow_deletions": {"enabled": value["allow_deletions"]},
            }
        else:
            raise AssertionError(f"Unexpected write: {method} {path}")
        return {}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = policy.read_policy()
        self.cfg = self.policy["repositories"]["bronto-layout"]
        self.req = self.policy["profiles"]["project"]

    def findings(self, item, cfg=None):
        return policy.resolve_findings(item, cfg or self.cfg, self.req)

    def test_schema(self):
        self.assertEqual(self.policy["owner"], "Ponchia")
        self.assertEqual(len(self.policy["repositories"]), 10)
        self.assertIn("bronto-pulse", self.policy["repositories"])
        self.assertIn("bronto-visual-models", self.policy["repositories"])

    def test_baseline_compliant(self):
        self.assertEqual(self.findings(state()), [])

    def test_missing_branch_protection_action(self):
        issues = self.findings(state(protected=False))
        self.assertEqual([(f["code"], f["action"]) for f in issues],
                         [("branch.protection", "branch.initial_protection")])

    def test_existing_rules_are_not_overwritten(self):
        item = state(protected=False)
        item["rules"] = [{"type": "pull_request"}]
        findings = self.findings(item)
        self.assertFalse(any(f.get("action") == "branch.initial_protection" for f in findings))

    def test_existing_protection_without_pr_is_reported_not_changed(self):
        issues = self.findings(state(pr=False))
        self.assertEqual(issues[0]["code"], "branch.pull_request")
        self.assertIsNone(issues[0]["action"])

    def test_required_context_drift_detected(self):
        item = state()
        item["protection"]["required_status_checks"]["checks"] = [
            {"context": "obsolete"}
        ]
        self.assertIn("branch.required_checks", [f["code"] for f in self.findings(item)])

    def test_sponsorship_requires_right_destination(self):
        issues = self.findings(state(sponsor=False, funding=False))
        codes = {f["code"]: f for f in issues}
        self.assertIn("sponsor.funding", codes)
        self.assertIsNone(codes["sponsor.button"]["action"])

    def test_safe_settings_applied_idempotently(self):
        item = state()
        item["repo"]["delete_branch_on_merge"] = False
        item["repo"]["security_and_analysis"]["dependabot_security_updates"][
            "status"
        ] = "disabled"
        fake = FakeGitHub(item)
        actions, failures = policy.apply_supported(fake, item, self.cfg, self.findings(item))
        self.assertEqual(actions, [
            "security.dependabot_updates", "settings.delete_merged_branches"
        ])
        self.assertFalse(failures)
        self.assertEqual(self.findings(fake.state), [])

    def test_dependabot_prerequisite_is_audited(self):
        item = state()
        item["vulnerability_alerts"] = False
        item["repo"]["security_and_analysis"]["dependabot_security_updates"][
            "status"
        ] = "disabled"
        found = self.findings(item)
        self.assertEqual(
            [f["code"] for f in found],
            ["security.vulnerability_alerts", "security.dependabot_updates"]
        )

    def test_dependabot_prerequisite_is_enabled_first(self):
        item = state()
        item["vulnerability_alerts"] = False
        item["repo"]["security_and_analysis"]["dependabot_security_updates"][
            "status"
        ] = "disabled"
        fake = FakeGitHub(item)
        applied, failures = policy.apply_supported(
            fake, item, self.cfg, self.findings(item)
        )
        self.assertFalse(failures)
        self.assertEqual(applied, [
            "security.vulnerability_alerts",
            "security.dependabot_updates",
        ])
        self.assertEqual([row[1].split("/")[-1] for row in fake.writes],
                         ["vulnerability-alerts", "automated-security-fixes"])
        self.assertEqual(self.findings(fake.state), [])

    def test_dependabot_refuses_to_run_without_alerts(self):
        item = state()
        item["vulnerability_alerts"] = False
        item["repo"]["security_and_analysis"]["dependabot_security_updates"][
            "status"
        ] = "disabled"
        fake = FakeGitHub(item)
        # Simulate a policy that explicitly waives alerts (not a normal baseline).
        requested = [
            f for f in self.findings(item)
            if f["code"] == "security.dependabot_updates"
        ]
        applied, failures = policy.apply_supported(fake, item, self.cfg, requested)
        self.assertFalse(applied)
        self.assertTrue(any("alerts are disabled" in f for f in failures))
        self.assertFalse(fake.writes)

    def test_branch_only_added_with_real_successful_checks(self):
        item = state(protected=False)
        fake = FakeGitHub(item)
        fake.checks_ok = False
        applied, failures = policy.apply_supported(fake, item, self.cfg, self.findings(item))
        self.assertFalse(applied)
        self.assertTrue(any("missing/ambiguous" in f for f in failures))
        self.assertFalse(fake.writes)

    def test_branch_protection_fails_closed_when_rules_change(self):
        item = state(protected=False)
        fake = FakeGitHub(item)
        fake.state["rules"] = [{"type": "pull_request"}]
        applied, failures = policy.apply_supported(fake, item, self.cfg, self.findings(item))
        self.assertFalse(applied)
        self.assertTrue(failures)
        self.assertFalse(fake.writes)

    def test_branch_protection_bootstrap_and_verification(self):
        item = state(protected=False)
        fake = FakeGitHub(item)
        applied, failures = policy.apply_supported(fake, item, self.cfg, self.findings(item))
        self.assertEqual(applied, ["branch.initial_protection"])
        self.assertFalse(failures)
        self.assertEqual(self.findings(fake.state), [])
        payload = fake.writes[0][2]
        self.assertEqual(payload["required_pull_request_reviews"]["required_approving_review_count"], 0)
        self.assertTrue(payload["enforce_admins"])
        self.assertFalse(payload["allow_deletions"])

    def test_sponsor_mutation_only_with_verified_destination(self):
        item = state(sponsor=False, funding=True)
        fake = FakeGitHub(item)
        applied, failures = policy.apply_supported(fake, item, self.cfg, self.findings(item))
        self.assertEqual(applied, ["sponsor.button"])
        self.assertFalse(failures)
        self.assertTrue(fake.state["funding"]["hasSponsorshipsEnabled"])

    def test_waivers_require_reason(self):
        cfg = dict(self.cfg, waivers={
            "branch.pull_request": "Deliberate exception for reviewed legacy process"
        })
        issues = self.findings(state(pr=False), cfg)
        self.assertEqual(issues[0]["severity"], "waived")
        self.assertIsNone(issues[0]["action"])

    def test_unknown_fork_skipped_before_mutation(self):
        item = state()
        item["repository"] = "Ponchia/teavm"
        item["repo"]["fork"] = True
        item["repo"]["full_name"] = "Ponchia/teavm"
        fake = FakeGitHub(item)
        report = policy.audit(fake, self.policy, ["Ponchia/teavm"], apply=True)
        self.assertEqual(report["repositories"][0]["status"], "skipped_fork")
        self.assertFalse(fake.writes)

    def test_unknown_original_requires_registration(self):
        item = state()
        item["repository"] = "Ponchia/new-project"
        item["repo"]["full_name"] = "Ponchia/new-project"
        fake = FakeGitHub(item)
        report = policy.audit(fake, self.policy, ["Ponchia/new-project"], apply=True)
        self.assertEqual(report["repositories"][0]["status"], "unmanaged")
        self.assertFalse(fake.writes)

    def test_dry_run_never_mutates(self):
        item = state(protected=False)
        fake = FakeGitHub(item)
        report = policy.audit(fake, self.policy, [item["repository"]])
        self.assertEqual(report["repositories"][0]["status"], "needs_attention")
        self.assertFalse(fake.writes)

    def test_wrong_authenticated_account_is_refused(self):
        item = state()
        fake = FakeGitHub(item)
        fake.identity = "Elsewhere"
        with contextlib.redirect_stderr(io.StringIO()):
            code = policy.main(["--repo", item["repository"], "--apply"], client=fake)
        self.assertEqual(code, 2)
        self.assertFalse(fake.writes)

    def test_unreadable_effective_rules_fails_closed(self):
        item = state(protected=False)
        fake = FakeGitHub(item)
        fake.rule_failure = True
        report = policy.audit(fake, self.policy, [item["repository"]], apply=True)
        self.assertEqual(report["repositories"][0]["status"], "error")
        self.assertFalse(fake.writes)


if __name__ == "__main__":
    unittest.main()
