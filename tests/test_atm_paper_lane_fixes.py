#!/usr/bin/env python3
"""Tests for ATM paper-lane fixes: curated Finviz skip, entry sanity, dual-lane sync."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCuratedFinvizSkip(unittest.TestCase):

    def test_watchlist_proposal_is_curated(self):
        from atm_proposal_source_policy import is_curated_proposal
        p = {
            "discovery_source": "watchlist",
            "origin": "watchlist",
            "proposed_by": "watchlist_proposal_bridge",
        }
        self.assertTrue(is_curated_proposal(p))

    def test_atm_select_includes_curated_fields(self):
        src = (PROJECT_ROOT / "scripts/atm_auto_approver.py").read_text()
        self.assertIn("p.discovery_source", src)
        self.assertIn("p.origin", src)
        self.assertIn("p.proposed_by", src)

    def test_curated_paper_fast_track(self):
        from atm_proposal_source_policy import atm_enrichment_bypass
        ok, reason = atm_enrichment_bypass(
            {
                "discovery_source": "watchlist",
                "origin": "watchlist",
                "proposed_entry": 4.8,
                "proposed_stop": 4.31,
                "proposed_target1": 9.23,
                "proposed_rr": 9.04,
                "risk_gate_result": "APPROVED",
            },
            acct_mode="paper",
            proposal_age_hours=0.5,
        )
        self.assertTrue(ok)
        self.assertIn("curated", reason)


class TestEntrySanity(unittest.TestCase):

    def test_rejects_absurd_entry_vs_live(self):
        from broker_trade_plan_gate import entry_live_drift_ok
        self.assertFalse(entry_live_drift_ok(1.26, 11.08))
        self.assertTrue(entry_live_drift_ok(4.8, 4.93))

    def test_resolve_levels_skips_stale_limit(self):
        from broker_trade_plan_gate import resolve_authoritative_levels
        conn = MagicMock()
        with patch("broker_trade_plan_gate._find_trade_plan", return_value=None), \
             patch("broker_trade_plan_gate._find_watchlist_card", return_value={
                 "ideal_entry": 1.26, "stop_loss": 1.1, "target_price": 1.5,
                 "support": 1.1, "resistance": 1.5,
             }), \
             patch("broker_trade_plan_gate._find_confluence", return_value=None), \
             patch("broker_trade_plan_gate._live_reference_price", return_value=11.08), \
             patch("broker_strategy_resolver.resolve_executable_strategy", return_value={"strategy_id": "momentum_scalp"}), \
             patch("broker_strategy_resolver.apply_strategy_exit_plan", side_effect=lambda e, s, t, *a, **k: (e, s, t, {"sources": ["stop from watchlist strategy card"]})):
            out = resolve_authoritative_levels(
                conn, "DJTU",
                candidate={"limit_price": 1.26, "symbol": "DJTU"},
                quote_cache={"DJTU": 11.08},
            )
        self.assertIsNone(out)


class TestDualLaneSync(unittest.TestCase):

    def test_classify_entry_zone_wide(self):
        from proposal_enrichment_loop import classify_entry_zone
        self.assertEqual(classify_entry_zone(13.0, "swing"), "ENTRY_MISSED")
        self.assertEqual(classify_entry_zone(15.1, "swing"), "ENTRY_MISSED")
        self.assertEqual(classify_entry_zone(4.0, "swing"), "ENTRY_ZONE_VALID")

    def test_sync_helper_present(self):
        src = (PROJECT_ROOT / "scripts/proposal_enrichment_loop.py").read_text()
        self.assertIn("_sync_watchlist_dual_lane_prices", src)
        self.assertIn("dual_lane_sync", src)


if __name__ == "__main__":
    unittest.main()