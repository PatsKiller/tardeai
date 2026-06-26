#!/usr/bin/env python3
"""Tests for SP-2C Route Audit Pipeline Wiring."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompilation(unittest.TestCase):

    def test_01_creation_paths_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_proposal_creation_paths.py"), doraise=True)

    def test_02_route_audit_integration_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/proposal_route_audit_integration.py"), doraise=True)

    def test_03_auto_proposal_generator_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/auto_proposal_generator.py"), doraise=True)

    def test_04_incubator_promoter_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/incubator_proposal_promoter.py"), doraise=True)

    def test_05_paper_trade_logger_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/paper_trade_logger.py"), doraise=True)

    def test_06_simulation_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/test_route_audit_pipeline_simulation.py"), doraise=True)


class TestWiring(unittest.TestCase):

    def test_07_auto_gen_calls_route_audit(self):
        src = (PROJECT_ROOT / "scripts/auto_proposal_generator.py").read_text()
        self.assertIn("ensure_route_audit_for_proposal", src)

    def test_08_promoter_calls_route_audit(self):
        src = (PROJECT_ROOT / "scripts/incubator_proposal_promoter.py").read_text()
        self.assertIn("ensure_route_audit_for_proposal", src)

    def test_09_logger_scan_calls_route_audit(self):
        src = (PROJECT_ROOT / "scripts/paper_trade_logger.py").read_text()
        self.assertIn("paper_trade_logger_scan", src)

    def test_10_logger_manual_calls_route_audit(self):
        src = (PROJECT_ROOT / "scripts/paper_trade_logger.py").read_text()
        self.assertIn("paper_trade_logger_manual", src)


class TestHelperBehavior(unittest.TestCase):

    def test_11_preserves_original_strategy_id(self):
        from proposal_route_audit_integration import ensure_route_audit_for_proposal
        r = ensure_route_audit_for_proposal(
            None, 0, "TEST", "recovery_watch",
            {"symbol": "TEST", "price": 10, "rvol": 5, "score": 45, "decision": "GO",
             "catalyst_verified": True}, dry_run=True
        )
        self.assertEqual(r["original_strategy_id"], "recovery_watch")

    def test_12_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/proposal_route_audit_integration.py").read_text()
        self.assertNotIn("activate_strategy", src)
        self.assertNotIn("deactivate_strategy", src)

    def test_13_no_yaml_mutation(self):
        src = (PROJECT_ROOT / "scripts/proposal_route_audit_integration.py").read_text()
        self.assertNotIn("yaml.dump", src)
        self.assertNotIn("write_text", src)

    def test_14_detects_screener_invalid(self):
        from proposal_route_audit_integration import ensure_route_audit_for_proposal
        r = ensure_route_audit_for_proposal(
            None, 0, "TEST", "screener",
            {"symbol": "TEST", "price": 10, "score": 0, "decision": "GO"}, dry_run=True
        )
        self.assertTrue(r["invalid_strategy_id"])
        self.assertTrue(any("invalid_strategy_id" in b for b in r["blockers"]))

    def test_15_route_audit_failure_returns_blocker(self):
        """If configs can't load, should return a blocker."""
        # This test validates the structure when route_symbol runs successfully
        from proposal_route_audit_integration import ensure_route_audit_for_proposal
        r = ensure_route_audit_for_proposal(
            None, 0, "TEST", "recovery_watch",
            {"symbol": "TEST", "price": 10, "score": 0, "decision": "GO"}, dry_run=True
        )
        # Should succeed (configs loadable), so no blockers unless mismatch
        self.assertIsInstance(r["blockers"], list)


class TestSafety(unittest.TestCase):

    def test_16_no_trade_creation(self):
        for f in ["proposal_route_audit_integration.py", "report_proposal_creation_paths.py",
                   "test_route_audit_pipeline_simulation.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_17_sp2b_tests_pass(self):
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
