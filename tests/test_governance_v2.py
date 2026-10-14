"""Offline safety tests. No GitHub network or live writes."""

from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import stat
import sys
import tempfile
import unittest

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, str(BASE / "tests"))

import governance_v2 as g
import repository_policy as rp
from test_repository_policy import FakeGitHub, state


class FakeClient(FakeGitHub):
    def __init__(self, item=None):
        item = item or state()
        item["repo"]["id"] = 12345
        super().__init__(item)
        self.head = "a" * 40

    def get(self, path, *, not_found_ok=False):
        if path == (
            f"repos/{self.state['repository']}/branches/"
            f"{self.state['repo']['default_branch']}"
        ):
            return {"commit": {"sha": self.head}}
        return super().get(path, not_found_ok=not_found_ok)


class FakeNotifier:
    def __init__(self, fail=False):
        self.created = []
        self.commented = []
        self.closed = []
        self.fail = fail
        self.open = set()
        self.next_number = 100

    def issue(self, number):
        return {"state": "open" if number in self.open else "closed"} if number else None

    def create(self, body):
        if self.fail:
            raise rp.ApiError("GitHub issue API transient failure", 503)
        number = self.next_number
        self.next_number += 1
        self.created.append(body)
        self.open.add(number)
        return number

    def comment(self, number, body):
        self.commented.append((number, body))

    def close(self, number):
        self.closed.append(number)
        self.open.discard(number)


