#!/usr/bin/env python3
"""Tests for POST-AUDIT-OPS-1 remaining backend fixes."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_regime(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_regime_cron1_staleness.py"), doraise=True)

    def test_02_overnight(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_llm_fix1_overnight_fallback.py"), doraise=True)

    def test_03_agent(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_agent_fix1_queue_health.py"), doraise=True)

    def test_04_count(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_count_truth1_drift_contract.py"), doraise=True)

    def test_05_attr(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_attr1_benchmark_alpha.py"), doraise=True)

    def test_06_smoke(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_post_audit_ops1_integration_smoke.py"), doraise=True)


class TestSafety(unittest.TestCase):
    def test_07_no_trades(self):
        for f in ["report_regime_cron1_staleness.py", "report_llm_fix1_overnight_fallback.py",
                   "report_agent_fix1_queue_health.py", "report_count_truth1_drift_contract.py",
                   "report_attr1_benchmark_alpha.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src, f"{f} has create_order")
            self.assertNotIn("submit_order", src, f"{f} has submit_order")


class TestDocs(unittest.TestCase):
    def test_08_readme_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/operator_hygiene/phase_post_audit_ops1_remaining_backend_fixes/00_README.md").exists())

    def test_09_safety_audit_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/operator_hygiene/phase_post_audit_ops1_remaining_backend_fixes/post_audit_ops1_safety_audit.md").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
