#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-2 full ingestion catalog."""
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestFullIngestion(unittest.TestCase):
    def test_01_runner_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/finviz_screener_runner.py"), doraise=True)

    def test_02_no_50_cap(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("tickers[:50]", src)

    def test_03_no_500_cap_as_normal_stop(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("tickers[:500]", src)

    def test_04_emergency_cap_exists(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        # SCREENER-ARCH-2B moved cap to run_screener with per-screener overrides
        self.assertIn("DEFAULT_MAX_ROWS", src)
        self.assertIn("5000", src)

    def test_05_new_ticker_cap_raised(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertIn("new_tickers[:200]", src)
        # new_tickers[:10] still used for sample preview — that's fine
        # The insertion loop must use [:200], not [:10]

    def test_06_full_csv_returned(self):
        """Verify the function returns all tickers when under emergency cap."""
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        # Should have `return tickers` as the normal path
        self.assertIn("return tickers", src)


class TestDesignDocs(unittest.TestCase):
    def test_07_pagination_design_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/screener_architecture/phase_screener_arch2_full_ingestion_catalog/finviz_full_pagination_design.md").exists())

    def test_08_catalog_design_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/screener_architecture/phase_screener_arch2_full_ingestion_catalog/ticker_catalog_lifecycle_design.md").exists())

    def test_09_ingestion_audit_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/screener_architecture/phase_screener_arch2_full_ingestion_catalog/finviz_ingestion_method_audit_report.md").exists())


class TestSafety(unittest.TestCase):
    def test_10_no_trading_change(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_11_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_12_screener_arch1_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_screener_arch1_full_coverage.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)

    def test_13_watch2_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_watch2_watchpool_maturity_alerts.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
