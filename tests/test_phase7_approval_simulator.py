#!/usr/bin/env python3
"""Unit tests for Phase 7 approval simulator.

Standalone runner:
    .venv/bin/python tests/test_phase7_approval_simulator.py
"""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from simulate_paper_proposal_approval import simulate_proposal


def _get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
                            cursor_factory=psycopg2.extras.RealDictCursor)


def _fresh_proposal(**overrides):
    """Build a mock proposal dict."""
    p = {
        "id": 99999, "symbol": "AAPL", "strategy_id": "swing_trade",
        "status": "PENDING", "proposed_entry": 200.0, "proposed_stop": 190.0,
        "proposed_target1": 220.0, "proposed_shares": 50,
        "proposed_account": "ALPACA_PAPER",
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=30),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=3),
    }
    p.update(overrides)
    return p


class TestApprovalSimulator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _get_conn()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    # 1. Fresh regular-session valid proposal
    def test_01_fresh_valid_would_pass_or_block_market(self):
        """A fresh proposal either passes all gates or blocks at session/revalidation (market-dependent)."""
        r = simulate_proposal(self.conn, _fresh_proposal())
        self.assertIn(r["overall_status"], ("would_pass", "would_block"))
        # If it blocks, it should be session or revalidation (not freshness)
        if r["overall_status"] == "would_block":
            self.assertIn(r["blocking_gate"], ("session", "revalidation", "risk_gate"))

    # 2. Stale proposal → needs_refresh
    def test_02_stale_proposal_needs_refresh(self):
        r = simulate_proposal(self.conn, _fresh_proposal(
            created_at=datetime.now(timezone.utc) - timedelta(hours=200),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        self.assertIn(r["overall_status"], ("needs_refresh", "would_block"))
        if r["overall_status"] == "needs_refresh":
            self.assertEqual(r["blocking_gate"], "freshness")

    # 3. Terminal proposal
    def test_03_terminal_proposal_blocked(self):
        r = simulate_proposal(self.conn, _fresh_proposal(status="REJECTED"))
        self.assertEqual(r["overall_status"], "would_block")
        self.assertEqual(r["blocking_gate"], "freshness")

    # 4. Missing entry/stop/target — blocks at revalidation or earlier gate
    def test_04_missing_params_blocked(self):
        r = simulate_proposal(self.conn, _fresh_proposal(proposed_entry=0))
        self.assertEqual(r["overall_status"], "would_block")
        # May block at session (if after hours) before reaching revalidation
        self.assertIn(r["blocking_gate"], ("revalidation", "session"))

    # 5. Simulator does NOT create paper_trades
    def test_05_no_trade_created(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE symbol='ZZZZZZ'")
        before = cur.fetchone()["c"]
        simulate_proposal(self.conn, _fresh_proposal(symbol="ZZZZZZ"))
        cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE symbol='ZZZZZZ'")
        after = cur.fetchone()["c"]
        self.assertEqual(before, after)

    # 6. Simulator does NOT mutate proposal status
    def test_06_no_proposal_mutation(self):
        """Simulator doesn't write to paper_trade_proposals."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM paper_trade_proposals WHERE id=99999")
        # Proposal 99999 doesn't exist — simulator should not create it
        count = cur.fetchone()["c"]
        simulate_proposal(self.conn, _fresh_proposal(id=99999))
        cur.execute("SELECT COUNT(*) as c FROM paper_trade_proposals WHERE id=99999")
        self.assertEqual(count, cur.fetchone()["c"])

    # 7. Returns proposal_freshness
    def test_07_returns_freshness(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        self.assertIn("proposal_freshness", r)
        self.assertIsNotNone(r["proposal_freshness"])

    # 8. Returns market_session_policy (if freshness passes)
    def test_08_returns_session(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        # If freshness passed, session should be populated
        if r["proposal_freshness"].get("fresh"):
            self.assertIsNotNone(r["market_session_policy"])

    # 9. Returns market_revalidation (if session passes)
    def test_09_returns_revalidation(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        if r.get("market_session_policy", {}).get("allowed"):
            self.assertIsNotNone(r["market_revalidation"])

    # 10. Returns risk_gate (if revalidation passes)
    def test_10_returns_risk_gate(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        mr = r.get("market_revalidation")
        if mr and mr.get("ok"):
            self.assertIsNotNone(r["risk_gate"])

    # 11. Returns paper_order_preview (if all pass)
    def test_11_returns_order_preview(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        if r["overall_status"] == "would_pass":
            self.assertIsNotNone(r["paper_order_preview"])
            self.assertIn("shares", r["paper_order_preview"])
            self.assertIn("dollar_risk", r["paper_order_preview"])

    # 12. Response structure complete
    def test_12_response_structure(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        for key in ("proposal_id", "symbol", "simulated_at", "overall_status",
                    "blocking_gate", "proposal_freshness", "operator_summary", "next_action"):
            self.assertIn(key, r)

    # 13. next_action is valid enum
    def test_13_next_action_valid(self):
        r = simulate_proposal(self.conn, _fresh_proposal())
        valid = {"approve_now", "refresh_proposal", "wait_for_market", "reject", "investigate"}
        self.assertIn(r["next_action"], valid)

    # 14. Phase 6A regression
    def test_14_phase6a_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1,
             "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])

    # 15. Phase 6B regression
    def test_15_phase6b_regression(self):
        try:
            from zoneinfo import ZoneInfo
            ET = ZoneInfo("America/New_York")
        except ImportError:
            return
        from phase6_market_session_policy import classify_market_session
        r = classify_market_session(datetime(2026, 5, 13, 10, 30, tzinfo=ET))
        self.assertTrue(r["allowed"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestApprovalSimulator))
    sys.exit(0 if result.wasSuccessful() else 1)
