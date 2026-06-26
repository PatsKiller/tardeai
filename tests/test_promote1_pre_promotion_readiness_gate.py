#!/usr/bin/env python3
"""Tests for PROMOTE-1 Pre-Promotion Readiness Gate."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPrePromotionPolicy(unittest.TestCase):

    def test_01_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/pre_promotion_readiness_policy.py"), doraise=True)

    def test_02_rr_below_minimum_blocked(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "proposed_entry": 3.91, "proposed_stop": 3.71, "proposed_target1": 4.3,
            "proposed_rr": 1.95, "strategy_id": "momentum_scalp"
        })
        self.assertTrue(any("rr_below" in b for b in r["blockers"]))
        self.assertFalse(r["promote_ready"])

    def test_03_unknown_provider_warns(self):
        # Without quote data the gate blocks (quote_never_checked); fresh quote age passes with warnings only.
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "strategy_id": "momentum_scalp",
            "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
            "quote_age_hours": 0.1,
        })
        self.assertTrue(r["promote_ready"])

    def test_04_price_moved_blocked(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "proposed_entry": 3.91, "proposed_stop": 3.71, "proposed_target1": 4.5,
            "quote_price": 4.46, "strategy_id": "momentum_scalp"
        })
        self.assertTrue(any("price_moved" in b for b in r["blockers"]))

    def test_05_invalid_strategy_blocked(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({"strategy_id": "screener", "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12})
        self.assertTrue(any("invalid_strategy" in b for b in r["blockers"]))

    def test_06_spread_too_wide_blocked(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
            "spread_pct": 15.0, "strategy_family": "INTRADAY_MOMENTUM", "strategy_id": "momentum_scalp"
        })
        self.assertTrue(any("spread_too_wide" in b for b in r["blockers"]))

    def test_07_daily_scalp_blocked(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({"discovery_source": "daily_momentum_scalp", "strategy_id": "x"})
        self.assertTrue(any("out_of_scope" in b for b in r["blockers"]))


class TestWiring(unittest.TestCase):

    def test_08_promoter_calls_pre_promotion(self):
        src = (PROJECT_ROOT / "scripts/incubator_proposal_promoter.py").read_text()
        self.assertIn("pre_promotion_readiness_policy", src)
        self.assertIn("evaluate_pre_promotion_readiness", src)
        self.assertIn("BLOCKED_PRE_PROMOTION", src)

    def test_09_auto_gen_calls_pre_promotion(self):
        src = (PROJECT_ROOT / "scripts/auto_proposal_generator.py").read_text()
        self.assertIn("pre_promotion_readiness_policy", src)
        self.assertIn("evaluate_pre_promotion_readiness", src)

    def test_10_promoter_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/incubator_proposal_promoter.py"), doraise=True)

    def test_11_auto_gen_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/auto_proposal_generator.py"), doraise=True)


class TestSafety(unittest.TestCase):

    def test_12_no_trade_creation(self):
        src = (PROJECT_ROOT / "scripts/pre_promotion_readiness_policy.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_13_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/pre_promotion_readiness_policy.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_14_q1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_q1_proactive_quote_refresh.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"Q-1 tests failed:\n{r.stderr}")

    def test_15_sp2c_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_sp2c_route_audit_pipeline_wiring.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"SP-2C tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
