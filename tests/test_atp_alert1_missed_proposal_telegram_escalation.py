#!/usr/bin/env python3
"""Tests for ATP-ALERT-1 missed proposal Telegram escalation."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_evaluator(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_atp_alert_evaluator.py"), doraise=True)

    def test_02_q1_refresh(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_proactive_quote_refresh.py"), doraise=True)


class TestAlertLogic(unittest.TestCase):
    def test_03_target_crossed(self):
        from run_atp_alert_evaluator import classify_alert
        prop = {"proposed_entry": 2.15, "current_price": 2.40, "proposed_target1": 2.36, "proposed_stop": 2.04}
        alerts = classify_alert(prop)
        self.assertIsNotNone(alerts)
        types = [a["type"] for a in alerts]
        self.assertIn("target_crossed_before_review", types)

    def test_04_target_crossed_urgent(self):
        from run_atp_alert_evaluator import classify_alert
        prop = {"proposed_entry": 2.15, "current_price": 2.40, "proposed_target1": 2.36, "proposed_stop": 2.04}
        alerts = classify_alert(prop)
        target_alert = [a for a in alerts if a["type"] == "target_crossed_before_review"][0]
        self.assertEqual(target_alert["severity"], "URGENT")

    def test_05_no_alert_below_target(self):
        from run_atp_alert_evaluator import classify_alert
        prop = {"proposed_entry": 2.15, "current_price": 2.20, "proposed_target1": 2.36, "proposed_stop": 2.04}
        alerts = classify_alert(prop)
        self.assertIsNone(alerts)

    def test_06_large_move(self):
        from run_atp_alert_evaluator import classify_alert
        prop = {"proposed_entry": 10.00, "current_price": 10.60, "proposed_target1": 12.00, "proposed_stop": 9.00}
        alerts = classify_alert(prop)
        self.assertIsNotNone(alerts)
        types = [a["type"] for a in alerts]
        self.assertIn("large_move_before_review", types)

    def test_07_stop_crossed(self):
        from run_atp_alert_evaluator import classify_alert
        prop = {"proposed_entry": 10.00, "current_price": 8.50, "proposed_target1": 12.00, "proposed_stop": 9.00}
        alerts = classify_alert(prop)
        types = [a["type"] for a in alerts]
        self.assertIn("stop_crossed_pending", types)

    def test_08_message_has_safety_footer(self):
        from run_atp_alert_evaluator import build_telegram_message
        prop = {"id": 99, "symbol": "CODX", "strategy_id": "swing_trade", "status": "PENDING",
                "proposed_entry": 2.15, "current_price": 2.40, "proposed_target1": 2.36, "proposed_stop": 2.04}
        alert = {"type": "target_crossed_before_review", "severity": "URGENT", "reason": "test"}
        msg = build_telegram_message(prop, alert)
        self.assertIn("No order submitted", msg)
        self.assertIn("Paper mode", msg)

    def test_09_dedupe_works(self):
        from run_atp_alert_evaluator import is_deduped, mark_sent, dedupe_key
        prop = {"id": 99}
        alert = {"type": "target_crossed_before_review"}
        self.assertFalse(is_deduped(prop, alert))
        mark_sent(prop, alert)
        self.assertTrue(is_deduped(prop, alert))


class TestIntegration(unittest.TestCase):
    def test_10_q1_has_alert_call(self):
        src = (PROJECT_ROOT / "scripts/run_proactive_quote_refresh.py").read_text()
        self.assertIn("run_atp_alert_evaluator", src)
        self.assertIn("classify_alert", src)


class TestSafety(unittest.TestCase):
    def test_11_no_trades(self):
        src = (PROJECT_ROOT / "scripts/run_atp_alert_evaluator.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_12_no_approval(self):
        src = (PROJECT_ROOT / "scripts/run_atp_alert_evaluator.py").read_text()
        self.assertNotIn("approve_proposal", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
