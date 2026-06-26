#!/usr/bin/env python3
"""Tests for R-2 Family and Liquidity Gating."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestGatePolicies(unittest.TestCase):

    def test_01_eligibility_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/strategy_eligibility_gate_policy.py"), doraise=True)

    def test_02_family_gate_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/strategy_family_gate_policy.py"), doraise=True)

    def test_03_router_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/multi_setup_router.py"), doraise=True)

    def test_04_intraday_not_routed_to_compounder(self):
        from strategy_family_gate_policy import family_gate_allows_strategy
        candidate = {"price": 5.0, "rvol": 8.0, "gap_pct": 5.0}
        config = {"strategy_id": "dividend_growth_compounder"}
        r = family_gate_allows_strategy(candidate, config)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["status"], "BLOCK")

    def test_05_compounder_not_routed_to_intraday(self):
        from strategy_family_gate_policy import family_gate_allows_strategy
        candidate = {"price": 150.0, "float_m": 500.0, "rvol": 0.5}
        config = {"strategy_id": "momentum_scalp"}
        r = family_gate_allows_strategy(candidate, config)
        self.assertFalse(r["allowed"])

    def test_06_low_price_blocked(self):
        from strategy_eligibility_gate_policy import evaluate_liquidity_eligibility
        r = evaluate_liquidity_eligibility({"price": 0.5}, "INTRADAY")
        self.assertFalse(r["eligible"])

    def test_07_stale_quote_blocked(self):
        from strategy_eligibility_gate_policy import evaluate_quote_eligibility
        r = evaluate_quote_eligibility({"execution_readiness": {"quote_age_seconds": 100000}})
        self.assertFalse(r["eligible"])

    def test_08_family_blocked_cannot_win(self):
        from multi_setup_router import route_symbol
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
        signal = {"symbol": "T", "price": 5.0, "rvol": 8.0, "gap_pct": 5.0,
                  "catalyst": "t", "catalyst_verified": True, "strategy_id": "momentum_scalp"}
        r = route_symbol("T", signal, configs)
        # DIVIDEND_CORE_COMPOUNDER should be blocked, not in secondaries
        for sid in r["secondary_strategy_ids"]:
            self.assertNotIn(sid, ["dividend_growth_compounder", "bond_income", "cash_or_stable", "core_index"])

    def test_09_yaml_weights_still_used(self):
        from multi_setup_router import evaluate_strategy_match
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config("momentum_scalp")
        signal = {"symbol": "T", "price": 5.0, "rvol": 5.0}
        r = evaluate_strategy_match(cfg, signal)
        self.assertTrue(r["scoring_weights_used"])

    def test_10_route_audit_has_family(self):
        from multi_setup_router import route_symbol
        from strategy_config_loader import load_all_strategy_configs
        r = route_symbol("T", {"symbol": "T", "price": 5.0, "rvol": 5.0, "strategy_id": "momentum_scalp"},
                         load_all_strategy_configs())
        self.assertIn("candidate_family", r)
        for m in r["setup_stack"][:3]:
            self.assertIn("candidate_family", m)
            self.assertIn("strategy_family", m)


class TestSafety(unittest.TestCase):

    def test_11_no_yaml_mutation(self):
        for f in ["strategy_eligibility_gate_policy.py", "strategy_family_gate_policy.py", "multi_setup_router.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("yaml.dump", src)

    def test_12_no_strategy_activation(self):
        for f in ["strategy_eligibility_gate_policy.py", "strategy_family_gate_policy.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("activate_strategy", src)

    def test_13_no_trade_creation(self):
        for f in ["strategy_eligibility_gate_policy.py", "strategy_family_gate_policy.py",
                   "report_router_family_gating_shadow_comparison.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_14_r5_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_r5_yaml_scoring_weights_router.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"R-5 tests failed:\n{r.stderr}")

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
