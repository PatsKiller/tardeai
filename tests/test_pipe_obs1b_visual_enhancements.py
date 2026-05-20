#!/usr/bin/env python3
"""Tests for PIPE-OBS-1B visual/legend enhancements."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestLegend(unittest.TestCase):
    def test_01_legend_in_page(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("Status Legend", src)

    def test_02_all_statuses_labeled(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        for label in ["Healthy", "Waiting", "Needs Attention", "Blocked", "Failed", "Manual/On-Demand", "Dry-Run"]:
            self.assertIn(label, src, f"Missing status label: {label}")

    def test_03_icons_not_color_only(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        # Stage cards should have text status, not just color
        self.assertIn("Healthy", src)
        self.assertIn("Attention", src)
        self.assertIn("No telemetry", src)

    def test_04_kpi_tiles(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("KPI Tiles", src)
        for kpi in ["Completed", "Warnings", "Critical", "Never Run"]:
            self.assertIn(kpi, src)

    def test_05_explanation_block(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("separates stage registry from run telemetry", src)

    def test_06_no_unsafe_buttons(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        for unsafe in ["Run Live", "Execute Trade", "Submit Order", "Approve Proposal"]:
            self.assertNotIn(unsafe, src)

    def test_07_legend_doc_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/operator_hygiene/phase_pipe_obs1_pipeline_run_telemetry/pipe_obs1_visual_status_legend.md").exists())

    def test_08_frontend_builds(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("index-*.js")))


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
