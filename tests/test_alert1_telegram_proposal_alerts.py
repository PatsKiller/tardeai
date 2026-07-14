#!/usr/bin/env python3
"""Tests for ALERT-1 Telegram Proposal Decision Alerts."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestAlertPolicy(unittest.TestCase):

    def test_01_policy_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/telegram_proposal_alert_policy.py"), doraise=True)

    def test_02_sender_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_telegram_proposal_alert.py"), doraise=True)

    def test_03_blocked_no_approve(self):
        from telegram_proposal_alert_policy import build_proposal_alert_packet
        pkt = build_proposal_alert_packet({
            "symbol": "TEST", "strategy_id": "momentum_scalp", "status": "PENDING",
            "operator_verdict": "BLOCKED", "proposed_rr": 1.5,
            "approval_blockers": [{"reason": "rr_below_minimum"}],
            "execution_readiness": {"readiness_state": "BLOCKED_PRICE_MOVED"},
        })
        self.assertNotIn("APPROVE_PAPER", pkt["actions"])
        self.assertFalse(pkt["approval_allowed"])

    def test_04_ready_has_approve(self):
        from telegram_proposal_alert_policy import build_proposal_alert_packet
        pkt = build_proposal_alert_packet({
            "symbol": "TEST", "strategy_id": "momentum_scalp", "status": "PENDING",
            "operator_verdict": "READY", "proposed_rr": 2.5,
            "approval_blockers": [], "approval_allowed": True,
            "execution_readiness": {"readiness_state": "READY_FOR_PAPER_SUBMIT"},
        })
        self.assertIn("APPROVE_PAPER", pkt["actions"])
        self.assertTrue(pkt["approval_allowed"])

    def test_05_blocked_rr_rebuild(self):
        from telegram_proposal_alert_policy import classify_proposal_alert_state
        state = classify_proposal_alert_state({
            "status": "PENDING", "operator_verdict": "BLOCKED",
            "approval_blockers": [{"reason": "rr_below_minimum: 1.5 < 2.0"}],
            "execution_readiness": {"readiness_state": "BLOCKED"},
        })
        self.assertEqual(state, "BLOCKED_NEEDS_REBUILD")

    def test_06_message_has_fields(self):
        from telegram_proposal_alert_policy import build_proposal_alert_packet, format_telegram_message
        pkt = build_proposal_alert_packet({
            "symbol": "ATLN", "strategy_id": "swing_breakout", "status": "PENDING",
            "proposed_entry": 1.50, "proposed_stop": 1.43, "proposed_target1": 1.65,
            "proposed_rr": 2.1, "proposed_shares": 200, "sector": "Healthcare",
            "catalyst": "Contract win", "catalyst_verified": True,
            "approval_blockers": [], "execution_readiness": {},
        })
        pkt["proposal_id"] = 2297
        pkt["account_display"] = "Schwab Taxable"
        pkt["routing_lane_label"] = "Schwab/Fidelity · 2FA manual"
        pkt["status"] = "PENDING"
        pkt["proposed_by"] = "watchlist_proposal_bridge"
        msg = format_telegram_message(pkt)
        self.assertIn("ATLN", msg)
        self.assertIn("#2297", msg)
        self.assertIn("Swing Breakout", msg)
        self.assertIn("Schwab Taxable", msg)
        self.assertIn("tab=Proposals&proposal=2297", msg)
        self.assertIn("1.50", msg)
        self.assertIn("1.43", msg)
        self.assertIn("1.65", msg)
        self.assertIn("2.1", msg)

    def test_07_suppression_key_stable(self):
        from telegram_proposal_alert_policy import alert_suppression_key
        k1 = alert_suppression_key({"id": 95, "symbol": "DWSN", "status": "PENDING", "operator_verdict": "BLOCKED"})
        k2 = alert_suppression_key({"id": 95, "symbol": "DWSN", "status": "PENDING", "operator_verdict": "BLOCKED"})
        self.assertEqual(k1, k2)

    def test_08_sender_defaults_dry_run(self):
        src = (PROJECT_ROOT / "scripts/send_telegram_proposal_alert.py").read_text()
        self.assertIn("default=True", src)

    def test_09_send_requires_flag(self):
        src = (PROJECT_ROOT / "scripts/send_telegram_proposal_alert.py").read_text()
        self.assertIn("--send", src)

    def test_10_no_token_in_policy(self):
        src = (PROJECT_ROOT / "scripts/telegram_proposal_alert_policy.py").read_text()
        self.assertNotIn("BOT_TOKEN", src)
        self.assertNotIn("CHAT_ID", src)


class TestSafety(unittest.TestCase):

    def test_11_dispatcher_no_source_env(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_proposal_alert_dispatcher.sh").read_text()
        self.assertNotIn("source .env", src)

    def test_12_dispatcher_checks_alpaca(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_proposal_alert_dispatcher.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)

    def test_13_dispatcher_checks_llm(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_proposal_alert_dispatcher.sh").read_text()
        self.assertIn("LLM_DISABLE_LIVE_EXECUTION", src)

    def test_14_no_trade_creation(self):
        for f in ["telegram_proposal_alert_policy.py", "send_telegram_proposal_alert.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_15_promote1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_promote1_pre_promotion_readiness_gate.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"PROMOTE-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
