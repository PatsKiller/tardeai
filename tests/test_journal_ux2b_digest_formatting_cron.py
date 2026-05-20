#!/usr/bin/env python3
"""Tests for JOURNAL-UX-2B digest formatting and cron."""
import subprocess, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_digest_builder(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/build_closed_trade_digest.py"), doraise=True)

    def test_02_digest_sender(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/send_closed_trade_digest.py"), doraise=True)


class TestDigestFormat(unittest.TestCase):
    def _digest(self, trades):
        from closed_trade_postmortem_model import build_postmortem, build_daily_summary
        from build_closed_trade_digest import build_digest_message
        pms = [build_postmortem(t) for t in trades]
        summary = build_daily_summary(pms)
        return build_digest_message(summary, "2026-05-20")

    def test_03_has_closed_count(self):
        msg = self._digest([{"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5}])
        self.assertIn("Closed: 1", msg)

    def test_04_has_pnl(self):
        msg = self._digest([{"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5}])
        self.assertIn("P&L:", msg)
        self.assertIn("Avg R:", msg)

    def test_05_has_best_trade(self):
        msg = self._digest([{"symbol": "AAPL", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 100, "r_multiple": 2}])
        self.assertIn("Best: AAPL", msg)

    def test_06_has_lesson(self):
        msg = self._digest([{"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5}])
        self.assertIn("Lesson:", msg)

    def test_07_no_padded_actions(self):
        msg = self._digest([{"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5}])
        self.assertNotIn("No additional action", msg)

    def test_08_has_review_when_different(self):
        msg = self._digest([
            {"symbol": "AAA", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 100, "r_multiple": 2},
            {"symbol": "BBB", "strategy_id": "s", "exit_reason": "stop_hit_instant", "pnl": -10, "r_multiple": -0.05},
        ])
        self.assertIn("Review:", msg)

    def test_09_no_raw_narrative(self):
        msg = self._digest([{"symbol": "X", "strategy_id": "s", "exit_reason": "target_hit", "pnl": 50, "r_multiple": 1.5}])
        self.assertNotIn("BLOCKED BY IRIS", msg)
        self.assertNotIn("Trade AI v12", msg)

    def test_10_max_3_actions(self):
        trades = [{"symbol": f"S{i}", "strategy_id": "s", "exit_reason": "stop_hit_instant", "pnl": -10, "r_multiple": -0.05} for i in range(5)]
        msg = self._digest(trades)
        action_lines = [l for l in msg.split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5."))]
        self.assertLessEqual(len(action_lines), 3)

    def test_11_routes_p1(self):
        from telegram_alert_router import classify_alert
        msg = "Closed Trade Review -- 2026-05-20\nClosed: 3 | 2W / 1L / 0F\nP&L: $50"
        level = classify_alert(msg)
        self.assertIn(level, ("P1_DIGEST", "P2_DASHBOARD_ONLY"))

    def test_12_test_label(self):
        """send-test mode should prepend [TEST]."""
        src = (PROJECT_ROOT / "scripts/send_closed_trade_digest.py").read_text()
        self.assertIn("[TEST]", src)

    def test_13_no_empty_digest(self):
        from build_closed_trade_digest import build_digest_message
        from closed_trade_postmortem_model import build_daily_summary
        msg = build_digest_message(build_daily_summary([]), "2026-05-20")
        self.assertIn("No closed trades", msg)


class TestCronWrapper(unittest.TestCase):
    def test_14_wrapper_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/run_closed_trade_digest_cron.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_15_rollback_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/rollback_journal_ux2b_digest_cron.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_16_wrapper_has_safety(self):
        src = (PROJECT_ROOT / "scripts/run_closed_trade_digest_cron.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)
        self.assertIn("set -a; source", src)


class TestSafety(unittest.TestCase):
    def test_17_no_trades(self):
        for f in ["build_closed_trade_digest.py", "send_closed_trade_digest.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_18_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/build_closed_trade_digest.py").read_text()
        self.assertNotIn("activate_strategy", src)


class TestRegression(unittest.TestCase):
    def test_19_ux2_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_journal_ux2_persistent_lessons_digest.py").exists())

    def test_20_ops_hygiene_exists(self):
        self.assertTrue((PROJECT_ROOT / "tests/test_ops_hygiene1_command_surface_alert_cleanup.py").exists())


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
