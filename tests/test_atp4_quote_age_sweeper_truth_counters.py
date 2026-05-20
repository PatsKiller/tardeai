#!/usr/bin/env python3
"""Tests for ATP-4 quote-age stale sweeper and truth counters."""
import sys, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_gap_report(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_quote_age_stale_sweeper_gap.py"), doraise=True)

    def test_02_action_review(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_quote_age_stale_proposal_review.py"), doraise=True)

    def test_03_staleness_policy(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/phase6_proposal_staleness_policy.py"), doraise=True)

    def test_04_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestQuoteAgeStaleness(unittest.TestCase):
    def test_05_unknown_quote_needs_action(self):
        from phase6_proposal_staleness_policy import classify_proposal_staleness
        prop = {"id": 1, "status": "PENDING", "strategy_id": "swing_trade",
                "created_at": datetime.now(timezone.utc) - timedelta(hours=1)}
        result = classify_proposal_staleness(prop)
        self.assertEqual(result["quote_status"], "never_checked")
        self.assertTrue(result["requires_refresh"])

    def test_06_fresh_proposal_stale_quote(self):
        from phase6_proposal_staleness_policy import classify_proposal_staleness
        prop = {"id": 1, "status": "PENDING", "strategy_id": "swing_trade",
                "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
                "last_price_checked_at": datetime.now(timezone.utc) - timedelta(hours=5)}
        result = classify_proposal_staleness(prop)
        self.assertTrue(result["fresh"])  # proposal is fresh
        self.assertEqual(result["quote_status"], "stale")  # but quote is stale
        self.assertTrue(result["requires_refresh"])

    def test_07_extreme_quote_age_expire(self):
        from phase6_proposal_staleness_policy import classify_proposal_staleness
        prop = {"id": 1, "status": "PENDING", "strategy_id": "recovery_watch",
                "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
                "last_price_checked_at": datetime.now(timezone.utc) - timedelta(hours=300)}
        result = classify_proposal_staleness(prop)
        self.assertEqual(result["quote_status"], "extremely_stale")
        self.assertIn("expire or rebuild", result["reason"].lower())

    def test_08_fresh_quote_no_block(self):
        from phase6_proposal_staleness_policy import classify_proposal_staleness
        prop = {"id": 1, "status": "PENDING", "strategy_id": "swing_trade",
                "created_at": datetime.now(timezone.utc) - timedelta(minutes=30),
                "last_price_checked_at": datetime.now(timezone.utc) - timedelta(minutes=10)}
        result = classify_proposal_staleness(prop)
        self.assertEqual(result["quote_status"], "fresh")
        self.assertFalse(result["requires_refresh"])


class TestCounters(unittest.TestCase):
    def test_09_unknown_quote_in_api(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("unknown_quote_count", src)
        self.assertIn("unknown quotes", src.lower())

    def test_10_pipeline_message_includes_unknown(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("unknown quotes", src)


class TestSafety(unittest.TestCase):
    def test_11_no_trades(self):
        for f in ["report_quote_age_stale_sweeper_gap.py", "run_quote_age_stale_proposal_review.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_12_no_approval(self):
        src = (PROJECT_ROOT / "scripts/run_quote_age_stale_proposal_review.py").read_text()
        self.assertNotIn("approve_proposal", src)
        self.assertNotIn("APPROVED", src.split("WHERE")[0] if "WHERE" in src else "")


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
