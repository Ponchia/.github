"""Offline regression tests for the read-only Actions run inventory."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

script = Path(__file__).resolve().parents[1] / "scripts/actions_efficiency.py"
spec = importlib.util.spec_from_file_location("actions_efficiency", script)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def item(number, event="pull_request", pr=2):
    return {
        "id": number, "name": "CI", "event": event, "conclusion": "success",
        "pull_requests": [{"number": pr}] if pr is not None else [],
    }


class ActionsTests(unittest.TestCase):
    def test_complete_pagination_and_repeat_detection(self):
        records = [item(n) for n in range(101)]
        pages = {
            1: {"total_count": 101, "workflow_runs": records[:100]},
            2: {"total_count": 101, "workflow_runs": records[100:]},
        }
        found = audit.collect_runs(pages.__getitem__)
        report = audit.summarize("Ponchia/a", found)
        self.assertEqual(report["runs"], 101)
        self.assertEqual(report["events"], {"pull_request": 101})
        self.assertEqual(report["repeatAttempts"], [{"pr": 2, "workflow": "CI", "runs": 101}])

    def test_empty_interval(self):
        self.assertEqual(
            audit.collect_runs(lambda _: {"total_count": 0, "workflow_runs": []}), []
        )

    def test_incomplete_fails_closed(self):
        with self.assertRaisesRegex(audit.AuditError, "incomplete"):
            audit.collect_runs(
                lambda page: {
                    "total_count": 2,
                    "workflow_runs": [item(1)] if page == 1 else [],
                }
            )

    def test_duplicate_page_fails_closed(self):
        first = {"total_count": 101, "workflow_runs": [item(n) for n in range(100)]}
        second = {"total_count": 101, "workflow_runs": [item(0)]}
        with self.assertRaisesRegex(audit.AuditError, "Overlapping"):
            audit.collect_runs(lambda n: first if n == 1 else second)

    def test_page_limit_fails_closed(self):
        with self.assertRaisesRegex(audit.AuditError, "narrow"):
            audit.collect_runs(lambda _: {"total_count": 301, "workflow_runs": []}, max_pages=3)

    def test_missing_count_fails_closed(self):
        with self.assertRaisesRegex(audit.AuditError, "total_count"):
            audit.collect_runs(lambda _: {"total_count": "a", "workflow_runs": []})

    def test_pr_without_number_is_explicit(self):
        result = audit.summarize("Ponchia/a", [item(1, pr=None)])
        self.assertEqual(result["unboundPrRuns"], 1)
        self.assertEqual(result["repeatAttempts"], [])

    def test_date_strict(self):
        self.assertEqual(audit.iso_day("2026-11-13").isoformat(), "2026-11-13")
        with self.assertRaises(Exception):
            audit.iso_day("2026-1-3")


if __name__ == "__main__":
    unittest.main()
