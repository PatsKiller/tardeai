#!/usr/bin/env python3
"""Unit tests for Phase 9C scheduled maturity board."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestPhase9CScheduledMaturityBoard(unittest.TestCase):

    def test_01_wrapper_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").exists())

    def test_02_operator_summary_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/report_operator_readiness_summary.py").exists())

    def test_03_rollback_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/rollback_phase9c_maturity_cron.sh").exists())

    def test_04_wrapper_checks_alpaca(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").read_text()
        self.assertIn("ALPACA_MODE", script)
        self.assertIn("paper", script)

    def test_05_wrapper_checks_llm_disable(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").read_text()
        self.assertIn("LLM_DISABLE_LIVE_EXECUTION", script)

    def test_06_wrapper_uses_flock(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").read_text()
        self.assertIn("flock", script)

    def test_07_wrapper_no_source_env(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").read_text()
        self.assertNotIn("source .env", script)
        self.assertNotIn("source $PROJ/.env", script)

    def test_08_operator_summary_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_operator_readiness_summary.py"), doraise=True)

    def test_09_rollback_targets_phase9c_only(self):
        script = (PROJECT_ROOT / "scripts/rollback_phase9c_maturity_cron.sh").read_text()
        self.assertIn("Phase 9C", script)
        self.assertNotIn("GOV-1", script)
        self.assertNotIn("stale_proposal_sweeper", script)

    def test_10_wrapper_checks_holdings(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").read_text()
        self.assertIn("holdings.json", script)
        self.assertIn("file_is_intact", script)

    def test_11_wrapper_outputs_to_maturity_hardening(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_maturity_control_board.sh").read_text()
        self.assertIn("docs/maturity_hardening/maturity_control_board_latest", script)
        self.assertIn("docs/maturity_hardening/phase_readiness_latest", script)

    def test_12_operator_summary_reads_latest_files(self):
        src = (PROJECT_ROOT / "scripts/report_operator_readiness_summary.py").read_text()
        self.assertIn("maturity_control_board_latest.json", src)
        self.assertIn("phase_readiness_latest.json", src)
        self.assertIn("governance_status_latest.json", src)

    def test_13_operator_summary_live_trading_blocked(self):
        src = (PROJECT_ROOT / "scripts/report_operator_readiness_summary.py").read_text()
        self.assertIn('"live_trading": "BLOCKED"', src)

    def test_14_cron_installed(self):
        import subprocess
        cron = subprocess.check_output("crontab -l", shell=True).decode()
        self.assertIn("BEGIN Phase 9C", cron)
        self.assertIn("END Phase 9C", cron)
        self.assertIn("run_scheduled_maturity_control_board.sh", cron)
        self.assertIn("report_operator_readiness_summary.py", cron)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestPhase9CScheduledMaturityBoard))
    sys.exit(0 if result.wasSuccessful() else 1)
