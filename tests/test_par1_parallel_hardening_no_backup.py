#!/usr/bin/env python3
"""Tests for PAR-1 Parallel Hardening (no backup work)."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompilation(unittest.TestCase):

    def test_01_quote_freshness_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_quote_freshness_provider_audit.py"), doraise=True)

    def test_02_route_mismatch_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_route_mismatch_human_review.py"), doraise=True)

    def test_03_source_attribution_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_proposal_source_attribution.py"), doraise=True)

    def test_04_watchpool_status_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_bucket2_watchpool_status.py"), doraise=True)

    def test_05_morning_packet_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_operator_morning_packet.py"), doraise=True)

    def test_06_regression_runner_exists(self):
        runner = PROJECT_ROOT / "scripts/run_tradeai_regression.sh"
        self.assertTrue(runner.exists())
        import os
        self.assertTrue(os.access(str(runner), os.X_OK))

    def test_07_invalid_strategy_design_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/parallel_hardening/phase_par1_no_backup/par1_invalid_strategy_workflow_design.md").exists())


class TestSafety(unittest.TestCase):

    def test_08_no_backup_scripts(self):
        """PAR-1 scripts must not perform backup/encryption operations."""
        for f in ["report_quote_freshness_provider_audit.py", "report_route_mismatch_human_review.py",
                   "report_proposal_source_attribution.py", "report_bucket2_watchpool_status.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("backup", src.lower())
            self.assertNotIn("encrypt", src.lower())
        # Morning packet may reference backup_note (status note, not backup operation)
        mp_src = (PROJECT_ROOT / "scripts/report_operator_morning_packet.py").read_text()
        self.assertNotIn("encrypt", mp_src.lower())
        self.assertNotIn("upload_backup", mp_src.lower())

    def test_09_no_secrets_for_upload(self):
        for f in ["report_operator_morning_packet.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("API_KEY", src)
            self.assertNotIn("print(env", src)

    def test_10_no_strategy_activation(self):
        for f in ["report_quote_freshness_provider_audit.py", "report_route_mismatch_human_review.py",
                   "report_proposal_source_attribution.py", "report_bucket2_watchpool_status.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("activate_strategy", src)

    def test_11_no_yaml_mutation(self):
        for f in ["report_route_mismatch_human_review.py", "report_proposal_source_attribution.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("yaml.dump", src)

    def test_12_no_trade_creation(self):
        for f in ["report_quote_freshness_provider_audit.py", "report_route_mismatch_human_review.py",
                   "report_proposal_source_attribution.py", "report_bucket2_watchpool_status.py",
                   "report_operator_morning_packet.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_13_scalp_boundary_maintained(self):
        src = (PROJECT_ROOT / "scripts/report_proposal_source_attribution.py").read_text()
        self.assertIn("daily_momentum_scalp", src)
        self.assertIn("BLOCKED_SOURCES", src)

    def test_14_recommendations_human_review(self):
        src = (PROJECT_ROOT / "scripts/report_route_mismatch_human_review.py").read_text()
        self.assertIn("human_review_only", src)

    def test_15_regression_runner_checks_safety(self):
        src = (PROJECT_ROOT / "scripts/run_tradeai_regression.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)
        self.assertIn("LLM_DISABLE", src)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
