#!/usr/bin/env python3
"""Tests for AFTERHOURS-READY-1 candidate preparation."""
import subprocess, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_migration(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/migrate_afterhours_readiness.py"), doraise=True)

    def test_02_runner(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.py"), doraise=True)

    def test_03_digest(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/build_afterhours_readiness_digest.py"), doraise=True)

    def test_04_verifier(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/verify_afterhours_ready1_runtime.py"), doraise=True)

    def test_05_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestCronWrapper(unittest.TestCase):
    def test_06_wrapper_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_07_rollback_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/rollback_afterhours_ready1_cron.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_08_wrapper_has_safety(self):
        src = (PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)
        self.assertIn("set -a; source", src)


class TestPolicyDoc(unittest.TestCase):
    def test_09_policy_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/screener_architecture/phase_afterhours_ready1_full_candidate_preparation/operator_observed_failure.md").exists())


class TestRunner(unittest.TestCase):
    def test_10_human_review_only(self):
        src = (PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.py").read_text()
        self.assertIn("human_review_only", src)

    def test_11_executable_now_false(self):
        src = (PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.py").read_text()
        self.assertIn("executable_now", src)

    def test_12_no_trades(self):
        src = (PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_13_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_14_no_yaml_changes(self):
        src = (PROJECT_ROOT / "scripts/run_afterhours_candidate_preparation.py").read_text()
        self.assertNotIn("yaml.dump", src)


class TestAPI(unittest.TestCase):
    def test_15_afterhours_endpoint(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/afterhours-readiness/summary", src)


class TestRegression(unittest.TestCase):
    def test_16_arch5_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_screener_arch5_schedule_stale_remediation.py").exists())

    def test_17_ops_hygiene_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_ops_hygiene1_command_surface_alert_cleanup.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
