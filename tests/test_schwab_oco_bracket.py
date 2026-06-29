#!/usr/bin/env python3
"""Tests for the Schwab API OCO bracket builder + guards (P3). PURE — no live broker calls."""
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import schwab_oco_bracket as oco


class TestOcoBuilder(unittest.TestCase):
    def test_01_compile(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/schwab_oco_bracket.py"), doraise=True)

    def test_02_spec_shape(self):
        spec = oco.make_oco_order_spec("agnc", 293, 11.24, 10.75)
        self.assertEqual(spec["orderStrategyType"], "OCO")
        kids = spec["childOrderStrategies"]
        self.assertEqual(len(kids), 2)
        by_type = {k["orderType"]: k for k in kids}
        # take-profit LIMIT leg
        self.assertIn("LIMIT", by_type)
        tp = by_type["LIMIT"]
        self.assertEqual(tp["price"], "11.24")
        self.assertEqual(tp["orderLegCollection"][0]["instruction"], "SELL")
        self.assertEqual(tp["orderLegCollection"][0]["quantity"], 293)
        self.assertEqual(tp["orderLegCollection"][0]["instrument"]["symbol"], "AGNC")
        self.assertEqual(tp["duration"], "GOOD_TILL_CANCEL")
        # stop-loss STOP leg
        self.assertIn("STOP", by_type)
        sp = by_type["STOP"]
        self.assertEqual(sp["stopPrice"], "10.75")
        self.assertEqual(sp["orderLegCollection"][0]["instruction"], "SELL")
        self.assertEqual(sp["orderLegCollection"][0]["quantity"], 293)

    def test_03_fractional_qty_rejected(self):
        with self.assertRaises(oco.OcoAbort):
            oco.make_oco_order_spec("AGNC", 10.5, 11.24, 10.75)

    def test_04_zero_qty_rejected(self):
        with self.assertRaises(oco.OcoAbort):
            oco.make_oco_order_spec("AGNC", 0, 11.24, 10.75)

    def test_05_tp_must_exceed_stop(self):
        with self.assertRaises(oco.OcoAbort):
            oco.make_oco_order_spec("AGNC", 100, 10.50, 10.75)   # tp below stop

    def test_06_nonpositive_prices_rejected(self):
        with self.assertRaises(oco.OcoAbort):
            oco.make_oco_order_spec("AGNC", 100, 11.24, 0)

    def test_07_submit_failclosed_when_flag_off(self):
        os.environ.pop(oco.OCO_FLAG, None)
        self.assertFalse(oco.flag_enabled())
        with self.assertRaises(oco.OcoAbort) as ctx:
            oco.submit_oco("schwab_taxable", "AGNC", 1, 11.24, 10.75, intent=object())
        self.assertIn("OFF", str(ctx.exception))

    def test_08_canary_cap_enforced_when_flag_on(self):
        # flag ON but qty over the canary cap -> aborts BEFORE ever reaching place_order (no live call)
        os.environ[oco.OCO_FLAG] = "1"
        try:
            with self.assertRaises(oco.OcoAbort) as ctx:
                oco.submit_oco("schwab_taxable", "AGNC", 293, 11.24, 10.75, intent=object(), canary=True)
            self.assertIn("canary cap", str(ctx.exception))
        finally:
            os.environ.pop(oco.OCO_FLAG, None)

    def test_09_preview_is_pure_and_flags_2fa(self):
        os.environ.pop(oco.OCO_FLAG, None)
        t = oco.preview_oco_ticket("AGNC", 293, 11.24, 10.75, account_key="schwab_taxable")
        self.assertTrue(t["requires_2fa"])
        self.assertFalse(t["live_enabled"])
        self.assertEqual(t["order_strategy"], "OCO")
        self.assertEqual(t["order_spec"]["orderStrategyType"], "OCO")

    def test_10_intent_protective_marker_and_shape(self):
        from brokers.execution_guard import PROTECTIVE_STOP_MARKER
        from brokers.order_intent import Direction
        intent = oco.make_oco_intent("schwab_taxable", "AGNC", 293, 11.24, 10.75,
                                     current_price=10.97, held_qty=293)
        self.assertEqual(intent.direction, Direction.LONG)          # both legs sell-to-close
        self.assertEqual(intent.broker, "schwab")
        self.assertEqual(intent.meta.strategy_id, PROTECTIVE_STOP_MARKER)   # routes through protective gate
        ev = intent.meta.signal_evidence
        self.assertEqual(ev["instruction"], "SELL")
        self.assertEqual(ev["order_type"], "OCO")
        self.assertEqual(ev["stop_price"], 10.75)
        self.assertEqual(ev["take_profit_price"], 11.24)
        self.assertEqual(float(intent.entry.stop_price), 10.75)     # STOP leg is the intent entry

    def test_11_intent_validates_structurally(self):
        from brokers.order_intent import validate
        intent = oco.make_oco_intent("schwab_taxable", "AGNC", 293, 11.24, 10.75)
        vr = validate(intent)
        self.assertTrue(vr.ok, f"intent failed canonical validation: {getattr(vr,'errors',None)}")

    def test_12_intent_rejects_fractional(self):
        with self.assertRaises(oco.OcoAbort):
            oco.make_oco_intent("schwab_taxable", "AGNC", 10.5, 11.24, 10.75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
