#!/usr/bin/env python3
"""Tests for JOURNAL-UX-1 closed trade postmortem dashboard."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPostmortemModel(unittest.TestCase):
    def test_01_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/closed_trade_postmortem_model.py"), doraise=True)

    def test_02_target_hit_good_exit(self):
        from closed_trade_postmortem_model import build_postmortem
        r = build_postmortem({"symbol": "INFU", "strategy_id": "earnings_catalyst", "exit_reason": "target_hit", "pnl": 56, "r_multiple": 1.35})
        self.assertEqual(r["exit_quality"], "GOOD_EXIT")
        self.assertEqual(r["verdict"], "WIN")

    def test_03_stop_hit_instant(self):
        from closed_trade_postmortem_model import build_postmortem
        r = build_postmortem({"symbol": "BLBD", "strategy_id": "earnings_catalyst", "exit_reason": "stop_hit_instant", "pnl": -14.8, "r_multiple": -0.05})
        self.assertEqual(r["exit_quality"], "NEEDS_REVIEW")
        self.assertIn("instant stop", r["one_line_lesson"].lower())

    def test_04_manual_stale_needs_review(self):
        from closed_trade_postmortem_model import build_postmortem
        r = build_postmortem({"symbol": "INFU", "exit_reason": "manual_stale_close", "pnl": 67, "r_multiple": 0.45})
        self.assertEqual(r["exit_quality"], "NEEDS_REVIEW")
        self.assertIn("manual", r["one_line_lesson"].lower())

    def test_05_time_stop_lesson(self):
        from closed_trade_postmortem_model import build_postmortem
        r = build_postmortem({"symbol": "GCTS", "exit_reason": "time_stop_max_0d", "pnl": -9.38, "r_multiple": -0.07})
        self.assertEqual(r["lesson_category"], "holding_period")

    def test_06_has_all_fields(self):
        from closed_trade_postmortem_model import build_postmortem
        r = build_postmortem({"symbol": "X", "exit_reason": "target_hit", "pnl": 10, "r_multiple": 1.0})
        for field in ["why_closed", "one_line_lesson", "operator_action", "exit_quality", "entry_quality", "human_review_only"]:
            self.assertIn(field, r)

    def test_07_human_review_only(self):
        from closed_trade_postmortem_model import build_postmortem
        r = build_postmortem({"symbol": "X", "exit_reason": "stop_hit", "pnl": -5, "r_multiple": -0.3})
        self.assertTrue(r["human_review_only"])


class TestFrontend(unittest.TestCase):
    def test_08_dashboard_section_exists(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/AutomatedTradeJournal.tsx").read_text()
        self.assertIn("Closed Trade Review", src)
        self.assertIn("Why Closed", src)
        self.assertIn("Exit Quality", src)
        self.assertIn("Lesson", src)

    def test_09_build_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("AutomatedTradeJournal-*.js")))


class TestSafety(unittest.TestCase):
    def test_10_no_trades(self):
        src = (PROJECT_ROOT / "scripts/closed_trade_postmortem_model.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_11_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/closed_trade_postmortem_model.py").read_text()
        self.assertNotIn("activate_strategy", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
