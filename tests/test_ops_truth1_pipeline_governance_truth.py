#!/usr/bin/env python3
"""Tests for OPS-TRUTH-1 pipeline and governance truth."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_pipeline_audit(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_pipeline_truth_audit.py"), doraise=True)

    def test_02_governance_audit(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_governance_count_consistency.py"), doraise=True)


class TestPipelineTruth(unittest.TestCase):
    def test_03_no_false_nominal(self):
        """Pipeline page must not show 'X/X stages nominal' when stages haven't run."""
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertNotIn("stages nominal (no runs yet today)", src)

    def test_04_waiting_for_schedule(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("waiting for schedule", src.lower())

    def test_05_zero_completed_shows_warning(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("0/{total} stages completed today", src)


class TestGovernanceTruth(unittest.TestCase):
    def test_06_no_contradiction(self):
        """Governance must not say 'No closed paper trades yet' when closed trades exist."""
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperGovernance.tsx").read_text()
        self.assertIn("closed_paper_trades > 0", src)
        self.assertIn("scorecard eligibility", src.lower())

    def test_07_explains_eligibility(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperGovernance.tsx").read_text()
        self.assertIn("minimum sample size", src.lower())


class TestSafety(unittest.TestCase):
    def test_08_no_trades(self):
        for f in ["report_pipeline_truth_audit.py", "report_governance_count_consistency.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_09_frontend_builds(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("index-*.js")))


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
