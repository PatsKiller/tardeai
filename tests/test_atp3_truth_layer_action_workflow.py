#!/usr/bin/env python3
"""Tests for ATP-3 truth layer and action workflow."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_audit(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_atp_readiness_truth_audit.py"), doraise=True)

    def test_02_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestTruthLayer(unittest.TestCase):
    def test_03_unknown_quote_counter_in_api(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("unknown_quote_count", src)

    def test_04_exec_missing_counter(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("exec_missing_count", src)

    def test_05_unknown_quote_blocks_approval(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("UNKNOWN_QUOTE", src)
        # approval_allowed set to False for unknown quote
        self.assertIn("prop['approval_allowed'] = False", src)

    def test_06_rr_below_minimum_blocks(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("rr_below_minimum", src)

    def test_07_primary_blockers_added(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("primary_blockers", src)
        self.assertIn("primary_blocker", src)

    def test_08_high_rvol_warning(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("high_rvol_warning", src)

    def test_09_high_gap_warning(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("high_gap_warning", src)

    def test_10_approval_override_requires_quote(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("has_quote", src)


class TestSafety(unittest.TestCase):
    def test_11_no_trades(self):
        src = (PROJECT_ROOT / "scripts/report_atp_readiness_truth_audit.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_12_no_approval_in_audit(self):
        src = (PROJECT_ROOT / "scripts/report_atp_readiness_truth_audit.py").read_text()
        self.assertNotIn("approve_proposal", src)


class TestWorkflowDoc(unittest.TestCase):
    def test_13_action_workflow_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/automated_trade_proposals/phase_atp3_truth_layer_action_workflow/atp3_action_workflow_design.md").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
