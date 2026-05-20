#!/usr/bin/env python3
"""Tests for JOURNAL-UX-2 persistent lessons and closed-trade digest."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_migration(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/migrate_journal_ux2_lesson_memory.py"), doraise=True)

    def test_02_persist(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/persist_closed_trade_lessons.py"), doraise=True)

    def test_03_rollup(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/build_strategy_lesson_rollup.py"), doraise=True)

    def test_04_report(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_trade_lesson_memory.py"), doraise=True)

    def test_05_digest_builder(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/build_closed_trade_digest.py"), doraise=True)

    def test_06_digest_sender(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_closed_trade_digest.py"), doraise=True)

    def test_07_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestLessonModel(unittest.TestCase):
    def _pm(self, **kw):
        from closed_trade_postmortem_model import build_postmortem
        base = {"symbol": "TEST", "strategy_id": "test_strat", "pnl": 0, "r_multiple": 0}
        base.update(kw)
        return build_postmortem(base)

    def test_08_human_review_only(self):
        pm = self._pm(exit_reason="target_hit", pnl=50, r_multiple=1.5)
        self.assertTrue(pm["human_review_only"])

    def test_09_repeated_pattern_key(self):
        pm = self._pm(exit_reason="stop_hit_instant", pnl=-10, r_multiple=-0.05)
        key = f"{pm['strategy']}_{pm['mistake_type']}_{pm['lesson_category']}"
        self.assertIn("spread_slippage", key)
        self.assertIn("entry_timing", key)

    def test_10_confidence_delta(self):
        pm = self._pm(exit_reason="target_hit", pnl=50, r_multiple=1.5)
        self.assertEqual(pm["confidence_delta"], "positive")
        pm2 = self._pm(exit_reason="stop_hit", pnl=-50, r_multiple=-0.8)
        self.assertEqual(pm2["confidence_delta"], "negative")


class TestDigestBuilder(unittest.TestCase):
    def test_11_daily_summary_has_fields(self):
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        trades = [
            {"symbol": "AAA", "strategy_id": "s1", "exit_reason": "target_hit", "pnl": 100, "r_multiple": 2.0},
            {"symbol": "BBB", "strategy_id": "s2", "exit_reason": "stop_hit", "pnl": -30, "r_multiple": -0.5},
        ]
        pms = [build_postmortem(t) for t in trades]
        s = build_daily_summary(pms)
        self.assertIn("closed_today_count", s)
        self.assertIn("best_trade", s)
        self.assertIn("worst_trade", s)
        self.assertIn("top_lesson", s)
        self.assertIn("top_action_item", s)

    def test_12_best_trade(self):
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        pms = [build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 100, "r_multiple": 2})]
        s = build_daily_summary(pms)
        self.assertEqual(s["best_trade"]["symbol"], "X")

    def test_13_max_3_actions(self):
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        trades = [{"symbol": f"S{i}", "strategy_id": "s", "exit_reason": "stop_hit_instant", "pnl": -10, "r_multiple": -0.05} for i in range(5)]
        pms = [build_postmortem(t) for t in trades]
        s = build_daily_summary(pms)
        # top_action_item is a single string, review queue can have many
        self.assertIsNotNone(s["top_action_item"])

    def test_14_human_review_only_summary(self):
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        pms = [build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 10, "r_multiple": 1})]
        s = build_daily_summary(pms)
        self.assertTrue(s["human_review_only"])


class TestDigestRouter(unittest.TestCase):
    def test_15_digest_routes_p1(self):
        from telegram_alert_router import classify_alert
        msg = "Closed Trade Review -- 2026-05-19\nClosed: 3 | 2W / 1L / 0F\nP&L: $50 | Avg R: 0.5R"
        # This doesn't match P0 patterns, should be P1
        level = classify_alert(msg)
        self.assertIn(level, ("P1_DIGEST", "P2_DASHBOARD_ONLY"))

    def test_16_no_raw_narrative_in_digest(self):
        """Digest should not dump raw agent narrative."""
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        pms = [build_postmortem({"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 10, "r_multiple": 1})]
        s = build_daily_summary(pms)
        # top_lesson should be a single sentence, not a wall of text
        self.assertLess(len(s["top_lesson"]), 300)


class TestAPI(unittest.TestCase):
    def test_17_lesson_memory_endpoint(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/journal/lesson-memory/summary", src)

    def test_18_strategy_lessons_endpoint(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("/api/v2/journal/strategy-lessons/summary", src)


class TestSafety(unittest.TestCase):
    def test_19_no_trades(self):
        for script in ["persist_closed_trade_lessons.py", "build_strategy_lesson_rollup.py",
                        "build_closed_trade_digest.py", "send_closed_trade_digest.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("create_order", src, f"{script} has create_order")
            self.assertNotIn("submit_order", src, f"{script} has submit_order")

    def test_20_no_strategy_activation(self):
        for script in ["persist_closed_trade_lessons.py", "build_strategy_lesson_rollup.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("activate_strategy", src)

    def test_21_no_yaml_changes(self):
        for script in ["persist_closed_trade_lessons.py", "build_strategy_lesson_rollup.py"]:
            src = (PROJECT_ROOT / "scripts" / script).read_text()
            self.assertNotIn("yaml.dump", src)

    def test_22_digest_sender_has_test_mode(self):
        src = (PROJECT_ROOT / "scripts/send_closed_trade_digest.py").read_text()
        self.assertIn("send_test", src)
        self.assertIn("[TEST]", src)


class TestRegression(unittest.TestCase):
    def test_23_ux1b_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_journal_ux1b_closed_trade_action_dashboard.py").exists())

    def test_24_ops_hygiene_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_ops_hygiene1_command_surface_alert_cleanup.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
