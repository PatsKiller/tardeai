#!/usr/bin/env python3
"""Tests for ATP-1B workflow answers."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_schedule_report(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_current_research_pipeline_schedule.py"), doraise=True)

    def test_02_candidate_breakdown(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_candidate_status_breakdown.py"), doraise=True)


class TestDocs(unittest.TestCase):
    def test_03_operator_answers(self):
        self.assertTrue((PROJECT_ROOT / "docs/automated_trade_proposals/phase_atp1b_workflow_answers/atp1b_direct_operator_answers.md").exists())

    def test_04_target_schedule(self):
        self.assertTrue((PROJECT_ROOT / "docs/automated_trade_proposals/phase_atp1b_workflow_answers/atp1b_target_scheduler_design.md").exists())

    def test_05_page_menu(self):
        self.assertTrue((PROJECT_ROOT / "docs/automated_trade_proposals/phase_atp1b_workflow_answers/atp1b_page_menu_answer.md").exists())

    def test_06_rename_status(self):
        self.assertTrue((PROJECT_ROOT / "docs/automated_trade_proposals/phase_atp1b_workflow_answers/atp1b_rename_status.md").exists())


class TestRename(unittest.TestCase):
    def test_07_shell_renamed(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/components/Shell.tsx").read_text()
        self.assertIn("Automated Trade Proposals", src)
        self.assertNotIn("'Paper Proposals'", src)

    def test_08_page_renamed(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn("Automated Trade Proposals", src)

    def test_09_route_preserved(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/components/Shell.tsx").read_text()
        self.assertIn("/paper-proposals", src)

    def test_10_build_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("index-*.js")))


class TestSafety(unittest.TestCase):
    def test_11_no_trades(self):
        for f in ["report_current_research_pipeline_schedule.py", "report_candidate_status_breakdown.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
