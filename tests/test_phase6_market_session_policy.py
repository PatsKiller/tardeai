#!/usr/bin/env python3
"""Unit tests for Phase 6B market session policy gate.

Standalone runner (no pytest required):
    .venv/bin/python tests/test_phase6_market_session_policy.py
"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Need zoneinfo for ET datetimes
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = None

from phase6_market_session_policy import classify_market_session


def _et(year, month, day, hour, minute):
    """Create an Eastern Time datetime."""
    if ET:
        return datetime(year, month, day, hour, minute, tzinfo=ET)
    # Fallback: naive datetime (tests still work since market_session does conversion)
    return datetime(year, month, day, hour, minute)


class TestMarketSessionPolicy(unittest.TestCase):

    # ── 1. PASS: weekday regular session 10:30 ET ──
    def test_01_regular_session_allowed(self):
        # Wednesday 2026-05-13 10:30 ET
        r = classify_market_session(_et(2026, 5, 13, 10, 30))
        self.assertTrue(r["allowed"])
        self.assertEqual(r["session"], "regular")
        self.assertIn("open", r["reason"].lower())

    # ── 2. BLOCK: premarket 08:00 ET ──
    def test_02_premarket_blocked(self):
        r = classify_market_session(_et(2026, 5, 13, 8, 0))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "premarket")
        self.assertIn("pre-market", r["reason"].lower())

    # ── 3. BLOCK: afterhours 16:30 ET ──
    def test_03_afterhours_blocked(self):
        r = classify_market_session(_et(2026, 5, 13, 16, 30))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "afterhours")
        self.assertIn("after-hours", r["reason"].lower())

    # ── 4. BLOCK: overnight 20:00 ET ──
    def test_04_overnight_blocked(self):
        r = classify_market_session(_et(2026, 5, 13, 22, 0))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "closed")

    # ── 5. BLOCK: weekend Saturday ──
    def test_05_weekend_blocked(self):
        # Saturday 2026-05-16 10:30 ET
        r = classify_market_session(_et(2026, 5, 16, 10, 30))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "weekend")

    # ── 6. BLOCK: Sunday ──
    def test_06_sunday_blocked(self):
        r = classify_market_session(_et(2026, 5, 17, 10, 30))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "weekend")

    # ── 7. BLOCK: holiday ──
    def test_07_holiday_blocked(self):
        # 2026-01-01 (New Year's Day)
        r = classify_market_session(_et(2026, 1, 1, 10, 30))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "holiday")

    # ── 8. RESPONSE: structure has required fields ──
    def test_08_response_structure(self):
        r = classify_market_session(_et(2026, 5, 13, 10, 30))
        for key in ("ok", "session", "allowed", "reason", "timestamp_et",
                     "next_regular_open", "next_regular_close", "source"):
            self.assertIn(key, r, f"Missing key: {key}")

    # ── 9. Regular session has next_regular_close ──
    def test_09_regular_has_close(self):
        r = classify_market_session(_et(2026, 5, 13, 10, 30))
        self.assertIsNotNone(r["next_regular_close"])
        self.assertIn("16:00", r["next_regular_close"])

    # ── 10. Closed session has next_regular_open ──
    def test_10_closed_has_next_open(self):
        r = classify_market_session(_et(2026, 5, 16, 10, 30))  # Saturday
        self.assertIsNotNone(r["next_regular_open"])
        self.assertIn("09:30", r["next_regular_open"])

    # ── 11. Market open boundary 09:30 ──
    def test_11_market_open_boundary(self):
        r = classify_market_session(_et(2026, 5, 13, 9, 30))
        self.assertTrue(r["allowed"])
        self.assertEqual(r["session"], "regular")

    # ── 12. Market close boundary 15:59 ──
    def test_12_just_before_close(self):
        r = classify_market_session(_et(2026, 5, 13, 15, 59))
        self.assertTrue(r["allowed"])
        self.assertEqual(r["session"], "regular")

    # ── 13. Market close at 16:00 → afterhours ──
    def test_13_at_close(self):
        r = classify_market_session(_et(2026, 5, 13, 16, 0))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["session"], "afterhours")

    # ── 14. Early close day (Thanksgiving Friday) ──
    def test_14_early_close_day(self):
        # 2026-11-27 is early close
        r_before = classify_market_session(_et(2026, 11, 27, 12, 0))
        self.assertTrue(r_before["allowed"])
        r_after = classify_market_session(_et(2026, 11, 27, 14, 0))
        self.assertFalse(r_after["allowed"])

    # ── 15. Phase 6A tests still pass (regression) ──
    def test_15_phase6a_regression(self):
        from datetime import timezone
        from paper_trade_logger import validate_paper_proposal_live_market
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "bid": 100.4, "ask": 100.6, "spread_pct": 0.1,
             "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


class TestMarketSessionPolicyAuditIntegration(unittest.TestCase):
    """Test session policy integrates with audit trail."""

    @classmethod
    def setUpClass(cls):
        import psycopg2
        env = {}
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        cls.conn = psycopg2.connect(
            host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

    @classmethod
    def tearDownClass(cls):
        cur = cls.conn.cursor()
        cur.execute("DELETE FROM paper_proposal_approval_audit_events WHERE audit_id IN (SELECT id FROM paper_proposal_approval_audit WHERE proposal_id >= 77770)")
        cur.execute("DELETE FROM paper_proposal_approval_audit WHERE proposal_id >= 77770")
        cls.conn.commit()
        cls.conn.close()

    def test_16_session_block_audit(self):
        """Session block correctly recorded in audit."""
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)
        prop = {"id": 77771, "symbol": "TEST"}
        aid = create_approval_audit_attempt(self.conn, prop)
        session = classify_market_session(_et(2026, 5, 16, 10, 0))  # Saturday
        update_approval_audit(self.conn, aid,
            session_policy=session, gate="session_policy",
            gate_passed=session["allowed"])
        finalize_approval_audit(self.conn, aid, "blocked_session", session["reason"])
        cur = self.conn.cursor()
        cur.execute("SELECT approval_status, passed_session_gate FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "blocked_session")
        self.assertFalse(row[1])

    def test_17_session_pass_audit(self):
        """Session pass correctly recorded in audit."""
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit)
        prop = {"id": 77772, "symbol": "TEST"}
        aid = create_approval_audit_attempt(self.conn, prop)
        session = classify_market_session(_et(2026, 5, 13, 10, 30))  # Wednesday regular
        update_approval_audit(self.conn, aid,
            session_policy=session, gate="session_policy",
            gate_passed=session["allowed"])
        cur = self.conn.cursor()
        cur.execute("SELECT passed_session_gate FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        self.assertTrue(cur.fetchone()[0])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestMarketSessionPolicy))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketSessionPolicyAuditIntegration))
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
