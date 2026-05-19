#!/usr/bin/env python3
"""Tests for JOURNAL-UX-1B closed trade action dashboard."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_gap_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_journal_ux1b_gap_audit.py"), doraise=True)

    def test_02_postmortem_model_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/closed_trade_postmortem_model.py"), doraise=True)

    def test_03_lesson_quality_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_journal_lesson_quality.py"), doraise=True)

    def test_04_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestLessonQuality(unittest.TestCase):
    def _pm(self, **kw):
        from closed_trade_postmortem_model import build_postmortem
        base = {"symbol": "TEST", "strategy_id": "test_strat", "pnl": 0, "r_multiple": 0}
        base.update(kw)
        return build_postmortem(base)

    def test_05_no_bare_review(self):
        """No lesson should be just 'Review.'"""
        for reason in ["target_hit", "stop_hit", "stop_hit_instant", "time_stop_max_0d",
                        "manual_stale_close", "phantom_no_alpaca_position", "position_closed_in_alpaca"]:
            pm = self._pm(exit_reason=reason)
            self.assertNotEqual(pm["improved_lesson"].strip().lower(), "review", f"{reason} produced bare 'Review'")
            self.assertGreater(len(pm["improved_lesson"]), 30, f"{reason} lesson too short")

    def test_06_no_bare_check_stop(self):
        """No lesson should be just 'Check stop distance.'"""
        pm = self._pm(exit_reason="stop_hit", r_multiple=-0.3)
        self.assertNotEqual(pm["improved_lesson"].strip().lower(), "check stop distance")

    def test_07_stale_close_mentions_exit_rule(self):
        pm = self._pm(exit_reason="manual_stale_close", pnl=50, r_multiple=0.5)
        lesson = pm["improved_lesson"].lower()
        self.assertTrue("exit rule" in lesson or "stale" in lesson or "explicit" in lesson)

    def test_08_instant_stop_mentions_spread(self):
        pm = self._pm(exit_reason="stop_hit_instant", pnl=-10, r_multiple=-0.05)
        lesson = pm["improved_lesson"].lower()
        self.assertTrue("spread" in lesson or "entry" in lesson or "slippage" in lesson)

    def test_09_broker_close_mentions_sync(self):
        pm = self._pm(exit_reason="position_closed_in_alpaca", pnl=-15, r_multiple=-0.8)
        lesson = pm["improved_lesson"].lower()
        self.assertTrue("broker" in lesson or "alpaca" in lesson or "external" in lesson)

    def test_10_target_hit_mentions_discipline(self):
        pm = self._pm(exit_reason="target_hit", pnl=50, r_multiple=1.5)
        lesson = pm["improved_lesson"].lower()
        self.assertTrue("discipline" in lesson or "strategy" in lesson or "plan" in lesson or "target" in lesson)

    def test_11_time_stop_mentions_capital(self):
        pm = self._pm(exit_reason="time_stop_max_0d", pnl=-5, r_multiple=-0.1)
        lesson = pm["improved_lesson"].lower()
        self.assertTrue("capital" in lesson or "window" in lesson or "drawdown" in lesson or "time stop" in lesson)


class TestDashboardSummary(unittest.TestCase):
    def _summary(self):
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        trades = [
            {"symbol": "AAA", "strategy_id": "s1", "exit_reason": "target_hit", "pnl": 100, "r_multiple": 2.0},
            {"symbol": "BBB", "strategy_id": "s2", "exit_reason": "stop_hit", "pnl": -30, "r_multiple": -0.5},
            {"symbol": "CCC", "strategy_id": "s1", "exit_reason": "stop_hit_instant", "pnl": -10, "r_multiple": -0.05},
        ]
        return build_daily_summary([build_postmortem(t) for t in trades])

    def test_12_has_best_trade(self):
        s = self._summary()
        self.assertIsNotNone(s["best_trade"])
        self.assertEqual(s["best_trade"]["symbol"], "AAA")

    def test_13_has_worst_trade(self):
        s = self._summary()
        self.assertIsNotNone(s["worst_trade"])
        self.assertEqual(s["worst_trade"]["symbol"], "BBB")

    def test_14_has_top_lesson(self):
        s = self._summary()
        self.assertIsNotNone(s["top_lesson"])
        self.assertGreater(len(s["top_lesson"]), 20)

    def test_15_has_top_action(self):
        s = self._summary()
        self.assertIsNotNone(s["top_action_item"])
        self.assertGreater(len(s["top_action_item"]), 10)

    def test_16_human_review_only(self):
        s = self._summary()
        self.assertTrue(s["human_review_only"])


class TestNewFields(unittest.TestCase):
    def test_17_dashboard_verdict(self):
        from closed_trade_postmortem_model import build_postmortem
        pm = build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5})
        self.assertEqual(pm["dashboard_verdict"], "CLEAN_WIN")

    def test_18_mistake_type(self):
        from closed_trade_postmortem_model import build_postmortem
        pm = build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "stop_hit_instant", "pnl": -10, "r_multiple": -0.05})
        self.assertEqual(pm["mistake_type"], "spread_slippage")

    def test_19_action_priority(self):
        from closed_trade_postmortem_model import build_postmortem
        pm = build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "stop_hit_instant", "pnl": -10, "r_multiple": -0.05})
        self.assertEqual(pm["action_priority"], "high")

    def test_20_confidence_delta(self):
        from closed_trade_postmortem_model import build_postmortem
        pm = build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5})
        self.assertEqual(pm["confidence_delta"], "positive")


class TestAPI(unittest.TestCase):
    def test_21_api_has_endpoints(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/journal/closed-trades/action-dashboard", src)
        self.assertIn("/api/v2/journal/closed-trades/action-items", src)
        self.assertIn("/api/v2/journal/closed-trades/lessons", src)

    def test_22_endpoints_read_only(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        for fn in ["_journal_closed_action_dashboard", "_journal_closed_action_items", "_journal_closed_lessons"]:
            start = src.index(f"def {fn}")
            end = src.index("\ndef ", start + 1)
            body = src[start:end]
            self.assertNotIn("INSERT", body)
            self.assertNotIn("UPDATE", body)
            self.assertNotIn("DELETE", body)


class TestFrontend(unittest.TestCase):
    def test_23_has_lessons_section(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/AutomatedTradeJournal.tsx").read_text()
        self.assertIn("Today's Trade Lessons", src)

    def test_24_has_action_queue(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/AutomatedTradeJournal.tsx").read_text()
        self.assertIn("Action Queue", src)

    def test_25_build_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("AutomatedTradeJournal-*.js")))


class TestSafety(unittest.TestCase):
    def test_26_no_trades(self):
        for script in ["closed_trade_postmortem_model.py", "report_journal_ux1b_gap_audit.py", "report_journal_lesson_quality.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_27_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/closed_trade_postmortem_model.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_28_all_human_review_only(self):
        from closed_trade_postmortem_model import build_postmortem
        for reason in ["target_hit", "stop_hit", "stop_hit_instant", "manual_stale_close", "phantom_no_alpaca_position"]:
            pm = build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": reason, "pnl": 0, "r_multiple": 0})
            self.assertTrue(pm["human_review_only"])


class TestRegression(unittest.TestCase):
    def test_29_ux1_test_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_journal_ux1_closed_trade_postmortem_dashboard.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
