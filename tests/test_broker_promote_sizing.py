#!/usr/bin/env python3
"""Tests for broker promote sizing + evaluation gates."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import broker_promote_sizing as bps
import account_policy as ap


class TestBrokerPromoteSizing(unittest.TestCase):
    def test_effective_policy_applies_momentum_scalp_live_rules(self):
        pol = bps.effective_policy_for_broker("schwab_taxable", "momentum_scalp")
        self.assertEqual(pol.get("max_notional_per_trade"), 2000)
        self.assertEqual(pol.get("max_risk_dollars_per_trade"), 150)

    def test_crmt_schwab_shares_capped_vs_paper(self):
        """664 shares @ $3.01 on schwab vs thousands on paper percent policy."""
        with patch.object(ap, "equity_for_account", return_value=(71182.48, "test")):
            with patch.object(ap, "cash_for_account", return_value=(50000.0, "test")):
                with patch.object(bps, "account_activity_snapshot", return_value={"open_trades": 0}):
                    s = bps.compute_broker_sizing("schwab_taxable", "momentum_scalp", 3.01, 2.86)
        self.assertLessEqual(s["shares"], 664)
        self.assertLessEqual(s["dollar_size"], 2000)
        self.assertLessEqual(s["dollar_risk"], 200)

    def test_oversized_shares_blocked(self):
        now = datetime.now(timezone.utc).isoformat()
        quote = {"last": 3.01, "bid": 3.00, "ask": 3.02, "spread_pct": 0.5, "quote_timestamp": now}
        with patch.object(ap, "equity_for_account", return_value=(71182.48, "test")):
            with patch.object(ap, "cash_for_account", return_value=(50000.0, "test")):
                with patch.object(bps, "account_activity_snapshot", return_value={"open_trades": 0, "daily_limit_reached": False}):
                    ev = bps.evaluate_broker_promote(
                    "schwab_taxable", "momentum_scalp",
                    3.01, 2.86, 3.31, 6760, quote=quote,
                )
        self.assertEqual(ev["status"], "BLOCK")
        self.assertFalse(ev["allowed"])
        self.assertTrue(any("exceed max" in v for v in ev["violations"]))

    def test_306_fill_warn_not_block(self):
        now = datetime.now(timezone.utc).isoformat()
        quote = {"last": 3.06, "bid": 3.05, "ask": 3.07, "spread_pct": 0.5, "quote_timestamp": now}
        activity = {"open_trades": 0, "new_trades_today": 0, "slots_used_today": 0, "daily_limit_reached": False}
        with patch.object(ap, "equity_for_account", return_value=(71182.48, "test")):
            with patch.object(ap, "cash_for_account", return_value=(71182.48, "test")):
                with patch.object(bps, "account_activity_snapshot", return_value=activity):
                    ev = bps.evaluate_broker_promote(
                        "schwab_taxable", "momentum_scalp",
                        3.01, 2.86, 3.31, 664, quote=quote,
                    )
        self.assertIn(ev["status"], ("PASS", "WARN"))
        self.assertTrue(ev["allowed"])
        self.assertGreaterEqual(ev["market"]["checks"].get("rr", 0), 1.2)

    def test_live_account_sizes_on_cash_base(self):
        with patch.object(ap, "equity_for_account", return_value=(71182.48, "test")):
            with patch.object(ap, "cash_for_account", return_value=(12000.0, "test")):
                with patch.object(bps, "account_activity_snapshot", return_value={"open_trades": 1, "new_trades_today": 0, "slots_used_today": 0}):
                    s = bps.compute_broker_sizing("schwab_taxable", "momentum_scalp", 3.01, 2.86)
        self.assertEqual(s.get("sizing_base_label"), "cash")
        self.assertEqual(s.get("engine"), "percent_cash")
        self.assertLessEqual(s["dollar_size"], 2000)

    def test_daily_limit_blocks(self):
        now = datetime.now(timezone.utc).isoformat()
        quote = {"last": 3.01, "bid": 3.00, "ask": 3.02, "spread_pct": 0.5, "quote_timestamp": now}
        activity = {
            "open_trades": 1, "new_trades_today": 3, "slots_used_today": 3,
            "max_new_positions_per_day": 3, "daily_limit_reached": True,
            "remaining_new_today": 0,
        }
        with patch.object(ap, "equity_for_account", return_value=(71182.48, "test")):
            with patch.object(ap, "cash_for_account", return_value=(50000.0, "test")):
                with patch.object(bps, "account_activity_snapshot", return_value=activity):
                    ev = bps.evaluate_broker_promote(
                        "schwab_taxable", "momentum_scalp", 3.01, 2.86, 3.31, 664, quote=quote,
                    )
        self.assertEqual(ev["status"], "BLOCK")
        self.assertTrue(any("Daily new-trade limit" in v for v in ev["violations"]))

    def test_cash_cap_binding(self):
        policy = {
            "sizing_engine": "percent_equity",
            "risk_per_trade_pct": 5.0,
            "max_position_allocation_pct": 20.0,
        }
        s = ap.compute_sizing(policy, 100000, 10.0, 9.0, cash_available=500)
        self.assertEqual(s["shares"], 50)
        self.assertEqual(s["binding"], "cash_cap")


if __name__ == "__main__":
    unittest.main()