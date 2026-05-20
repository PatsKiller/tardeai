#!/usr/bin/env python3
"""Tests for PIPE-OPS-2 actionable pipeline operations."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_owner_map(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/pipeline_stage_owner_map.py"), doraise=True)

    def test_02_audit(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_pipeline_stage_actionability_audit.py"), doraise=True)

    def test_03_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestOwnerMap(unittest.TestCase):
    def test_04_all_stages_have_owner(self):
        from pipeline_stage_owner_map import get_all_stages
        stages = get_all_stages()
        self.assertEqual(len(stages), 31)
        for s in stages:
            self.assertIn("pipeline_key", s)
            self.assertIn("display_name", s)
            self.assertIn("category", s)
            self.assertIn("operator_next_action", s)

    def test_05_execution_no_dry_run(self):
        from pipeline_stage_owner_map import get_stage_owner
        rg = get_stage_owner("risk_gate")
        self.assertIsNone(rg["safe_dry_run_cmd"])
        ap = get_stage_owner("alpaca_paper")
        self.assertIsNone(ap["safe_dry_run_cmd"])

    def test_06_every_stage_has_action(self):
        from pipeline_stage_owner_map import get_all_stages
        for s in get_all_stages():
            self.assertTrue(len(s["operator_next_action"]) > 0, f"{s['pipeline_key']} missing action")


class TestAPIMetadata(unittest.TestCase):
    def test_07_api_returns_owner(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("owner_script", src)
        self.assertIn("recommended_action", src)
        self.assertIn("never_run_subtype", src)

    def test_08_no_unsafe_buttons(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        for unsafe in ["Run Live", "Execute Trade", "Submit Order", "Approve Proposal"]:
            self.assertNotIn(unsafe, src)


class TestFrontend(unittest.TestCase):
    def test_09_shows_owner(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("owner_script", src)

    def test_10_shows_action(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("recommended_action", src)

    def test_11_shows_never_run_subtype(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("never_run_subtype", src)

    def test_12_builds(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("index-*.js")))


class TestSafety(unittest.TestCase):
    def test_13_no_trades(self):
        for f in ["pipeline_stage_owner_map.py", "report_pipeline_stage_actionability_audit.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
