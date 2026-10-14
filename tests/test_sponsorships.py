"""Offline tests: no network calls or real GitHub mutations."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sponsorships.py"
spec = importlib.util.spec_from_file_location("sponsorships", SCRIPT)
assert spec and spec.loader
sponsors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sponsors)


def repository(
    name="bronto-ui",
    *,
    fork=False,
    archived=False,
    visibility="PUBLIC",
    enabled=False,
    funding=True,
):
    return {
        "id": "R_test_node_id",
        "nameWithOwner": f"Ponchia/{name}",
        "visibility": visibility,
        "isFork": fork,
        "isArchived": archived,
        "hasSponsorshipsEnabled": enabled,
        "fundingLinks": (
            [{"platform": "KO_FI", "url": "https://ko-fi.com/ponchia"}]
            if funding else []
        ),
    }


class FakeGitHub:
    def __init__(self, repo=None):
        self.data = repo if repo is not None else repository()
        self.enabled_count = 0
        self.read_count = 0

    def repository(self, full_name):
        self.read_count += 1
        return dict(self.data)

    def enable_sponsorship(self, node_id):
        self.enabled_count += 1
        self.data["hasSponsorshipsEnabled"] = True

    def public_repositories(self):
        return ["Ponchia/bronto-ui", "Ponchia/cate"]


class SponsorTests(unittest.TestCase):
    def test_audit_is_read_only(self):
        fake = FakeGitHub()
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui")
        self.assertEqual("needs_activation", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_apply_enables_and_verifies(self):
        fake = FakeGitHub()
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui", apply=True)
        self.assertEqual("enabled", outcome["status"])
        self.assertEqual(1, fake.enabled_count)
        self.assertEqual(2, fake.read_count)

    def test_idempotent_when_already_enabled(self):
        fake = FakeGitHub(repository(enabled=True))
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui", apply=True)
        self.assertEqual("ready", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_skips_fork_even_with_funding(self):
        fake = FakeGitHub(repository(name="cate", fork=True))
        outcome = sponsors.audit_one(fake, "Ponchia/cate", apply=True)
        self.assertEqual("skipped_fork", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_skips_private(self):
        fake = FakeGitHub(repository(visibility="PRIVATE"))
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui", apply=True)
        self.assertEqual("skipped_private", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_skips_archived(self):
        fake = FakeGitHub(repository(archived=True))
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui", apply=True)
        self.assertEqual("skipped_archived", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_never_enables_without_expected_funding(self):
        fake = FakeGitHub(repository(funding=False))
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui", apply=True)
        self.assertEqual("missing_funding", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_rejects_different_kofi_account(self):
        fake = FakeGitHub(repository(funding=False))
        fake.data["fundingLinks"] = [
            {"platform": "KO_FI", "url": "https://ko-fi.com/other"}
        ]
        outcome = sponsors.audit_one(fake, "Ponchia/bronto-ui", apply=True)
        self.assertEqual("missing_funding", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_skips_special_defaults_repo(self):
        fake = FakeGitHub(repository(name=".github"))
        outcome = sponsors.audit_one(fake, "Ponchia/.github", apply=True)
        self.assertEqual("skipped_defaults_repository", outcome["status"])
        self.assertEqual(0, fake.enabled_count)

    def test_rejects_other_account_without_api_call(self):
        fake = FakeGitHub()
        outcome = sponsors.audit_one(fake, "SomeoneElse/repo", apply=True)
        self.assertEqual("skipped_owner", outcome["status"])
        self.assertEqual(0, fake.read_count)

    def test_json_audit_exit_code_signals_issues(self):
        fake = FakeGitHub()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = sponsors.main(["Ponchia/bronto-ui", "--json"], client=fake)
        self.assertEqual(1, code)
        self.assertIn('"needs_activation"', output.getvalue())
        self.assertEqual(0, fake.enabled_count)

    def test_json_apply_is_successful(self):
        fake = FakeGitHub()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = sponsors.main(
                ["Ponchia/bronto-ui", "--apply", "--json"], client=fake
            )
        self.assertEqual(0, code)
        self.assertIn('"enabled"', output.getvalue())
        self.assertEqual(1, fake.enabled_count)


if __name__ == "__main__":
    unittest.main()
