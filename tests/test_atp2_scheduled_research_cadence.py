#!/usr/bin/env python3
"""Tests for ATP-2 scheduled research cadence."""
import subprocess, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_inventory(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_atp2_research_cadence_inventory.py"), doraise=True)

    def test_02_cycle(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_atp2_research_cycle.py"), doraise=True)

    def test_03_revalidation(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_automated_trade_proposal_revalidation.py"), doraise=True)

    def test_04_dd_queue(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_candidate_due_diligence_queue.py"), doraise=True)


class TestWrapper(unittest.TestCase):
    def test_05_wrapper_exists(self):
        p = PROJECT_ROOT / "scripts/run_scheduled_atp2_research_cycle.sh"
        self.assertTrue(p.exists())
        self.assertTrue(p.stat().st_mode & 0o111)  # executable

    def test_06_rollback_exists(self):
        p = PROJECT_ROOT / "scripts/rollback_atp2_research_cron.sh"
        self.assertTrue(p.exists())
        self.assertTrue(p.stat().st_mode & 0o111)

    def test_07_wrapper_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/run_scheduled_atp2_research_cycle.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_08_rollback_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/rollback_atp2_research_cron.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_09_wrapper_checks_alpaca(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_atp2_research_cycle.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)

    def test_10_wrapper_checks_llm_disable(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_atp2_research_cycle.sh").read_text()
        self.assertIn("LLM_DISABLE", src)

    def test_11_wrapper_uses_flock(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_atp2_research_cycle.sh").read_text()
        self.assertIn("flock", src)


class TestSafety(unittest.TestCase):
    def test_12_no_trades(self):
        for f in ["run_atp2_research_cycle.py", "run_automated_trade_proposal_revalidation.py", "report_candidate_due_diligence_queue.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src, f"{f} has create_order")
            self.assertNotIn("submit_order", src, f"{f} has submit_order")

    def test_13_no_approval(self):
        src = (PROJECT_ROOT / "scripts/run_automated_trade_proposal_revalidation.py").read_text()
        self.assertNotIn("approve_proposal", src)

    def test_14_no_strategy_activation(self):
        for f in ["run_atp2_research_cycle.py", "run_automated_trade_proposal_revalidation.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("activate_strategy", src)

    def test_15_no_yaml_mutation(self):
        for f in ["run_atp2_research_cycle.py", "run_automated_trade_proposal_revalidation.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("yaml.dump", src)

    def test_16_rollback_only_atp2(self):
        src = (PROJECT_ROOT / "scripts/rollback_atp2_research_cron.sh").read_text()
        self.assertIn("ATP-2", src)
        self.assertNotIn("Q-1", src)
        self.assertNotIn("GOV-1", src)


class TestRegression(unittest.TestCase):
    def test_17_atp1b_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_atp1b_workflow_answers.py").exists())

    def test_18_ops_hygiene_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_ops_hygiene1_command_surface_alert_cleanup.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
