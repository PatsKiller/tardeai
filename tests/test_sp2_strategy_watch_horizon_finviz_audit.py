#!/usr/bin/env python3
"""Tests for SP-2 Strategy Watch Horizon and Finviz Screener Audit."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestWatchHorizonPolicy(unittest.TestCase):

    def test_01_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/strategy_watch_horizon_policy.py"), doraise=True)

    def test_02_recovery_watch_multi_day(self):
        from strategy_watch_horizon_policy import get_default_watch_horizon
        h = get_default_watch_horizon("recovery_watch")
        self.assertGreaterEqual(h["min_days"], 5)
        self.assertLessEqual(h["max_days"], 30)
        self.assertTrue(h["catalyst_required"])
        self.assertTrue(h["fib_required"])

    def test_03_momentum_scalp_intraday(self):
        from strategy_watch_horizon_policy import get_default_watch_horizon
        h = get_default_watch_horizon("momentum_scalp")
        self.assertEqual(h["min_days"], 0)
        self.assertLessEqual(h["max_days"], 3)
        self.assertTrue(h["orb_required"])

    def test_04_dividend_long_horizon(self):
        from strategy_watch_horizon_policy import get_default_watch_horizon
        h = get_default_watch_horizon("dividend_growth_compounder")
        self.assertGreaterEqual(h["max_days"], 90)

    def test_05_classify_new_candidate(self):
        from strategy_watch_horizon_policy import classify_candidate_watch_state
        r = classify_candidate_watch_state({"age_days": 0}, "recovery_watch")
        self.assertEqual(r["watch_state"], "new_candidate")

    def test_06_classify_expired(self):
        from strategy_watch_horizon_policy import classify_candidate_watch_state
        r = classify_candidate_watch_state({"age_days": 100}, "recovery_watch")
        self.assertEqual(r["watch_state"], "expired")

    def test_07_recommend_action_human_review(self):
        from strategy_watch_horizon_policy import recommend_watch_action
        r = recommend_watch_action({"age_days": 5}, "recovery_watch")
        self.assertTrue(r["human_review_only"])


class TestReportScripts(unittest.TestCase):

    def test_08_watch_horizon_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_watch_horizon.py"), doraise=True)

    def test_09_finviz_screener_quality_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_finviz_screener_quality.py"), doraise=True)

    def test_10_strategy_assignment_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_assignment_engine_audit.py"), doraise=True)

    def test_11_no_db_writes(self):
        for f in ["report_strategy_watch_horizon.py", "report_finviz_screener_quality.py",
                   "report_strategy_assignment_engine_audit.py", "strategy_watch_horizon_policy.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("INSERT INTO", src, f"{f} has INSERT")
            self.assertNotIn("UPDATE ", src, f"{f} has UPDATE")
            self.assertNotIn("DELETE FROM", src, f"{f} has DELETE")

    def test_12_no_strategy_activation(self):
        for f in ["report_strategy_watch_horizon.py", "report_finviz_screener_quality.py",
                   "report_strategy_assignment_engine_audit.py", "strategy_watch_horizon_policy.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("activate_strategy", src)
            self.assertNotIn("deactivate_strategy", src)

    def test_13_no_yaml_mutation(self):
        for f in ["report_strategy_watch_horizon.py", "report_finviz_screener_quality.py",
                   "report_strategy_assignment_engine_audit.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("yaml.dump", src)
            self.assertNotIn("write_text", src.split("output_json")[0] if "output_json" in src else "")

    def test_14_no_trade_creation(self):
        for f in ["report_strategy_watch_horizon.py", "report_finviz_screener_quality.py",
                   "report_strategy_assignment_engine_audit.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_15_no_secrets_printed(self):
        for f in ["report_finviz_screener_quality.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("API_KEY", src)
            self.assertNotIn("finviz_url", src.lower().split("output")[0] if "output" in src else src)

    def test_16_existing_sp1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_sp1_strategy_proof_governance.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60
        )
        self.assertEqual(r.returncode, 0, f"SP-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
