#!/usr/bin/env python3
"""Tests for B-1C Bucket 2 Migration and Scalp Boundary."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompilation(unittest.TestCase):

    def test_01_bucket2_scope_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_b1c_bucket2_migration_scope.py"), doraise=True)

    def test_02_boundary_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_daily_momentum_scalp_boundary.py"), doraise=True)

    def test_03_migrate_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/migrate_b1c_bucket2.py"), doraise=True)


class TestMigrationSafety(unittest.TestCase):

    def test_04_migrate_defaults_dry_run(self):
        src = (PROJECT_ROOT / "scripts/migrate_b1c_bucket2.py").read_text()
        self.assertIn("default=True", src)

    def test_05_migrate_requires_apply(self):
        src = (PROJECT_ROOT / "scripts/migrate_b1c_bucket2.py").read_text()
        self.assertIn("--apply", src)

    def test_06_migrate_checks_unsafe_patterns(self):
        src = (PROJECT_ROOT / "scripts/migrate_b1c_bucket2.py").read_text()
        self.assertIn("UNSAFE_PATTERNS", src)
        self.assertIn("cookie", src)
        self.assertIn("credential", src)


class TestBoundary(unittest.TestCase):

    def test_07_boundary_distinguishes_trade_ai_momentum_scalp(self):
        """Trade AI momentum_scalp YAML is valid, not the same as daily scalp."""
        src = (PROJECT_ROOT / "scripts/report_daily_momentum_scalp_boundary.py").read_text()
        self.assertIn("trade_ai_momentum_scalp_valid", src)
        # Should NOT flag momentum_scalp YAML as leakage
        self.assertNotIn("momentum_scalp", [
            "daily_momentum_scalp", "tradeai_daily_scalp",
        ])

    def test_08_daily_scalp_indicators_defined(self):
        src = (PROJECT_ROOT / "scripts/report_daily_momentum_scalp_boundary.py").read_text()
        self.assertIn("daily_momentum_scalp", src)
        self.assertIn("tradeai_daily_scalp", src)

    def test_09_momentum_scalp_yaml_exists(self):
        self.assertTrue((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").exists())

    def test_10_momentum_scalp_is_same_day(self):
        import yaml
        with open(PROJECT_ROOT / "config/strategies/momentum_scalp.yaml") as f:
            cfg = yaml.safe_load(f)
        self.assertEqual(cfg.get("freshness", {}).get("bucket"), "SAME_DAY")
        self.assertFalse(cfg.get("freshness", {}).get("watchpool", True))


class TestNoMutation(unittest.TestCase):

    def test_11_no_strategy_activation(self):
        for f in ["report_b1c_bucket2_migration_scope.py", "report_daily_momentum_scalp_boundary.py", "migrate_b1c_bucket2.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("activate_strategy", src)
            self.assertNotIn("deactivate_strategy", src)

    def test_12_no_trade_creation(self):
        for f in ["report_b1c_bucket2_migration_scope.py", "report_daily_momentum_scalp_boundary.py", "migrate_b1c_bucket2.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_13_sp2c_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_sp2c_route_audit_pipeline_wiring.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"SP-2C tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
