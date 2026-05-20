#!/usr/bin/env python3
"""Tests for Q-1B premarket quote refresh cadence."""
import subprocess, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCron(unittest.TestCase):
    def test_01_6am_cron_exists(self):
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        self.assertIn("Q-1B", r.stdout)
        self.assertIn("0 6 * * 1-5", r.stdout)

    def test_02_630_cron_exists(self):
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        self.assertIn("30 6 * * 1-5", r.stdout)

    def test_03_rollback_exists(self):
        p = PROJECT_ROOT / "scripts/rollback_q1b_premarket_quote_refresh.sh"
        self.assertTrue(p.exists())

    def test_04_rollback_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/rollback_q1b_premarket_quote_refresh.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)


class TestSafety(unittest.TestCase):
    def test_05_wrapper_checks_safety(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)
        self.assertIn("LLM_DISABLE", src)

    def test_06_no_trades_in_wrapper(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_07_rollback_only_q1b(self):
        src = (PROJECT_ROOT / "scripts/rollback_q1b_premarket_quote_refresh.sh").read_text()
        self.assertIn("Q-1B", src)
        self.assertNotIn("Q-1 proactive", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
