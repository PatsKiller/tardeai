#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-1 full screener coverage."""
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestPaginationFix(unittest.TestCase):
    def test_01_runner_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/finviz_screener_runner.py"), doraise=True)

    def test_02_cap_raised_above_50(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("tickers[:50]", src)
        # SCREENER-ARCH-2 replaced [:500] with full return + emergency 5000 cap
        self.assertIn("MAX_ROWS_PER_SCREENER", src)

    def test_03_inventory_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_inventory_freshness.py"), doraise=True)


class TestSafety(unittest.TestCase):
    def test_04_no_trading_change(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_05_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_06_watch2_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_watch2_watchpool_maturity_alerts.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
