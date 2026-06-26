#!/usr/bin/env python3
"""Tests for SP-2B Route Audit Backfill and Strategy Assignment Repair."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompilation(unittest.TestCase):

    def test_01_root_cause_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_route_audit_root_cause.py"), doraise=True)

    def test_02_backfill_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/backfill_proposal_route_audit.py"), doraise=True)

    def test_03_invalid_assignments_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_invalid_strategy_assignments.py"), doraise=True)

    def test_04_config_drift_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_config_drift.py"), doraise=True)

    def test_05_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestBackfillSafety(unittest.TestCase):

    def test_06_backfill_defaults_dry_run(self):
        src = (PROJECT_ROOT / "scripts/backfill_proposal_route_audit.py").read_text()
        self.assertIn("default=True", src)  # dry_run default
        self.assertIn("--apply", src)

    def test_07_backfill_no_proposal_strategy_change(self):
        src = (PROJECT_ROOT / "scripts/backfill_proposal_route_audit.py").read_text()
        # Must not contain UPDATE paper_trade_proposals SET strategy_id
        self.assertNotIn("UPDATE paper_trade_proposals", src)

    def test_08_backfill_no_strategy_activation(self):
        for f in ["backfill_proposal_route_audit.py", "report_route_audit_root_cause.py",
                   "report_invalid_strategy_assignments.py", "report_strategy_config_drift.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("activate_strategy", src)
            self.assertNotIn("deactivate_strategy", src)

    def test_09_reports_no_db_writes(self):
        for f in ["report_route_audit_root_cause.py", "report_invalid_strategy_assignments.py",
                   "report_strategy_config_drift.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("INSERT INTO", src)
            self.assertNotIn("UPDATE ", src)
            self.assertNotIn("DELETE FROM", src)


class TestInvalidDetection(unittest.TestCase):

    def test_10_detects_screener_strategy(self):
        """The invalid strategy report must check against YAML configs."""
        src = (PROJECT_ROOT / "scripts/report_invalid_strategy_assignments.py").read_text()
        self.assertIn("load_all_strategy_configs", src)
        self.assertIn("valid_ids", src)

    def test_11_api_has_route_audit_blocker(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("route_audit", src)
        self.assertIn("Route audit missing", src)

    def test_12_api_has_invalid_strategy_blocker(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("invalid_strategy", src)
        self.assertIn("not a valid YAML strategy", src)


class TestNoMutation(unittest.TestCase):

    def test_13_no_trade_creation(self):
        for f in ["backfill_proposal_route_audit.py", "report_route_audit_root_cause.py",
                   "report_invalid_strategy_assignments.py", "report_strategy_config_drift.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_14_no_yaml_mutation(self):
        for f in ["backfill_proposal_route_audit.py", "report_route_audit_root_cause.py",
                   "report_invalid_strategy_assignments.py", "report_strategy_config_drift.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("yaml.dump", src)

    def test_15_no_screener_mutation(self):
        for f in ["backfill_proposal_route_audit.py", "report_route_audit_root_cause.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("UPDATE screener_config", src)
            self.assertNotIn("UPDATE finviz_screeners", src)


class TestRegression(unittest.TestCase):

    def test_16_sp2_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_sp2_strategy_watch_horizon_finviz_audit.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60
        )
        self.assertEqual(r.returncode, 0, f"SP-2 tests failed:\n{r.stderr}")

    def test_17_ppux2_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_pp_ux2_proposal_trust_audit.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"PP-UX-2 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
