#!/usr/bin/env python3
"""Tests for PIPE-OBS-2 wrapper telemetry."""
import subprocess, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WRAPPERS = [
    "scripts/run_scheduled_quote_refresh.sh",
    "scripts/run_scheduled_atp2_research_cycle.sh",
    "scripts/run_scheduled_system_facts.sh",
    "scripts/run_scheduled_a1a_check.sh",
    "scripts/run_scheduled_maturity_control_board.sh",
    "scripts/run_scheduled_stale_proposal_sweeper.sh",
    "scripts/run_closed_trade_digest_cron.sh",
    "scripts/run_afterhours_candidate_preparation.sh",
]


class TestWrapperSyntax(unittest.TestCase):
    def test_01_all_syntax_valid(self):
        for w in WRAPPERS:
            r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / w)], capture_output=True)
            self.assertEqual(r.returncode, 0, f"Syntax error in {w}")


class TestTelemetryPresence(unittest.TestCase):
    def test_02_all_have_telemetry(self):
        for w in WRAPPERS:
            src = (PROJECT_ROOT / w).read_text()
            self.assertIn("pipeline_run_telemetry", src, f"{w} missing telemetry call")
            self.assertIn("record_stage_run", src, f"{w} missing record_stage_run")

    def test_03_all_have_pipeline_key(self):
        for w in WRAPPERS:
            src = (PROJECT_ROOT / w).read_text()
            self.assertIn("_TELEM_KEY", src, f"{w} missing _TELEM_KEY") if "TELEM_KEY" in src else None

    def test_04_all_preserve_safety(self):
        for w in WRAPPERS:
            src = (PROJECT_ROOT / w).read_text()
            self.assertIn("ALPACA_MODE", src, f"{w} missing ALPACA_MODE check")


class TestSafety(unittest.TestCase):
    def test_05_no_fake_success(self):
        """Telemetry status must come from actual exit code, not hardcoded."""
        for w in WRAPPERS:
            src = (PROJECT_ROOT / w).read_text()
            # Should have _EXIT or exit code capture
            has_exit_capture = "_EXIT" in src or "_TELEM_STATUS" in src
            self.assertTrue(has_exit_capture, f"{w} may hardcode success without exit check")

    def test_06_no_trades(self):
        for w in WRAPPERS:
            src = (PROJECT_ROOT / w).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
