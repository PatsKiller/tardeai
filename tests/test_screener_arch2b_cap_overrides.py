#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-2B per-screener cap overrides."""
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCapOverrides(unittest.TestCase):
    def test_01_runner_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/finviz_screener_runner.py"), doraise=True)

    def test_02_global_default_5000(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertIn("DEFAULT_MAX_ROWS = 5000", src)

    def test_03_broad_screeners_10000(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        for sid in ["bond_etf_income", "covered_call_etf", "high_yield_income", "ira_income_friendly"]:
            self.assertIn(f'"{sid}": 10000', src)

    def test_04_cap_status_tracked(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertIn("cap_status", src)
        self.assertIn("ROW_LIMIT_REACHED", src)
        self.assertIn("EXHAUSTED", src)

    def test_05_raw_fetched_recorded(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertIn("raw_fetched", src)
        self.assertIn("effective_cap", src)

    def test_06_no_trading_change(self):
        src = (PROJECT_ROOT / "scripts/finviz_screener_runner.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_07_arch2_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_screener_arch2_full_ingestion_catalog.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
