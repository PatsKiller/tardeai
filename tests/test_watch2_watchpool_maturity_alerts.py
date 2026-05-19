#!/usr/bin/env python3
"""Tests for WATCH-2 Watchpool Maturity Alerts."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestMaturityPolicy(unittest.TestCase):
    def test_01_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/watchpool_maturity_policy.py"), doraise=True)

    def test_02_near_trigger(self):
        from watchpool_maturity_policy import classify_watchpool_maturity
        r = classify_watchpool_maturity({"strategy_id": "swing_breakout", "latest_score": 40, "days_active": 13, "catalyst_verified": True, "quote_provider": "alpaca"})
        self.assertEqual(r["maturity_state"], "NEAR_TRIGGER")

    def test_03_ready(self):
        from watchpool_maturity_policy import classify_watchpool_maturity
        r = classify_watchpool_maturity({"strategy_id": "swing_breakout", "latest_score": 50, "days_active": 5, "catalyst_verified": True, "quote_provider": "alpaca"})
        self.assertEqual(r["maturity_state"], "WATCHPOOL_READY")

    def test_04_stale(self):
        from watchpool_maturity_policy import classify_watchpool_maturity
        r = classify_watchpool_maturity({"strategy_id": "momentum_scalp", "latest_score": 40, "days_active": 10, "status": "ACTIVE"})
        self.assertEqual(r["maturity_state"], "STALE_OR_EXPIRED")

    def test_05_needs_quote(self):
        from watchpool_maturity_policy import classify_watchpool_maturity
        r = classify_watchpool_maturity({"strategy_id": "swing_trade", "latest_score": 42, "days_active": 3})
        self.assertEqual(r["maturity_state"], "NEEDS_QUOTE_REFRESH")

    def test_06_suppression_stable(self):
        from watchpool_maturity_policy import should_suppress_watchpool_alert
        r1 = should_suppress_watchpool_alert({"symbol": "TEST", "strategy_id": "x", "latest_score": 40, "days_active": 5})
        r2 = should_suppress_watchpool_alert({"symbol": "TEST", "strategy_id": "x", "latest_score": 40, "days_active": 5}, {r1["key"]})
        self.assertFalse(r2["send"])


class TestReports(unittest.TestCase):
    def test_07_no_leads_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_no_leads_root_cause.py"), doraise=True)

    def test_08_maturity_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_watchpool_maturity_audit.py"), doraise=True)

    def test_09_alert_sender_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_watchpool_maturity_alerts.py"), doraise=True)

    def test_10_diagnostic_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_no_leads_diagnostic_alert.py"), doraise=True)

    def test_11_wrapper_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/run_scheduled_watchpool_alerts.sh").exists())

    def test_12_rollback_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/rollback_watch2_watchpool_alert_cron.sh").exists())


class TestSafety(unittest.TestCase):
    def test_13_no_trades(self):
        for f in ["watchpool_maturity_policy.py", "send_watchpool_maturity_alerts.py", "send_no_leads_diagnostic_alert.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_14_human_review_only(self):
        from watchpool_maturity_policy import classify_watchpool_maturity
        r = classify_watchpool_maturity({"strategy_id": "x", "latest_score": 40, "days_active": 5})
        self.assertTrue(r["human_review_only"])

    def test_15_alert3_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest", "tests/test_alert3_dedicated_channel_and_page.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)

    def test_16_q1_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest", "tests/test_q1_proactive_quote_refresh.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
