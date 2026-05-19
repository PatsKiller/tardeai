#!/usr/bin/env python3
"""Tests for ALERT-2 Telegram Proposal Callbacks."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCallbackPolicy(unittest.TestCase):

    def test_01_policy_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/telegram_callback_policy.py"), doraise=True)

    def test_02_handler_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/handle_telegram_proposal_callback.py"), doraise=True)

    def test_03_blocked_no_approve(self):
        from telegram_callback_policy import classify_callback_action
        r = classify_callback_action(
            {"action": "APPROVE_PAPER"},
            {"status": "PENDING", "proposed_rr": 1.5,
             "approval_blockers": [{"reason": "rr_below"}],
             "execution_readiness": {"readiness_state": "BLOCKED_PRICE_MOVED"}}
        )
        self.assertFalse(r["allowed"])

    def test_04_blocked_allows_rebuild(self):
        from telegram_callback_policy import classify_callback_action
        r = classify_callback_action(
            {"action": "REBUILD"},
            {"status": "PENDING", "approval_blockers": [{"reason": "blocked"}]}
        )
        self.assertTrue(r["allowed"])

    def test_05_ready_allows_approve(self):
        from telegram_callback_policy import classify_callback_action
        r = classify_callback_action(
            {"action": "APPROVE_PAPER"},
            {"status": "PENDING", "proposed_rr": 2.5, "approval_allowed": True,
             "approval_blockers": [], "execution_readiness": {"readiness_state": "READY"}}
        )
        self.assertTrue(r["allowed"])
        self.assertTrue(r["paper_only"])

    def test_06_approve_requires_pending(self):
        from telegram_callback_policy import classify_callback_action
        r = classify_callback_action(
            {"action": "APPROVE_PAPER"},
            {"status": "EXPIRED", "proposed_rr": 2.5, "approval_allowed": True}
        )
        self.assertFalse(r["allowed"])

    def test_07_stale_quote_blocks(self):
        from telegram_callback_policy import classify_callback_action
        r = classify_callback_action(
            {"action": "APPROVE_PAPER"},
            {"status": "PENDING", "proposed_rr": 2.5,
             "approval_blockers": [{"reason": "quote_stale"}],
             "execution_readiness": {"readiness_state": "BLOCKED"}}
        )
        self.assertFalse(r["allowed"])

    def test_08_rr_below_blocks(self):
        from telegram_callback_policy import classify_callback_action
        r = classify_callback_action(
            {"action": "APPROVE_PAPER"},
            {"status": "PENDING", "proposed_rr": 1.8, "approval_blockers": [],
             "execution_readiness": {"readiness_state": "READY"}}
        )
        self.assertFalse(r["allowed"])

    def test_09_handler_defaults_dry_run(self):
        src = (PROJECT_ROOT / "scripts/handle_telegram_proposal_callback.py").read_text()
        self.assertIn("default=True", src)

    def test_10_apply_requires_flag(self):
        src = (PROJECT_ROOT / "scripts/handle_telegram_proposal_callback.py").read_text()
        self.assertIn("--apply", src)

    def test_11_suppression_key_stable(self):
        from telegram_callback_policy import callback_suppression_key
        k1 = callback_suppression_key({"action": "APPROVE_PAPER", "proposal_id": 95, "symbol": "DWSN"})
        k2 = callback_suppression_key({"action": "APPROVE_PAPER", "proposal_id": 95, "symbol": "DWSN"})
        self.assertEqual(k1, k2)

    def test_12_no_live_action(self):
        from telegram_callback_policy import ALLOWED_ACTIONS
        self.assertNotIn("APPROVE_LIVE", ALLOWED_ACTIONS)
        self.assertNotIn("SUBMIT_ORDER", ALLOWED_ACTIONS)

    def test_13_alert_has_commands(self):
        src = (PROJECT_ROOT / "scripts/telegram_proposal_alert_policy.py").read_text()
        self.assertIn("/ptapprove", src)
        self.assertIn("/ptreject", src)


class TestSafety(unittest.TestCase):

    def test_14_no_token_in_policy(self):
        src = (PROJECT_ROOT / "scripts/telegram_callback_policy.py").read_text()
        self.assertNotIn("BOT_TOKEN", src)

    def test_15_no_trade_creation(self):
        src = (PROJECT_ROOT / "scripts/telegram_callback_policy.py").read_text()
        self.assertNotIn("create_order", src)
        src2 = (PROJECT_ROOT / "scripts/handle_telegram_proposal_callback.py").read_text()
        self.assertNotIn("create_order", src2)

    def test_16_alert1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_alert1_telegram_proposal_alerts.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"ALERT-1 tests failed:\n{r.stderr}")

    def test_17_q1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_q1_proactive_quote_refresh.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"Q-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
