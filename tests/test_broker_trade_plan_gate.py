#!/usr/bin/env python3
"""Tests for authoritative trade-plan gate (no generic 2R gambling)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import broker_trade_plan_gate as btpg


class TestBrokerTradePlanGate(unittest.TestCase):
    def test_rr_only_target_detected(self):
        entry, stop, target = 100.0, 95.0, 110.0
        self.assertTrue(btpg.is_rr_only_target(entry, stop, target, target_rr=2.0))

    def test_resistance_target_not_rr_only(self):
        entry, stop, target = 100.0, 95.0, 108.0
        self.assertFalse(btpg.is_rr_only_target(entry, stop, target, target_rr=2.0))

    def test_generic_sources_blocked(self):
        result = btpg.assess_broker_trade_plan(
            100.0, 95.0, 110.0, "core_growth_compounder",
            sizing_basis={
                "exit_rationale": {
                    "sources": [
                        "stop 5% below entry (generic fallback)",
                        "target 2.0:1 R:R policy (core_growth_compounder)",
                    ],
                    "target_rr_policy": 2.0,
                },
            },
        )
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["allowed"])
        self.assertTrue(any("gambling" in v.lower() or "authoritative" in v.lower() for v in result["violations"]))

    def test_authoritative_card_sources_pass(self):
        result = btpg.assess_broker_trade_plan(
            100.0, 95.0, 108.0, "core_growth_compounder",
            sizing_basis={
                "plan_source": "watchlist_strategy_card",
                "exit_rationale": {
                    "sources": [
                        "stop from watchlist strategy card",
                        "target above resistance $106.00 (level_based)",
                    ],
                },
            },
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["allowed"])

    def test_sleeve_strategy_blocked(self):
        result = btpg.assess_broker_trade_plan(
            50.0, 48.0, 55.0, "income",
            sizing_basis={"plan_source": "watchlist_strategy_card", "exit_rationale": {"sources": ["stop from watchlist strategy card"]}},
        )
        self.assertEqual(result["status"], "BLOCK")
        self.assertTrue(any("sleeve" in v.lower() for v in result["violations"]))

    def test_resolve_levels_none_without_anchor(self):
        conn = MagicMock()
        with patch.object(btpg, "_find_trade_plan", return_value=None):
            with patch.object(btpg, "_find_watchlist_card", return_value={
                "ideal_entry": 100.0, "stop_loss": None, "target_price": None,
                "support": None, "resistance": None,
            }):
                with patch.object(btpg, "_find_confluence", return_value=None):
                    out = btpg.resolve_authoritative_levels(conn, "MS", candidate={"symbol": "MS"}, quote_cache={"MS": 100.0})
        self.assertIsNone(out)

    def test_resolve_levels_from_trade_plans(self):
        conn = MagicMock()
        plan = {
            "id": 42, "strategy_id": "core_growth_compounder",
            "entry_high": 100.0, "entry_low": 99.0,
            "stop_loss": 95.0, "target_1": 108.0,
        }
        with patch.object(btpg, "_find_trade_plan", return_value=plan):
            out = btpg.resolve_authoritative_levels(conn, "MS")
        self.assertIsNotNone(out)
        self.assertEqual(out["plan_source"], "trade_plans")
        self.assertEqual(out["entry"], 100.0)
        self.assertEqual(out["stop"], 95.0)
        self.assertEqual(out["target"], 108.0)


if __name__ == "__main__":
    unittest.main()