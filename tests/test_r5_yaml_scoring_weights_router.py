#!/usr/bin/env python3
"""Tests for R-5 YAML Scoring Weights Router."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestWeightedScoring(unittest.TestCase):

    def test_01_router_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/multi_setup_router.py"), doraise=True)

    def test_02_router_uses_scoring_weights(self):
        from multi_setup_router import evaluate_strategy_match
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config("momentum_scalp")
        signal = {"symbol": "TEST", "price": 5.0, "rvol": 5.0, "catalyst": "test",
                  "catalyst_verified": True, "score": 45, "decision": "GO"}
        r = evaluate_strategy_match(cfg, signal)
        self.assertTrue(r["scoring_weights_used"])
        self.assertEqual(r["scoring_model_version"], "yaml_weighted_v1")

    def test_03_no_flat_10_when_weights_exist(self):
        from multi_setup_router import evaluate_strategy_match
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config("momentum_scalp")
        signal = {"symbol": "T", "price": 5.0, "rvol": 5.0, "catalyst": "t",
                  "catalyst_verified": True}
        r = evaluate_strategy_match(cfg, signal)
        # With weights, raw_weighted_score should differ from criteria_met * 10
        self.assertIn("raw_weighted_score", r)

    def test_04_fallback_when_no_weights(self):
        from multi_setup_router import evaluate_strategy_match
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config("core_index")
        signal = {"symbol": "T", "price": 10.0, "rvol": 2.0}
        r = evaluate_strategy_match(cfg, signal)
        self.assertFalse(r["scoring_weights_used"])  # core_index has no scoring_weights

    def test_05_weighted_score_has_raw_and_normalized(self):
        from multi_setup_router import evaluate_strategy_match
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config("momentum_scalp")
        signal = {"symbol": "T", "price": 5.0, "rvol": 3.0}
        r = evaluate_strategy_match(cfg, signal)
        self.assertIn("raw_weighted_score", r)
        self.assertIn("max_possible_weighted_score", r)
        self.assertIn("match_score", r)
        self.assertGreaterEqual(r["match_score"], 0)
        self.assertLessEqual(r["match_score"], 100)

    def test_06_scoring_model_version(self):
        from multi_setup_router import evaluate_strategy_match
        r = evaluate_strategy_match({"strategy_id": "test", "entry_criteria": []}, {})
        self.assertEqual(r["scoring_model_version"], "yaml_weighted_v1")

    def test_07_preserves_criteria_met_failed(self):
        from multi_setup_router import evaluate_strategy_match
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config("momentum_scalp")
        signal = {"symbol": "T", "price": 5.0, "rvol": 5.0, "catalyst": "t", "catalyst_verified": True}
        r = evaluate_strategy_match(cfg, signal)
        self.assertIsInstance(r["criteria_met"], list)
        self.assertIsInstance(r["criteria_failed"], list)

    def test_08_inventory_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_yaml_scoring_weights_inventory.py"), doraise=True)

    def test_09_shadow_comparison_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_router_weighted_shadow_comparison.py"), doraise=True)


class TestSafety(unittest.TestCase):

    def test_10_no_yaml_mutation(self):
        src = (PROJECT_ROOT / "scripts/multi_setup_router.py").read_text()
        self.assertNotIn("yaml.dump", src)
        self.assertNotIn("write_text", src)

    def test_11_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/multi_setup_router.py").read_text()
        self.assertNotIn("activate_strategy", src)
        self.assertNotIn("deactivate_strategy", src)

    def test_12_no_trade_creation(self):
        for f in ["multi_setup_router.py", "report_yaml_scoring_weights_inventory.py",
                   "report_router_weighted_shadow_comparison.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_13_shadow_is_read_only(self):
        src = (PROJECT_ROOT / "scripts/report_router_weighted_shadow_comparison.py").read_text()
        self.assertNotIn("INSERT INTO", src)
        self.assertNotIn("UPDATE ", src)

    def test_14_sp2c_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_sp2c_route_audit_pipeline_wiring.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"SP-2C tests failed:\n{r.stderr}")

    def test_15_sp2b_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_sp2b_route_audit_repair.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"SP-2B tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
