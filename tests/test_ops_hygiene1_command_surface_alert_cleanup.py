#!/usr/bin/env python3
"""Tests for OPS-HYGIENE-1 operator alert surface."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_router_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/telegram_alert_router.py"), doraise=True)

    def test_02_noise_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_operator_telegram_noise_audit.py"), doraise=True)

    def test_03_command_surface_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_operator_command_surface.py"), doraise=True)

    def test_04_page_map_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_operator_page_map.py"), doraise=True)

    def test_05_drive_validation_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_drive_doc_sync_validation.py"), doraise=True)

    def test_06_cron_hygiene_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_cron_alert_hygiene.py"), doraise=True)


class TestAlertPolicy(unittest.TestCase):
    def test_07_config_loads(self):
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config/operator_alert_policy.yaml").read_text())
        self.assertEqual(cfg["telegram_mode"], "actionable_only")
        self.assertIn("rules", cfg)
        self.assertIn("destinations", cfg)


class TestRouter(unittest.TestCase):
    def _classify(self, msg):
        from telegram_alert_router import classify_alert
        return classify_alert(msg)

    def _should_send(self, msg):
        from telegram_alert_router import should_send_telegram
        return should_send_telegram(msg)

    def test_08_wait_dashboard_only(self):
        self.assertEqual(self._classify("WAIT signal for AAPL"), "P2_DASHBOARD_ONLY")

    def test_09_avoid_dashboard_only(self):
        self.assertEqual(self._classify("AVOID signal for TSLA"), "P2_DASHBOARD_ONLY")

    def test_10_rvol_only_dashboard(self):
        self.assertEqual(self._classify("RVOL 2.5x WAIT AAPL"), "P2_DASHBOARD_ONLY")

    def test_11_raw_catalyst_dashboard(self):
        self.assertEqual(self._classify("catalyst source 15 articles found"), "P2_DASHBOARD_ONLY")

    def test_12_generic_critique_suppressed(self):
        self.assertEqual(self._classify("Trade AI Critique 5/10 reviewed 3 confirmed"), "P2_DASHBOARD_ONLY")

    def test_13_iris_audit_suppressed(self):
        self.assertEqual(self._classify("Iris Library Audit: 50 entries checked"), "P2_DASHBOARD_ONLY")

    def test_14_iris_content_gap_suppressed(self):
        self.assertEqual(self._classify("content gap detected for 3 symbols"), "P2_DASHBOARD_ONLY")

    def test_15_cron_success_log_only(self):
        self.assertEqual(self._classify("cron success: all jobs completed"), "P3_LOG_ONLY")

    def test_16_drive_sync_log_only(self):
        self.assertEqual(self._classify("sync done: 5 uploaded, 100 unchanged, 0 failed"), "P3_LOG_ONLY")

    def test_17_overnight_stop_digest(self):
        level = self._classify("STOP TRIGGERED for AAPL at $150")
        self.assertIn(level, ("P1_DIGEST",))

    def test_18_stop_not_suppressed_if_p0(self):
        level = self._classify("STOP HIT action.required for AAPL — sell immediately")
        self.assertEqual(level, "P0_INTERRUPT")

    def test_19_go_without_plan_digest(self):
        level = self._classify("Trade AI v12.1d [0900] GO-Tier: AAPL 85 points")
        self.assertEqual(level, "P1_DIGEST")

    def test_20_approval_ready_p0(self):
        level = self._classify("APPROVAL_READY: AAPL paper proposal — /ptapprove 123")
        self.assertEqual(level, "P0_INTERRUPT")

    def test_21_go_with_trade_plan_p0(self):
        level = self._classify("Trade AI LIVE GO AAPL Entry $150 Stop $145 Target $160 R:R 2.0")
        self.assertEqual(level, "P0_INTERRUPT")

    def test_22_p2_not_sent(self):
        self.assertFalse(self._should_send("WAIT signal for AAPL"))

    def test_23_p3_not_sent(self):
        self.assertFalse(self._should_send("sync done: 5 uploaded, 100 unchanged, 0 failed"))

    def test_24_aegis_brief_digest(self):
        level = self._classify("Aegis Morning Brief: 3 items")
        self.assertEqual(level, "P1_DIGEST")


class TestSafety(unittest.TestCase):
    def test_25_no_tokens_in_config(self):
        cfg_text = (PROJECT_ROOT / "config/operator_alert_policy.yaml").read_text()
        self.assertNotIn("TELEGRAM_BOT_TOKEN", cfg_text)
        self.assertNotIn("TELEGRAM_CHAT_ID", cfg_text)

    def test_26_no_trades_in_router(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_router.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_27_no_orders(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_router.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_28_no_live_trading(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_router.py").read_text()
        self.assertNotIn("ALPACA_LIVE", src)

    def test_29_no_yaml_changes(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_router.py").read_text()
        self.assertNotIn("yaml.dump", src)

    def test_30_no_finviz_changes(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert_router.py").read_text()
        self.assertNotIn("finviz_url", src)

    def test_31_telegram_alert_has_router(self):
        src = (PROJECT_ROOT / "scripts/telegram_alert.py").read_text()
        self.assertIn("should_send_telegram", src)
        self.assertIn("bypass_router", src)


class TestRegression(unittest.TestCase):
    def test_32_alert3_tests_exist(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_alert3_dedicated_channel_and_page.py").exists())

    def test_33_ux1b_tests_exist(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_journal_ux1b_closed_trade_action_dashboard.py").exists())

    def test_34_arch3c_tests_exist(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch3c_membership_lifecycle_api.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
