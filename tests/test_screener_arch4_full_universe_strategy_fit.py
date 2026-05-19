#!/usr/bin/env python3
"""Tests for SCREENER-ARCH-4 full universe strategy-fit audit."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_baseline_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_screener_arch4_universe_strategy_baseline.py"), doraise=True)

    def test_02_migration_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/migrate_screener_arch4_strategy_fit_audit.py"), doraise=True)

    def test_03_audit_engine_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_full_universe_strategy_fit_audit.py"), doraise=True)

    def test_04_coverage_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_fit_coverage.py"), doraise=True)

    def test_05_data_gaps_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_fit_data_gaps.py"), doraise=True)

    def test_06_verifier_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/verify_arch4_no_proposal_no_trade_mutation.py"), doraise=True)

    def test_07_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestRouterLogic(unittest.TestCase):
    def test_08_evaluate_strategy_match(self):
        from multi_setup_router import evaluate_strategy_match
        config = {
            "strategy_id": "test_strat",
            "entry_criteria": [{"id": "RVOL", "metric": "rvol", "operator": "gte", "value": 2.0}],
            "auto_disqualifiers": [],
            "scoring_weights": {"rvol": 20},
            "universe": {},
        }
        signal = {"rvol": 3.0, "price": 10, "symbol": "TEST"}
        result = evaluate_strategy_match(config, signal)
        self.assertIn(result["match_status"], ("STRONG_MATCH", "MODERATE_MATCH", "WEAK_MATCH"))
        self.assertTrue(result["scoring_weights_used"])

    def test_09_missing_data_handled(self):
        from multi_setup_router import evaluate_strategy_match
        config = {
            "strategy_id": "test_strat",
            "entry_criteria": [{"id": "RVOL", "metric": "rvol", "operator": "gte", "value": 2.0}],
            "auto_disqualifiers": [],
            "universe": {},
        }
        signal = {"symbol": "TEST"}  # no rvol
        result = evaluate_strategy_match(config, signal)
        self.assertIn("RVOL", result["missing_data"])

    def test_10_top_match_selected(self):
        from run_full_universe_strategy_fit_audit import evaluate_symbol, load_strategy_configs
        configs = load_strategy_configs()
        signal = {"symbol": "TEST", "rvol": 5.0, "price": 8.0, "change_pct": 15.0, "gap_pct": 5.0,
                  "float_m": 10.0, "volume": 5000000, "catalyst": "earnings beat", "catalyst_verified": True,
                  "sector": "Technology", "industry": "Software", "scanned_at": None}
        results = evaluate_symbol(signal, configs, None)
        top = [r for r in results if r.get("top_match_for_symbol")]
        self.assertEqual(len(top), 1)

    def test_11_blocked_by_disqualifier(self):
        from multi_setup_router import evaluate_strategy_match
        config = {
            "strategy_id": "test",
            "entry_criteria": [],
            "auto_disqualifiers": [{"id": "HIGH_FLOAT", "condition": "float_m > 100"}],
            "universe": {},
        }
        signal = {"float_m": 200, "symbol": "BIG"}
        result = evaluate_strategy_match(config, signal)
        self.assertTrue(result["is_blocked"])


class TestAuditSafety(unittest.TestCase):
    def test_12_no_proposals_in_engine(self):
        src = (PROJECT_ROOT / "scripts/run_full_universe_strategy_fit_audit.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)
        self.assertNotIn("approve_proposal", src)

    def test_13_no_trades_in_engine(self):
        src = (PROJECT_ROOT / "scripts/run_full_universe_strategy_fit_audit.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_14_human_review_only(self):
        src = (PROJECT_ROOT / "scripts/run_full_universe_strategy_fit_audit.py").read_text()
        self.assertIn("human_review_only", src)
        self.assertIn("TRUE", src)

    def test_15_api_read_only(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        start = src.index("def _strategy_fit_summary_api")
        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        self.assertNotIn("INSERT", body)
        self.assertNotIn("UPDATE", body)
        self.assertNotIn("DELETE", body)

    def test_16_api_has_endpoint(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/strategy-fit/summary", src)


class TestRegression(unittest.TestCase):
    def test_17_arch3c_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch3c_membership_lifecycle_api.py").exists())

    def test_18_ux1b_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_journal_ux1b_closed_trade_action_dashboard.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
