#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-5 schedule/stale remediation."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_baseline_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_arch5_schedule_baseline.py"), doraise=True)

    def test_02_remediate_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/remediate_stale_screeners_arch5.py"), doraise=True)

    def test_03_health_alert_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_screener_schedule_health_alert.py"), doraise=True)

    def test_04_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestScheduleConfig(unittest.TestCase):
    def test_05_schedule_config_loads(self):
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config/screener_schedule.yaml").read_text())
        self.assertIn("sessions", cfg)
        self.assertIn("stale_thresholds", cfg)
        self.assertIn("alert_policy", cfg)

    def test_06_sessions_defined(self):
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config/screener_schedule.yaml").read_text())
        for session in ["premarket", "market_open", "intraday", "after_close", "overnight"]:
            self.assertIn(session, cfg["sessions"])


class TestRemediation(unittest.TestCase):
    def test_07_no_criteria_changes(self):
        src = (PROJECT_ROOT / "scripts/remediate_stale_screeners_arch5.py").read_text()
        self.assertNotIn("finviz_url", src)
        self.assertNotIn("screener_criteria", src)

    def test_08_no_trades(self):
        src = (PROJECT_ROOT / "scripts/remediate_stale_screeners_arch5.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_09_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/remediate_stale_screeners_arch5.py").read_text()
        self.assertNotIn("activate_strategy", src)


class TestHealthAlert(unittest.TestCase):
    def test_10_uses_router(self):
        src = (PROJECT_ROOT / "scripts/send_screener_schedule_health_alert.py").read_text()
        self.assertIn("classify_alert", src)

    def test_11_no_trades(self):
        src = (PROJECT_ROOT / "scripts/send_screener_schedule_health_alert.py").read_text()
        self.assertNotIn("create_order", src)


class TestAPI(unittest.TestCase):
    def test_12_schedule_endpoint_exists(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/screener-schedule/summary", src)


class TestSafety(unittest.TestCase):
    def test_13_no_yaml_changes(self):
        for script in ["report_screener_arch5_schedule_baseline.py", "remediate_stale_screeners_arch5.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("yaml.dump", src)

    def test_14_no_proposals(self):
        for script in ["report_screener_arch5_schedule_baseline.py", "remediate_stale_screeners_arch5.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("approve_proposal", src)


class TestRegression(unittest.TestCase):
    def test_15_arch4_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch4_full_universe_strategy_fit.py").exists())

    def test_16_ops_hygiene_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_ops_hygiene1_command_surface_alert_cleanup.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
