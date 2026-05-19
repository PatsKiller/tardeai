#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-3C membership lifecycle and API."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestTransitionScript(unittest.TestCase):
    def test_01_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/backfill_screener_membership_transitions.py"), doraise=True)

    def test_02_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_membership_status.py"), doraise=True)

    def test_03_catalog_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_ticker_catalog_status.py"), doraise=True)

    def test_04_falloff_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_and_apply_incubator_falloff_lifecycle.py"), doraise=True)

    def test_05_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestTransitionLogic(unittest.TestCase):
    def test_06_entered_transition(self):
        from backfill_screener_membership_transitions import classify_transitions
        prior = {}
        current = ["AAPL", "TSLA"]
        transitions = classify_transitions(prior, current, "run1", None, "screener")
        types = {t[1] for t in transitions}
        self.assertIn("entered", types)
        self.assertEqual(len(transitions), 2)

    def test_07_present_idempotent(self):
        from backfill_screener_membership_transitions import classify_transitions
        prior = {"AAPL": {"symbol": "AAPL", "membership_status": "present", "consecutive_missing_count": 0}}
        current = ["AAPL"]
        transitions = classify_transitions(prior, current, "run2", None, "screener")
        self.assertEqual(transitions[0][1], "present")

    def test_08_dropped_when_missing(self):
        from backfill_screener_membership_transitions import classify_transitions
        prior = {"AAPL": {"symbol": "AAPL", "membership_status": "present", "consecutive_missing_count": 0}}
        current = []
        transitions = classify_transitions(prior, current, "run2", None, "screener")
        self.assertEqual(transitions[0][1], "dropped")

    def test_09_stale_after_threshold(self):
        from backfill_screener_membership_transitions import classify_transitions, STALE_THRESHOLD
        prior = {"AAPL": {"symbol": "AAPL", "membership_status": "dropped", "consecutive_missing_count": STALE_THRESHOLD - 1}}
        current = []
        transitions = classify_transitions(prior, current, "run5", None, "screener")
        self.assertEqual(transitions[0][1], "stale")

    def test_10_expired_no_delete(self):
        from backfill_screener_membership_transitions import classify_transitions, EXPIRE_THRESHOLD
        prior = {"AAPL": {"symbol": "AAPL", "membership_status": "stale", "consecutive_missing_count": EXPIRE_THRESHOLD - 1}}
        current = []
        transitions = classify_transitions(prior, current, "run10", None, "screener")
        self.assertEqual(transitions[0][1], "expired")
        # No "delete" transition exists
        types = {t[1] for t in transitions}
        self.assertNotIn("delete", types)

    def test_11_reentered_from_dropped(self):
        from backfill_screener_membership_transitions import classify_transitions
        prior = {"AAPL": {"symbol": "AAPL", "membership_status": "dropped", "consecutive_missing_count": 1}}
        current = ["AAPL"]
        transitions = classify_transitions(prior, current, "run3", None, "screener")
        self.assertEqual(transitions[0][1], "reentered")

    def test_12_reentered_from_expired(self):
        from backfill_screener_membership_transitions import classify_transitions
        prior = {"AAPL": {"symbol": "AAPL", "membership_status": "expired", "consecutive_missing_count": 10}}
        current = ["AAPL"]
        transitions = classify_transitions(prior, current, "run11", None, "screener")
        self.assertEqual(transitions[0][1], "reentered")

    def test_13_multi_screener_active(self):
        """Symbol present in one screener remains active even if dropped in another."""
        from backfill_screener_membership_transitions import classify_transitions
        # screener1: dropped
        prior1 = {"AAPL": {"symbol": "AAPL", "membership_status": "present", "consecutive_missing_count": 0}}
        t1 = classify_transitions(prior1, [], "run2", None, "screener1")
        # screener2: still present
        prior2 = {"AAPL": {"symbol": "AAPL", "membership_status": "present", "consecutive_missing_count": 0}}
        t2 = classify_transitions(prior2, ["AAPL"], "run2", None, "screener2")
        # AAPL dropped in screener1 but present in screener2
        self.assertEqual(t1[0][1], "dropped")
        self.assertEqual(t2[0][1], "present")


class TestFalloffPolicy(unittest.TestCase):
    def test_14_active_in_sources(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state, classify_falloff_action
        cand = {"symbol": "AAPL", "strategy_id": "swing_breakout", "days_active": 5}
        memberships = [{"membership_status": "present", "present_this_run": True}]
        state = classify_source_membership_state(cand, memberships)
        self.assertEqual(state["state"], "active_in_sources")
        action = classify_falloff_action(cand, state)
        self.assertEqual(action["action"], "keep_active")

    def test_15_dropped_retain_by_ttl(self):
        from incubator_falloff_lifecycle_policy import classify_source_membership_state, classify_falloff_action
        cand = {"symbol": "AAPL", "strategy_id": "swing_breakout", "days_active": 3}
        memberships = [{"membership_status": "dropped", "present_this_run": False}]
        state = classify_source_membership_state(cand, memberships)
        self.assertEqual(state["state"], "dropped_from_all")
        action = classify_falloff_action(cand, state)
        self.assertEqual(action["action"], "retain_by_ttl")


class TestAPIContract(unittest.TestCase):
    def test_16_api_has_endpoints(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/ticker-catalog/summary", src)
        self.assertIn("/api/v2/screener-membership/summary", src)
        self.assertIn("/api/v2/incubator-lifecycle/summary", src)

    def test_17_endpoints_read_only(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # Find the three handler functions and verify no INSERT/UPDATE/DELETE
        for fn in ["_ticker_catalog_summary_api", "_screener_membership_summary_api", "_incubator_lifecycle_summary_api"]:
            start = src.index(f"def {fn}")
            end = src.index("\ndef ", start + 1)
            body = src[start:end]
            self.assertNotIn("INSERT", body)
            self.assertNotIn("UPDATE", body)
            self.assertNotIn("DELETE", body)


class TestSafety(unittest.TestCase):
    def test_18_no_trades(self):
        for script in ["backfill_screener_membership_transitions.py", "report_screener_membership_status.py",
                        "report_and_apply_incubator_falloff_lifecycle.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("create_order", src, f"{script} contains create_order")
            self.assertNotIn("submit_order", src, f"{script} contains submit_order")

    def test_19_no_strategy_activation(self):
        for script in ["backfill_screener_membership_transitions.py", "report_screener_membership_status.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("activate_strategy", src)

    def test_20_dashboard_exists(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperGovernance.tsx").read_text()
        self.assertIn("Scanner Catalog Lifecycle", src)
        self.assertIn("ticker-catalog/summary", src)
        self.assertIn("screener-membership/summary", src)

    def test_21_frontend_build_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("PaperGovernance-*.js")))


class TestRegression(unittest.TestCase):
    def test_22_arch3b_test_file_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch3b_importer_membership_backfill.py").exists())

    def test_23_arch3_test_file_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch3_catalog_lifecycle.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
