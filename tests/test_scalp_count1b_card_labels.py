#!/usr/bin/env python3
"""Tests for SCALP-COUNT-1B card label polish."""
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCardLabels(unittest.TestCase):
    def test_01_cards_say_run(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/TradeAI.tsx").read_text()
        self.assertIn('"Run GO"', src)
        self.assertIn('"Run WAIT"', src)
        self.assertIn('"Run NO GO"', src)

    def test_02_universe_card_exists(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/TradeAI.tsx").read_text()
        self.assertIn('"Universe"', src)
        self.assertIn("universe_count", src)

    def test_03_current_run_delta_label(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/TradeAI.tsx").read_text()
        self.assertIn('"current run"', src)

    def test_04_tracked_symbols_label(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/TradeAI.tsx").read_text()
        self.assertIn('"tracked symbols"', src)

    def test_05_scalp_count1_tests_pass(self):
        import subprocess, sys
        r = subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
                           "tests/test_scalp_count1_current_run_counts.py"],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
