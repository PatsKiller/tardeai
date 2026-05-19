#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-3D falloff lifecycle apply."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_baseline_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_arch3d_baseline.py"), doraise=True)

    def test_02_falloff_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_and_apply_incubator_falloff_lifecycle.py"), doraise=True)

    def test_03_catalog_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_ticker_catalog_status.py"), doraise=True)

    def test_04_membership_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_membership_status.py"), doraise=True)

    def test_05_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestFalloffPolicy(unittest.TestCase):
    def test_06_active_stays_active(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state, classify_falloff_action
        cand = {"symbol": "X", "strategy_id": "swing_breakout", "days_active": 5}
        state = classify_source_membership_state(cand, [{"membership_status": "present", "present_this_run": True}])
        action = classify_falloff_action(cand, state)
        self.assertEqual(action["action"], "keep_active")

    def test_07_dropped_retains_by_ttl(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state, classify_falloff_action
        cand = {"symbol": "X", "strategy_id": "swing_breakout", "days_active": 3}
        state = classify_source_membership_state(cand, [{"membership_status": "dropped", "present_this_run": False}])
        action = classify_falloff_action(cand, state)
        self.assertEqual(action["action"], "retain_by_ttl")

    def test_08_no_data_retains(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state, classify_falloff_action
        cand = {"symbol": "X", "strategy_id": "swing_breakout", "days_active": 5}
        state = classify_source_membership_state(cand, [])
        action = classify_falloff_action(cand, state)
        self.assertEqual(action["action"], "retain_no_data")


class TestLifecycleClassification(unittest.TestCase):
    def test_09_classify_active(self):
        from report_and_apply_incubator_falloff_lifecycle import classify_lifecycle_state
        self.assertEqual(classify_lifecycle_state("keep_active", "active_in_sources"), "active")

    def test_10_classify_source_missing(self):
        from report_and_apply_incubator_falloff_lifecycle import classify_lifecycle_state
        self.assertEqual(classify_lifecycle_state("retain_by_ttl", "dropped_from_all"), "source_missing")

    def test_11_classify_expired(self):
        from report_and_apply_incubator_falloff_lifecycle import classify_lifecycle_state
        self.assertEqual(classify_lifecycle_state("expire", "dropped_from_all"), "expired_pending_operator_review")

    def test_12_classify_needs_refresh(self):
        from report_and_apply_incubator_falloff_lifecycle import classify_lifecycle_state
        self.assertEqual(classify_lifecycle_state("retain_no_data", "no_membership_data"), "needs_refresh")


class TestOperatorGates(unittest.TestCase):
    def test_13_expire_requires_flag(self):
        """Script source must check --operator-approved-expire before expiring."""
        src = (PROJECT_ROOT / "scripts/report_and_apply_incubator_falloff_lifecycle.py").read_text()
        self.assertIn("operator_approved_expire", src)
        self.assertIn("expire_blocked_no_flag", src)

    def test_14_archive_requires_flag(self):
        src = (PROJECT_ROOT / "scripts/report_and_apply_incubator_falloff_lifecycle.py").read_text()
        self.assertIn("operator_approved_archive", src)

    def test_15_no_delete_in_script(self):
        src = (PROJECT_ROOT / "scripts/report_and_apply_incubator_falloff_lifecycle.py").read_text()
        self.assertNotIn("DELETE FROM incubator_universe", src)
        self.assertNotIn("DROP TABLE", src)


class TestSafety(unittest.TestCase):
    def test_16_no_trades(self):
        for script in ["report_and_apply_incubator_falloff_lifecycle.py", "report_screener_arch3d_baseline.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_17_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/report_and_apply_incubator_falloff_lifecycle.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_18_human_review_only(self):
        from incubator_falloff_lifecycle_policy import classify_falloff_action
        cand = {"symbol": "X", "strategy_id": "s", "days_active": 100}
        state = {"state": "dropped_from_all", "present_count": 0, "dropped_count": 1}
        action = classify_falloff_action(cand, state)
        self.assertTrue(action.get("human_review_only", False))

    def test_19_api_read_only(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        for fn in ["_ticker_catalog_summary_api", "_screener_membership_summary_api", "_incubator_lifecycle_summary_api"]:
            start = src.index(f"def {fn}")
            end = src.index("\ndef ", start + 1)
            body = src[start:end]
            self.assertNotIn("INSERT", body)
            self.assertNotIn("UPDATE", body)
            self.assertNotIn("DELETE", body)


class TestRegression(unittest.TestCase):
    def test_20_arch3c_tests_exist(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch3c_membership_lifecycle_api.py").exists())

    def test_21_arch3b_tests_exist(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch3b_importer_membership_backfill.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
