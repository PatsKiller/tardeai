#!/usr/bin/env python3
"""Tests for ALERT-3 Dedicated Channel and Page."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestRoutingPolicy(unittest.TestCase):

    def test_01_routing_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/telegram_alert_routing_policy.py"), doraise=True)

    def test_02_proposal_alert_routes_to_proposal(self):
        from telegram_alert_routing_policy import classify_alert_channel
        self.assertEqual(classify_alert_channel({"alert_type": "ACTIONABLE_READY"}), "proposal")
        self.assertEqual(classify_alert_channel({"alert_type": "BLOCKED_NEEDS_REBUILD"}), "proposal")

    def test_03_system_alert_routes_to_general(self):
        from telegram_alert_routing_policy import classify_alert_channel
        self.assertEqual(classify_alert_channel({"alert_type": "system_health"}), "general")

    def test_04_redact_hides_chat_id(self):
        from telegram_alert_routing_policy import redact_telegram_destination
        r = redact_telegram_destination({"chat_id": "-1001234567890", "channel_type": "proposal", "configured": True, "mode": "single"})
        self.assertNotIn("-1001234567890", str(r))
        self.assertIn("***", r["chat_id_redacted"])

    def test_05_missing_config_fails_closed(self):
        from telegram_alert_routing_policy import validate_telegram_routing_config
        r = validate_telegram_routing_config({"proposal_chat_configured": False, "general_chat_configured": False})
        self.assertFalse(r["valid"])

    def test_06_no_token_in_policy(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_routing_policy.py").read_text()
        self.assertNotIn("BOT_TOKEN", src)


class TestFrontend(unittest.TestCase):

    def test_07_proposal_alerts_page_exists(self):
        self.assertTrue((PROJECT_ROOT / "apps/command-center-v2/src/pages/ProposalAlerts.tsx").exists())

    def test_08_route_exists(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/App.tsx").read_text()
        self.assertIn("proposal-alerts", src)
        self.assertIn("ProposalAlerts", src)

    def test_09_nav_entry_exists(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/components/Shell.tsx").read_text()
        self.assertIn("Proposal Alerts", src)
        self.assertIn("/proposal-alerts", src)

    def test_10_page_no_secrets(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/ProposalAlerts.tsx").read_text()
        self.assertNotIn("BOT_TOKEN", src)
        self.assertNotIn("CHAT_ID", src)
        self.assertNotIn("API_KEY", src)


class TestSafety(unittest.TestCase):

    def test_11_no_live_trading(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_routing_policy.py").read_text()
        self.assertNotIn("enable_live", src)
        self.assertNotIn("create_order", src)

    def test_12_sender_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_telegram_proposal_alert.py"), doraise=True)

    def test_13_alert2_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_alert2_telegram_callbacks.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"ALERT-2 tests failed:\n{r.stderr}")

    def test_14_miss1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_miss1_missed_opportunity_audit.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"MISS-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
