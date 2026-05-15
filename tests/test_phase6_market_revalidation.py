#!/usr/bin/env python3
"""Unit tests for Phase 6A live market revalidation gate.

Standalone runner (no pytest required):
    .venv/bin/python tests/test_phase6_market_revalidation.py

Tests the pure validate_paper_proposal_live_market() function
with no external dependencies (no DB, no Alpaca, no network).
"""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from paper_trade_logger import validate_paper_proposal_live_market


def _make_quote(price=100.0, bid=99.95, ask=100.05, spread_pct=0.1,
                age_seconds=5, ts=None):
    """Build a mock quote dict for testing."""
    if ts is None:
        ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {
        "last_price": price,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread_pct,
        "quote_timestamp": ts,
        "provider": "test_mock",
    }


class TestMarketRevalidation(unittest.TestCase):
    """Tests for validate_paper_proposal_live_market()."""

    # ── 1. PASS: fresh quote, drift < 1.5%, spread ok, stop ok, RR ok ──
    def test_01_pass_fresh_quote_good_conditions(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.5, spread_pct=0.1))
        self.assertTrue(r["ok"])
        self.assertFalse(r["blocked"])
        self.assertEqual(len(r["warnings"]), 0)
        self.assertGreaterEqual(r["checks"]["rr"], 1.2)
        self.assertLess(r["checks"]["entry_drift_pct"], 1.5)

    # ── 2. WARN/PASS: drift 1.5-3%, adjusted entry ──
    def test_02_warn_moderate_drift_adjusted_entry(self):
        # 2% drift above entry, wide target to maintain R:R
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 90.0, 130.0, 50,
            _make_quote(price=102.0, spread_pct=0.1))
        self.assertTrue(r["ok"])
        self.assertFalse(r["blocked"])
        self.assertEqual(len(r["warnings"]), 1)
        self.assertIn("price_adjusted", r["warnings"][0])
        self.assertEqual(r["adjusted_entry"], 102.0)

    # ── 3. BLOCK: no live quote ──
    def test_03_block_no_live_quote(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": None, "bid": None, "ask": None})
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertIn("no live price", r["reason"])

    # ── 4. BLOCK: quote older than 15 minutes ──
    def test_04_block_stale_quote(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.0, age_seconds=1200))  # 20 min
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertIn("min old", r["reason"])

    # ── 5. BLOCK: price drift > 3% ──
    def test_05_block_excessive_drift(self):
        # 4% above entry
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=104.0, spread_pct=0.1))
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertIn("stale", r["reason"])
        self.assertGreater(r["checks"]["entry_drift_pct"], 3.0)

    # ── 6. BLOCK: stop already breached (long) ──
    def test_06_block_stop_breached_long(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=94.0, spread_pct=0.1))
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertTrue(r["checks"]["stop_breached"])
        self.assertIn("stop out", r["reason"])

    # ── 7. BLOCK: stop breached — price equals stop exactly ──
    def test_07_block_stop_breached_exact(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=95.0, spread_pct=0.1))
        self.assertFalse(r["ok"])
        self.assertTrue(r["checks"]["stop_breached"])

    # ── 8. BLOCK: spread > 1.5% ──
    def test_08_block_wide_spread(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.0, spread_pct=2.5))
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertIn("spread", r["reason"])

    # ── 9. BLOCK: R:R < 1.2 ──
    def test_09_block_rr_degraded(self):
        # Price moved up close to target — reward shrinks
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 106.0, 50,
            _make_quote(price=102.0, spread_pct=0.1))
        # risk = |102 - 95| = 7, reward = |106 - 102| = 4, R:R = 0.57
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertIn("R:R", r["reason"])
        self.assertLess(r["checks"]["rr"], 1.2)

    # ── 10. BLOCK: missing bid/ask (empty quote dict) ──
    def test_10_block_missing_bid_ask(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            {})  # empty dict
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])

    # ── 11. BLOCK: missing/invalid stop ──
    def test_11_block_missing_stop(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 0, 110.0, 50,
            _make_quote(price=100.0))
        self.assertFalse(r["ok"])
        self.assertIn("stop loss", r["reason"])

    # ── 12. BLOCK: missing/invalid target ──
    def test_12_block_missing_target(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 0, 50,
            _make_quote(price=100.0))
        self.assertFalse(r["ok"])
        self.assertIn("target", r["reason"])

    # ── 13. BLOCK: calculation exception fails closed ──
    def test_13_block_calculation_exception_fails_closed(self):
        # Pass a quote_timestamp that will cause age calculation to fail
        bad_quote = _make_quote(price=100.0)
        bad_quote["quote_timestamp"] = {"invalid": "object"}
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50, bad_quote)
        # Should either fail closed or skip timestamp check (object has no tzinfo)
        # The function handles this: hasattr check fails, isinstance check fails,
        # then (now - object) throws, caught by except → fail closed
        self.assertFalse(r["ok"])

    # ── 14. RESPONSE: market_revalidation structure ──
    def test_14_response_structure(self):
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.5, spread_pct=0.1))
        # Required fields
        self.assertIn("ok", r)
        self.assertIn("blocked", r)
        self.assertIn("warnings", r)
        self.assertIn("reason", r)
        self.assertIn("checks", r)
        self.assertIn("original_entry", r)
        self.assertIn("adjusted_entry", r)
        self.assertIn("live_price", r)
        self.assertIn("bid", r)
        self.assertIn("ask", r)
        self.assertIn("timestamp", r)
        # Check sub-fields
        checks = r["checks"]
        self.assertIn("quote_available", checks)
        self.assertIn("quote_age_minutes", checks)
        self.assertIn("quote_fresh", checks)
        self.assertIn("entry_drift_pct", checks)
        self.assertIn("stop_breached", checks)
        self.assertIn("spread_pct", checks)
        self.assertIn("rr", checks)

    # ── 15. ORDERING: revalidation runs before risk gate ──
    def test_15_ordering_revalidation_before_risk_gate(self):
        """Verify the approve_proposal flow calls revalidation first.

        We can't easily test the full flow without DB, but we verify
        the function signature and that it returns before risk gate
        would be called (by checking blocked result has no paper_trade_id).
        """
        # A blocked revalidation should never create a paper trade
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=90.0))  # stop breached
        self.assertFalse(r["ok"])
        # No paper_trade_id in result — risk gate and trade creation never reached
        self.assertNotIn("paper_trade_id", r)

    # ── Additional edge cases ──

    def test_16_string_timestamp_iso(self):
        """Quote timestamp as ISO string (Alpaca format)."""
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.0, spread_pct=0.1,
                        ts=datetime.now(timezone.utc).isoformat()))
        self.assertTrue(r["ok"])

    def test_17_unix_timestamp(self):
        """Quote timestamp as unix epoch float."""
        import time
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.0, spread_pct=0.1,
                        ts=time.time()))
        self.assertTrue(r["ok"])

    def test_18_no_timestamp_passes(self):
        """Quote with no timestamp should not block (trust provider)."""
        q = _make_quote(price=100.0, spread_pct=0.1)
        del q["quote_timestamp"]
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50, q)
        self.assertTrue(r["ok"])

    def test_19_configurable_thresholds(self):
        """Custom thresholds should override defaults."""
        # 2% drift would normally pass, but with max_block_drift_pct=1.5 it blocks
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 90.0, 115.0, 50,
            _make_quote(price=102.0, spread_pct=0.1),
            max_block_drift_pct=1.5)
        self.assertFalse(r["ok"])

    def test_20_none_quote_blocks(self):
        """None quote should block."""
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50, None)
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])

    def test_21_missing_entry(self):
        """Missing entry price should block."""
        r = validate_paper_proposal_live_market(
            "TEST", 0, 95.0, 110.0, 50,
            _make_quote(price=100.0))
        self.assertFalse(r["ok"])
        self.assertIn("entry", r["reason"])

    def test_22_rr_exactly_minimum(self):
        """R:R at exactly min_rr should pass."""
        # Need: reward/risk = 1.2 exactly
        # stop=90, price=100, target=112 → risk=10, reward=12, rr=1.2
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 90.0, 112.0, 50,
            _make_quote(price=100.0, spread_pct=0.1))
        self.assertTrue(r["ok"])
        self.assertEqual(r["checks"]["rr"], 1.2)

    def test_23_spread_exactly_at_limit(self):
        """Spread at exactly 1.5% should not block."""
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            _make_quote(price=100.0, spread_pct=1.5))
        self.assertTrue(r["ok"])

    def test_24_drift_exactly_at_block(self):
        """Drift at exactly 3.0% should not block (> 3.0 required)."""
        # Wide target to maintain R:R after drift
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 85.0, 130.0, 50,
            _make_quote(price=103.0, spread_pct=0.1))
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    # Run as standalone
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestMarketRevalidation))
    sys.exit(0 if result.wasSuccessful() else 1)
