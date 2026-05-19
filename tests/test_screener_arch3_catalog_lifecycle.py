#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-3 ticker catalog lifecycle."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestMigration(unittest.TestCase):
    def test_01_migration_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/migrate_screener_arch3_catalog_lifecycle.py"), doraise=True)

    def test_02_catalog_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_ticker_catalog_status.py"), doraise=True)


class TestFalloffPolicy(unittest.TestCase):
    def test_03_falloff_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/incubator_falloff_lifecycle_policy.py"), doraise=True)

    def test_04_active_in_sources(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state
        r = classify_source_membership_state({}, [{"present_this_run": True, "membership_status": "present"}])
        self.assertEqual(r["state"], "active_in_sources")

    def test_05_dropped_from_all(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state
        r = classify_source_membership_state({}, [{"present_this_run": False, "membership_status": "dropped"}])
        self.assertEqual(r["state"], "dropped_from_all")

    def test_06_retain_by_ttl(self):
        from incubator_falloff_lifecycle_policy import classify_falloff_action
        r = classify_falloff_action(
            {"strategy_id": "swing_breakout", "days_active": 5},
            {"state": "dropped_from_all"}
        )
        self.assertEqual(r["action"], "retain_by_ttl")

    def test_07_expire_after_ttl(self):
        from incubator_falloff_lifecycle_policy import classify_falloff_action
        r = classify_falloff_action(
            {"strategy_id": "momentum_scalp", "days_active": 10},
            {"state": "dropped_from_all"}
        )
        self.assertEqual(r["action"], "expire")

    def test_08_no_silent_delete(self):
        from incubator_falloff_lifecycle_policy import classify_falloff_action
        for state in ["active_in_sources", "dropped_from_all", "stale_all_sources", "no_membership_data", "unknown"]:
            r = classify_falloff_action({"strategy_id": "x", "days_active": 1}, {"state": state})
            self.assertNotEqual(r["action"], "delete")

    def test_09_human_review_only(self):
        from incubator_falloff_lifecycle_policy import classify_falloff_action
        r = classify_falloff_action({"strategy_id": "x", "days_active": 1}, {"state": "dropped_from_all"})
        self.assertTrue(r["human_review_only"])


class TestSafety(unittest.TestCase):
    def test_10_no_trades(self):
        for f in ["incubator_falloff_lifecycle_policy.py", "report_ticker_catalog_status.py", "migrate_screener_arch3_catalog_lifecycle.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_11_migration_non_destructive(self):
        src = (PROJECT_ROOT / "scripts/migrate_screener_arch3_catalog_lifecycle.py").read_text()
        self.assertNotIn("DROP TABLE", src)
        self.assertNotIn("DROP INDEX", src)
        self.assertIn("IF NOT EXISTS", src)

    def test_12_arch2b_tests_pass(self):
        import subprocess
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_screener_arch2b_cap_overrides.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
