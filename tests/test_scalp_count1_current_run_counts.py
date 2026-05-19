#!/usr/bin/env python3
"""Tests for SCALP-COUNT-1 current-run count fix."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestAPIFix(unittest.TestCase):
    def test_01_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)

    def test_02_api_has_current_run_fields(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("current_run_scanned", src)
        self.assertIn("current_run_go", src)
        self.assertIn("current_run_wait", src)
        self.assertIn("current_run_nogo", src)

    def test_03_api_has_universe_fields(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("universe_count", src)
        self.assertIn("universe_go", src)

    def test_04_current_run_filters_by_run_label(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("scan_run_label", src)
        self.assertIn("_current_run_label", src)


class TestFrontendFix(unittest.TestCase):
    def test_05_frontend_uses_current_run(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/TradeAI.tsx").read_text()
        self.assertIn("current_run_scanned", src)
        self.assertIn("universe_count", src)

    def test_06_all_renamed_to_universe(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/TradeAI.tsx").read_text()
        self.assertIn("Universe", src)

    def test_07_frontend_build_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("TradeAI-*.js")))


class TestSafety(unittest.TestCase):
    def test_08_no_trading_logic_changed(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # SCALP-COUNT-1 section should not contain order/trade creation
        idx = src.find("SCALP-COUNT-1")
        if idx > 0:
            section = src[idx:idx+500]
            self.assertNotIn("INSERT INTO", section)
            self.assertNotIn("create_order", section)

    def test_09_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        idx = src.find("SCALP-COUNT-1")
        if idx > 0:
            section = src[idx:idx+500]
            self.assertNotIn("activate_strategy", section)

    def test_10_watch2_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_watch2_watchpool_maturity_alerts.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
