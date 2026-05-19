#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-3B importer membership backfill."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestBackfill(unittest.TestCase):
    def test_01_backfill_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/backfill_screener_catalog_from_recent_runs.py"), doraise=True)

    def test_02_membership_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_membership_status.py"), doraise=True)

    def test_03_catalog_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_ticker_catalog_status.py"), doraise=True)

    def test_04_backfill_defaults_dry_run(self):
        src = (PROJECT_ROOT / "scripts/backfill_screener_catalog_from_recent_runs.py").read_text()
        self.assertIn("default=True", src)

    def test_05_backfill_requires_apply(self):
        src = (PROJECT_ROOT / "scripts/backfill_screener_catalog_from_recent_runs.py").read_text()
        self.assertIn("--apply", src)

    def test_06_no_silent_delete(self):
        src = (PROJECT_ROOT / "scripts/backfill_screener_catalog_from_recent_runs.py").read_text()
        self.assertNotIn("DELETE FROM", src)

    def test_07_no_trades(self):
        for f in ["backfill_screener_catalog_from_recent_runs.py", "report_screener_membership_status.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_08_membership_uses_upsert(self):
        src = (PROJECT_ROOT / "scripts/backfill_screener_catalog_from_recent_runs.py").read_text()
        self.assertIn("ON CONFLICT", src)

    def test_09_history_event_entered(self):
        src = (PROJECT_ROOT / "scripts/backfill_screener_catalog_from_recent_runs.py").read_text()
        self.assertIn("entered", src)
        self.assertIn("screener_symbol_membership_history", src)

    def test_10_arch3_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_screener_arch3_catalog_lifecycle.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)

    def test_11_arch2b_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_screener_arch2b_cap_overrides.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
