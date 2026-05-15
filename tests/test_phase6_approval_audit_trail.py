#!/usr/bin/env python3
"""Unit tests for Phase 6C approval audit trail.

Standalone runner (no pytest required):
    .venv/bin/python tests/test_phase6_approval_audit_trail.py

Tests the audit helper functions against a real DB connection.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_test_conn():
    """Get DB connection for tests."""
    import psycopg2
    env = {}
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env.get("DB_HOST", "localhost"),
        dbname=env.get("DB_NAME", "trade_ai"),
        user=env.get("DB_USER", "trade_ai"),
        password=env.get("DB_PASSWORD", ""))


class TestApprovalAuditHelpers(unittest.TestCase):
    """Tests for phase6_approval_audit.py helper functions."""

    @classmethod
    def setUpClass(cls):
        cls.conn = _get_test_conn()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _make_proposal(self, pid=99999):
        return {
            "id": pid, "symbol": "TEST", "side": "long",
            "proposed_entry": 100.0, "proposed_stop": 95.0,
            "proposed_target1": 110.0, "proposed_shares": 50,
            "status": "PENDING",
        }

    # ── 1. Audit row created at attempt start ──
    def test_01_audit_created(self):
        from phase6_approval_audit import create_approval_audit_attempt
        aid = create_approval_audit_attempt(self.conn, self._make_proposal())
        self.assertIsInstance(aid, int)
        self.assertGreater(aid, 0)
        # Verify row exists
        cur = self.conn.cursor()
        cur.execute("SELECT approval_status, proposal_id FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "started")
        self.assertEqual(row[1], 99999)

    # ── 2. Audit creation failure blocks (tested by checking raise behavior) ──
    def test_02_audit_creation_raises_on_failure(self):
        from phase6_approval_audit import create_approval_audit_attempt
        import psycopg2
        # Use a closed connection to simulate failure
        bad_conn = _get_test_conn()
        bad_conn.close()
        with self.assertRaises(Exception):
            create_approval_audit_attempt(bad_conn, self._make_proposal())

    # ── 3. Full successful path records all gates ──
    def test_03_full_success_path(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit,
            append_approval_audit_event, finalize_approval_audit)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99998))

        # Session gate
        update_approval_audit(self.conn, aid,
            session_policy={"allowed": True}, gate="session_policy", gate_passed=True)

        # Market revalidation
        update_approval_audit(self.conn, aid,
            market_revalidation={"passed": True, "live_price": 100.5},
            gate="market_revalidation", gate_passed=True,
            fields={"live_price": 100.5, "rr_at_approval": 2.1})

        # Risk gate
        update_approval_audit(self.conn, aid,
            risk_gate={"result": "APPROVED"}, gate="risk_gate", gate_passed=True)

        # Paper trade
        update_approval_audit(self.conn, aid,
            paper_trade={"paper_trade_id": 123}, gate="paper_trade", gate_passed=True)

        # Alpaca submission
        update_approval_audit(self.conn, aid,
            alpaca_response={"status": "submitted"}, gate="alpaca_submission", gate_passed=True)

        # Finalize
        finalize_approval_audit(self.conn, aid, "approved_paper_submitted", "All gates passed")

        # Verify
        cur = self.conn.cursor()
        cur.execute("""SELECT approval_status, passed_session_gate, passed_market_revalidation,
                              passed_risk_gate, paper_trade_created, alpaca_submitted, gate_sequence
                       FROM paper_proposal_approval_audit WHERE id=%s""", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "approved_paper_submitted")
        self.assertTrue(row[1])  # session
        self.assertTrue(row[2])  # revalidation
        self.assertTrue(row[3])  # risk gate
        self.assertTrue(row[4])  # paper trade
        self.assertTrue(row[5])  # alpaca
        self.assertIn("session_policy", row[6])
        self.assertIn("market_revalidation", row[6])
        self.assertIn("risk_gate", row[6])
        self.assertIn("paper_trade", row[6])
        self.assertIn("alpaca_submission", row[6])

    # ── 4. Session block records correctly ──
    def test_04_session_block(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99997))
        update_approval_audit(self.conn, aid,
            session_policy={"allowed": False, "reason": "after_hours"},
            gate="session_policy", gate_passed=False)
        finalize_approval_audit(self.conn, aid, "blocked_session", "After hours")

        cur = self.conn.cursor()
        cur.execute("""SELECT approval_status, passed_session_gate, passed_market_revalidation,
                              passed_risk_gate, paper_trade_created, alpaca_submitted
                       FROM paper_proposal_approval_audit WHERE id=%s""", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "blocked_session")
        self.assertFalse(row[1])
        self.assertFalse(row[2])
        self.assertFalse(row[3])
        self.assertFalse(row[4])
        self.assertFalse(row[5])

    # ── 5. Market revalidation block ──
    def test_05_market_reval_block(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99996))
        update_approval_audit(self.conn, aid,
            session_policy={"allowed": True}, gate="session_policy", gate_passed=True)
        update_approval_audit(self.conn, aid,
            market_revalidation={"passed": False, "blockers": ["stale_quote"]},
            gate="market_revalidation", gate_passed=False)
        finalize_approval_audit(self.conn, aid, "blocked_market_revalidation", "Stale quote")

        cur = self.conn.cursor()
        cur.execute("SELECT approval_status, passed_session_gate, passed_market_revalidation FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "blocked_market_revalidation")
        self.assertTrue(row[1])
        self.assertFalse(row[2])

    # ── 6. Risk gate block ──
    def test_06_risk_gate_block(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99995))
        update_approval_audit(self.conn, aid, gate="session_policy", gate_passed=True)
        update_approval_audit(self.conn, aid, gate="market_revalidation", gate_passed=True)
        update_approval_audit(self.conn, aid,
            risk_gate={"result": "BLOCKED"}, gate="risk_gate", gate_passed=False)
        finalize_approval_audit(self.conn, aid, "blocked_risk_gate", "Risk gate blocked")

        cur = self.conn.cursor()
        cur.execute("SELECT approval_status, passed_risk_gate, paper_trade_created FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "blocked_risk_gate")
        self.assertFalse(row[1])
        self.assertFalse(row[2])

    # ── 7. Paper trade creation failure ──
    def test_07_trade_creation_failure(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99994))
        update_approval_audit(self.conn, aid, gate="session_policy", gate_passed=True)
        update_approval_audit(self.conn, aid, gate="market_revalidation", gate_passed=True)
        update_approval_audit(self.conn, aid, gate="risk_gate", gate_passed=True)
        finalize_approval_audit(self.conn, aid, "failed_trade_creation", "DB insert failed")

        cur = self.conn.cursor()
        cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        self.assertEqual(cur.fetchone()[0], "failed_trade_creation")

    # ── 8. Alpaca submission failure ──
    def test_08_alpaca_failure(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99993))
        update_approval_audit(self.conn, aid, gate="session_policy", gate_passed=True)
        update_approval_audit(self.conn, aid, gate="market_revalidation", gate_passed=True)
        update_approval_audit(self.conn, aid, gate="risk_gate", gate_passed=True)
        update_approval_audit(self.conn, aid, gate="paper_trade", gate_passed=True)
        update_approval_audit(self.conn, aid,
            alpaca_response={"status": "failed", "error": "timeout"},
            gate="alpaca_submission", gate_passed=False)
        finalize_approval_audit(self.conn, aid, "failed_alpaca_submission", "Alpaca timeout")

        cur = self.conn.cursor()
        cur.execute("SELECT approval_status, alpaca_submitted FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "failed_alpaca_submission")
        self.assertFalse(row[1])

    # ── 9. Events table populated ──
    def test_09_events_recorded(self):
        from phase6_approval_audit import (
            create_approval_audit_attempt, append_approval_audit_event)

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99992))
        append_approval_audit_event(self.conn, aid, "test_event", "ok", message="test msg")

        cur = self.conn.cursor()
        cur.execute("SELECT event_type, event_status, message FROM paper_proposal_approval_audit_events WHERE audit_id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "test_event")
        self.assertEqual(row[1], "ok")
        self.assertEqual(row[2], "test msg")

    # ── 10. No secrets stored ──
    def test_10_no_secrets_stored(self):
        from phase6_approval_audit import create_approval_audit_attempt

        prop = self._make_proposal(99991)
        prop["api_key"] = "sk-secret-123"
        prop["broker_password"] = "supersecret"
        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99991),
            request_ip="192.168.1.100", user_agent="Mozilla/5.0")

        cur = self.conn.cursor()
        cur.execute("SELECT request_ip_hash, user_agent_hash, proposal_snapshot_json::text FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        # IP and UA should be hashed, not raw
        self.assertNotIn("192.168.1.100", row[0] or "")
        self.assertNotIn("Mozilla", row[1] or "")
        # proposal_snapshot should not contain secret fields
        self.assertNotIn("sk-secret", row[2] or "")

    # ── 11. Safety state captured ──
    def test_11_safety_state_captured(self):
        from phase6_approval_audit import create_approval_audit_attempt

        aid = create_approval_audit_attempt(self.conn, self._make_proposal(99990))
        cur = self.conn.cursor()
        cur.execute("SELECT alpaca_mode, llm_live_execution_disabled, live_trading_enabled FROM paper_proposal_approval_audit WHERE id=%s", [aid])
        row = cur.fetchone()
        self.assertEqual(row[0], "paper")
        self.assertTrue(row[1])
        self.assertFalse(row[2])


class TestApprovalAuditCleanup(unittest.TestCase):
    """Clean up test audit rows."""

    @classmethod
    def tearDownClass(cls):
        conn = _get_test_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM paper_proposal_approval_audit_events WHERE audit_id IN (SELECT id FROM paper_proposal_approval_audit WHERE proposal_id >= 99990)")
        cur.execute("DELETE FROM paper_proposal_approval_audit WHERE proposal_id >= 99990")
        conn.commit()
        conn.close()

    def test_cleanup(self):
        """Dummy test to trigger cleanup."""
        pass


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestApprovalAuditHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestApprovalAuditCleanup))
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
