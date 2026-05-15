#!/usr/bin/env python3
"""Unit tests for Phase 6D proposal stale-time sweeper.

Standalone runner:
    .venv/bin/python tests/test_phase6_proposal_stale_sweeper.py
"""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from phase6_proposal_staleness_policy import classify_proposal_staleness, TERMINAL_STATUSES


def _prop(strategy="swing_trade", age_min=30, status="PENDING", expires_at=None):
    """Build a mock proposal dict."""
    now = datetime.now(timezone.utc)
    p = {"id": 1, "status": status, "strategy_id": strategy,
         "created_at": now - timedelta(minutes=age_min)}
    if expires_at:
        p["expires_at"] = expires_at
    return p, now


class TestStalenessPolicy(unittest.TestCase):

    # 1. Fresh momentum under 60 min
    def test_01_fresh_momentum(self):
        p, now = _prop("gap_and_go", 30)
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["fresh"])
        self.assertEqual(r["status"], "fresh")

    # 2. Stale momentum over 60 min
    def test_02_stale_momentum(self):
        p, now = _prop("gap_and_go", 90)
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["stale"])
        self.assertEqual(r["status"], "stale")
        self.assertGreater(r["age_minutes"], 60)

    # 3. Day-trade / screener stale after 4 hours
    def test_03_stale_screener(self):
        p, now = _prop("screener", 300)  # 5 hours
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["stale"])

    # 4. Swing under 3 trading days — fresh
    def test_04_fresh_swing(self):
        p, now = _prop("swing_trade", 60)  # 1 hour
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["fresh"])

    # 5. Swing over 3 trading days — stale
    def test_05_stale_swing(self):
        p, now = _prop("swing_trade", 5000)  # > 4320 min
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["stale"])

    # 6. Recovery watch over 5 trading days
    def test_06_stale_recovery(self):
        p, now = _prop("recovery_watch", 8000)  # > 7200 min
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["stale"])

    # 7. Unknown strategy stale after 24 hours
    def test_07_stale_unknown(self):
        p, now = _prop("some_unknown_strategy", 1500)  # > 1440 min
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["stale"])
        self.assertEqual(r["threshold_minutes"], 1440)

    # 8. Missing created_at → requires_review
    def test_08_missing_timestamp(self):
        r = classify_proposal_staleness({"id": 1, "status": "PENDING"})
        self.assertEqual(r["status"], "requires_review")
        self.assertTrue(r["requires_refresh"])

    # 9. Terminal statuses ignored
    def test_09_terminal_ignored(self):
        for status in ["APPROVED", "REJECTED", "EXPIRED", "RISK_BLOCKED"]:
            r = classify_proposal_staleness({"id": 1, "status": status})
            self.assertEqual(r["status"], "terminal")

    # 10. Expired via expires_at
    def test_10_expired_via_expires_at(self):
        now = datetime.now(timezone.utc)
        p = {"id": 1, "status": "PENDING", "strategy_id": "swing_trade",
             "created_at": now - timedelta(hours=48),
             "expires_at": now - timedelta(hours=1)}
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["expired"])
        self.assertEqual(r["status"], "expired")

    # 11. Response structure
    def test_11_response_structure(self):
        p, now = _prop("swing_trade", 30)
        r = classify_proposal_staleness(p, now)
        for key in ("fresh", "stale", "expired", "requires_refresh", "status",
                     "reason", "age_minutes", "threshold_minutes", "strategy_type"):
            self.assertIn(key, r)

    # 12. Sweeper never deletes (structural test)
    def test_12_sweeper_no_delete(self):
        """Verify sweep script has no DELETE statement."""
        script = (PROJECT_ROOT / "scripts/sweep_stale_paper_proposals.py").read_text()
        self.assertNotIn("DELETE FROM paper_trade_proposals", script)

    # 13. Approval freshness blocks stale before session
    def test_13_stale_blocks_before_session(self):
        """Verify stale proposal would be blocked at freshness gate."""
        p, now = _prop("gap_and_go", 120)  # 2 hours > 60 min threshold
        r = classify_proposal_staleness(p, now)
        self.assertFalse(r["fresh"])
        # This means the approval endpoint would return 400 before session gate

    # 14. Fresh proposal proceeds
    def test_14_fresh_proceeds(self):
        p, now = _prop("swing_trade", 10)
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["fresh"])

    # 15. Phase 6A/6B/6C regression
    def test_15_phase6a_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "bid": 100.4, "ask": 100.6, "spread_pct": 0.1,
             "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])

    def test_16_phase6b_regression(self):
        try:
            from zoneinfo import ZoneInfo
            ET = ZoneInfo("America/New_York")
        except ImportError:
            return
        from phase6_market_session_policy import classify_market_session
        r = classify_market_session(datetime(2026, 5, 13, 10, 30, tzinfo=ET))
        self.assertTrue(r["allowed"])

    # 17. Income strategy has long threshold
    def test_17_income_long_threshold(self):
        p, now = _prop("income_add", 5000)  # ~3.5 days, under 14400 min
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["fresh"])
        self.assertEqual(r["threshold_minutes"], 14400)

    # 18. String timestamp parsing
    def test_18_string_timestamp(self):
        now = datetime.now(timezone.utc)
        p = {"id": 1, "status": "PENDING", "strategy_id": "swing_trade",
             "created_at": (now - timedelta(minutes=30)).isoformat()}
        r = classify_proposal_staleness(p, now)
        self.assertTrue(r["fresh"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestStalenessPolicy))
    sys.exit(0 if result.wasSuccessful() else 1)