class PlanAndWatchTests(unittest.TestCase):
    def setUp(self):
        self.policy = rp.read_policy()
        self.day = dt.datetime(2026, 10, 14, 15, 0, tzinfo=dt.timezone.utc)
        self.dir = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def drift_state(self):
        obj = state()
        obj["repo"]["delete_branch_on_merge"] = False
        return obj

    def plan(self, client):
        return g.make_plan(
            client, [client.state["repository"]],
            self.policy, clock=self.day,
        )

    def test_plan_contains_reviewable_changes_and_stable_digest(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        self.assertEqual(plan["schemaVersion"], 2)
        self.assertEqual(
            plan["changes"][0]["actions"],
            ["settings.delete_merged_branches"],
        )
        g.validate_plan(plan, clock=self.day)
        self.assertEqual(0, len(client.writes))
        self.assertEqual(64, len(plan["planSha256"]))

    def test_clean_plan_has_no_actions(self):
        client = FakeClient()
        plan = self.plan(client)
        self.assertFalse(plan["changes"])
        self.assertEqual(0, len(client.writes))

    def test_tampered_plan_rejected(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        plan["changes"][0]["actions"].append("security.vulnerability_alerts")
        with self.assertRaisesRegex(rp.PolicyError, "digest"):
            g.validate_plan(plan, clock=self.day)
        self.assertFalse(client.writes)

    def test_expired_plan_rejected(self):
        plan = self.plan(FakeClient(self.drift_state()))
        with self.assertRaisesRegex(rp.PolicyError, "expired"):
            g.validate_plan(plan, clock=self.day + dt.timedelta(days=2))

    def test_wrong_approval_hash_rejected_without_receipt(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        with self.assertRaisesRegex(rp.PolicyError, "approval"):
            g.apply_plan(client, plan, approve="f" * 64,
                         state_dir=self.state_dir, clock=self.day)
        self.assertFalse(client.writes)
        self.assertFalse(list(self.state_dir.glob("receipts/*.json")))

    def test_wrong_authenticated_account_rejected(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        client.identity = "SomeoneElse"
        with self.assertRaisesRegex(rp.PolicyError, "not Ponchia"):
            g.apply_plan(client, plan, approve=plan["planSha256"],
                         state_dir=self.state_dir, clock=self.day)
        self.assertFalse(client.writes)

    def test_stale_config_rejected_before_writes(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        client.state["repo"]["description"] = "Changed upstream"
        with self.assertRaisesRegex(rp.PolicyError, "Stale"):
            g.apply_plan(client, plan, approve=plan["planSha256"],
                         state_dir=self.state_dir, clock=self.day)
        self.assertFalse(client.writes)

    def test_new_commit_rejected_before_writes(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        client.head = "b" * 40
        with self.assertRaisesRegex(rp.PolicyError, "Stale"):
            g.apply_plan(client, plan, approve=plan["planSha256"],
                         state_dir=self.state_dir, clock=self.day)
        self.assertFalse(client.writes)

    def test_plan_applied_once_and_receipt_is_durable(self):
        client = FakeClient(self.drift_state())
        plan = self.plan(client)
        done = g.apply_plan(client, plan, approve=plan["planSha256"],
                            state_dir=self.state_dir, clock=self.day)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(
            done["executed"][0]["applied"],
            ["settings.delete_merged_branches"],
        )
        receipt = pathlib.Path(done["receipt"])
        self.assertTrue(receipt.exists())
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(g.load_json(receipt)["status"], "completed")
        with self.assertRaisesRegex(rp.PolicyError, "replay"):
            g.apply_plan(client, plan, approve=plan["planSha256"],
                         state_dir=self.state_dir, clock=self.day)
        self.assertEqual(len(client.writes), 1)

    def test_watch_clean_baseline_is_silent_and_read_only(self):
        client = FakeClient()
        notifier = FakeNotifier()
        outcome = g.watch_once(
            client, self.policy, state_dir=self.state_dir, notify=True,
            notifier=notifier, clock=self.day,
        )
        self.assertEqual(outcome["status"], "clean")
        self.assertEqual(outcome["notification"], "clean_baseline")
        self.assertFalse(notifier.created)
        self.assertFalse(client.writes)
        snapshot = pathlib.Path(outcome["evidence"])
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)

    def test_watch_notifies_only_on_new_changes_and_resolution(self):
        client = FakeClient()
        notifier = FakeNotifier()
        g.watch_once(client, self.policy, state_dir=self.state_dir,
                     notify=True, notifier=notifier, clock=self.day)
        client.state["repo"]["delete_branch_on_merge"] = False
        t = self.day + dt.timedelta(minutes=1)
        first = g.watch_once(client, self.policy, state_dir=self.state_dir,
                             notify=True, notifier=notifier, clock=t)
        self.assertEqual(first["notification"], "drift_reported")
        self.assertEqual(len(notifier.created), 1)
        same = g.watch_once(
            client, self.policy, state_dir=self.state_dir,
            notify=True, notifier=notifier,
            clock=t + dt.timedelta(minutes=1),
        )
        self.assertEqual(same["notification"], "unchanged")
        self.assertEqual(len(notifier.created), 1)
        client.state["repo"]["delete_branch_on_merge"] = True
        resolved = g.watch_once(
            client, self.policy, state_dir=self.state_dir,
            notify=True, notifier=notifier,
            clock=t + dt.timedelta(minutes=2),
        )
        self.assertEqual(resolved["notification"], "resolution_reported")
        self.assertEqual(len(notifier.closed), 1)
        self.assertEqual(len(notifier.commented), 1)
        self.assertFalse(client.writes)

    def test_watch_failure_preserves_previous_comparison_state(self):
        client = FakeClient(self.drift_state())
        notifier = FakeNotifier(fail=True)
        with self.assertRaisesRegex(rp.ApiError, "transient"):
            g.watch_once(
                client, self.policy, state_dir=self.state_dir,
                notify=True, notifier=notifier, clock=self.day,
            )
        self.assertFalse((self.state_dir / "watch-state.json").exists())
        notifier.fail = False
        second = g.watch_once(
            client, self.policy, state_dir=self.state_dir,
            notify=True, notifier=notifier,
            clock=self.day + dt.timedelta(minutes=1),
        )
        self.assertEqual(second["notification"], "drift_reported")
        self.assertEqual(len(notifier.created), 1)

    def test_read_only_watch_does_not_acknowledge_pending_notification(self):
        client = FakeClient(self.drift_state())
        notifier = FakeNotifier()
        manual = g.watch_once(
            client, self.policy, state_dir=self.state_dir,
            notify=False, notifier=notifier, clock=self.day,
        )
        self.assertEqual(manual["notification"], "disabled")
        self.assertFalse(notifier.created)
        scheduled = g.watch_once(
            client, self.policy, state_dir=self.state_dir,
            notify=True, notifier=notifier,
            clock=self.day + dt.timedelta(minutes=1),
        )
        self.assertFalse(scheduled["changed"])
        self.assertEqual(scheduled["notification"], "drift_reported")
        self.assertEqual(len(notifier.created), 1)

    def test_evidence_writer_does_not_chmod_existing_parent(self):
        with tempfile.TemporaryDirectory() as root:
            parent = pathlib.Path(root)
            parent.chmod(0o755)
            child = parent / "receipts" / "evidence.json"
            g.write_json(child, {"schemaVersion": 1}, exclusive=True)
            self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(child.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o600)

    def test_advisories_are_not_notified(self):
        client = FakeClient()
        client.state["repo"]["topics"] = []
        notifier = FakeNotifier()
        outcome = g.watch_once(
            client, self.policy, state_dir=self.state_dir,
            notify=True, notifier=notifier, clock=self.day,
        )
        self.assertEqual(outcome["status"], "clean")
        self.assertFalse(notifier.created)
        self.assertEqual(outcome["findings"], 0)

    def test_concurrent_writes_use_exclusive_state_lock(self):
        with g.ExclusiveLock(self.state_dir):
            with self.assertRaises(BlockingIOError):
                with g.ExclusiveLock(self.state_dir):
                    pass


if __name__ == "__main__":
    unittest.main()
