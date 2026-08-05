#!/usr/bin/env python3
"""CASE-bound quote identity + freshness tests."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.watch_canonical_quote import (  # noqa: E402
    compose_quote_artifact,
    derive_freshness,
    market_session_for,
    batch_canonical_quotes,
)

ET = ZoneInfo("America/New_York")


class TestComposeCaseBoundary(unittest.TestCase):
    def test_market_quotes_newer_wins_identity(self):
        mq_ts = datetime(2026, 8, 4, 16, 45, tzinfo=ET)
        wi_ts = datetime(2026, 8, 4, 12, 0, tzinfo=ET)
        art = compose_quote_artifact(
            symbol="FTH",
            mq_id=4386078,
            mq_price=25.35,
            mq_fetched_at=mq_ts,
            mq_source="alpaca",
            mq_day_change_pct=-7.6,
            wi_id=99,
            wi_price=24.7,
            wi_last_enriched_at=wi_ts,
            wi_change_pct=-9.9854,
            now=mq_ts + timedelta(minutes=10),
        )
        self.assertEqual(art["winning_branch"], "market_quotes")
        self.assertEqual(art["last"], 25.35)
        self.assertEqual(art["price_source"], "market_quotes")
        self.assertEqual(art["quote_id"], 4386078)
        self.assertEqual(art["source_record_id"], "market_quotes:4386078")
        self.assertNotIn("enrichment:99", str(art["quote_id"]))
        # change_pct from watchlist for list coherence
        self.assertAlmostEqual(art["day_change_pct"], -9.9854, places=4)
        self.assertIsNotNone(art["price_as_of"])
        self.assertIsNotNone(art["market_session"])
        self.assertNotEqual(art["freshness_state"], "DATA_UNAVAILABLE")

    def test_enrichment_newer_wins_no_mq_id(self):
        mq_ts = datetime(2026, 8, 4, 10, 0, tzinfo=ET)
        wi_ts = datetime(2026, 8, 4, 16, 0, tzinfo=ET)
        art = compose_quote_artifact(
            symbol="ZZZ",
            mq_id=111,
            mq_price=99.0,
            mq_fetched_at=mq_ts,
            mq_source="alpaca",
            mq_day_change_pct=1.0,
            wi_id=55,
            wi_price=100.0,
            wi_last_enriched_at=wi_ts,
            wi_change_pct=2.5,
            now=wi_ts + timedelta(minutes=5),
        )
        self.assertEqual(art["winning_branch"], "enrichment")
        self.assertEqual(art["last"], 100.0)
        self.assertEqual(art["price_source"], "enrichment")
        self.assertEqual(art["quote_id"], "enrichment:55")
        self.assertEqual(art["source_record_id"], "watchlist_items:55")
        # Older mq.id must not be the selected identity
        self.assertNotEqual(art["quote_id"], 111)
        self.assertNotEqual(art["source_record_id"], "market_quotes:111")
        self.assertEqual(art.get("mq_id_unused"), 111)

    def test_missing_timestamp_fail_closed(self):
        art = compose_quote_artifact(
            symbol="X",
            mq_id=1, mq_price=10.0, mq_fetched_at=None, mq_source="alpaca", mq_day_change_pct=0,
            wi_id=2, wi_price=11.0, wi_last_enriched_at=None, wi_change_pct=0,
        )
        self.assertIsNone(art["last"])
        self.assertEqual(art["freshness_state"], "DATA_UNAVAILABLE")
        self.assertIn("canonical_market_quote", art["missing"])

    def test_future_dated_rejected(self):
        now = datetime(2026, 8, 4, 12, 0, tzinfo=ET)
        future = now + timedelta(hours=5)
        art = compose_quote_artifact(
            symbol="X",
            mq_id=1, mq_price=10.0, mq_fetched_at=future, mq_source="alpaca", mq_day_change_pct=0,
            wi_id=None, wi_price=None, wi_last_enriched_at=None, wi_change_pct=None,
            now=now,
        )
        self.assertEqual(art["freshness_state"], "DATA_UNAVAILABLE")
        self.assertIsNone(art["last"])


class TestFreshnessDerived(unittest.TestCase):
    def test_rth_current_vs_stale(self):
        # Tuesday 15:00 ET quote, now 15:30 ET → CURRENT
        obs = datetime(2026, 8, 4, 15, 0, tzinfo=ET)  # Tuesday
        now = datetime(2026, 8, 4, 15, 30, tzinfo=ET)
        fresh, session = derive_freshness(obs, now=now)
        self.assertEqual(session, "regular")
        self.assertEqual(fresh, "CURRENT")
        # 5 hours later → STALE
        now2 = datetime(2026, 8, 4, 20, 30, tzinfo=ET)
        fresh2, session2 = derive_freshness(obs, now=now2)
        self.assertEqual(fresh2, "STALE")

    def test_afterhours_label(self):
        obs = datetime(2026, 8, 4, 17, 0, tzinfo=ET)
        now = datetime(2026, 8, 4, 17, 30, tzinfo=ET)
        fresh, session = derive_freshness(obs, now=now)
        self.assertEqual(session, "afterhours")
        self.assertEqual(fresh, "AFTER_HOURS_CURRENT")

    def test_premarket_label(self):
        obs = datetime(2026, 8, 4, 7, 0, tzinfo=ET)
        now = datetime(2026, 8, 4, 7, 30, tzinfo=ET)
        fresh, session = derive_freshness(obs, now=now)
        self.assertEqual(session, "premarket")
        self.assertEqual(fresh, "PREMARKET_CURRENT")

    def test_session_for_observation(self):
        self.assertEqual(market_session_for(datetime(2026, 8, 4, 10, 0, tzinfo=ET)), "regular")
        self.assertEqual(market_session_for(datetime(2026, 8, 4, 5, 0, tzinfo=ET)), "premarket")
        self.assertEqual(market_session_for(datetime(2026, 8, 4, 18, 0, tzinfo=ET)), "afterhours")


class TestLiveCoherenceIdentity(unittest.TestCase):
    def test_live_symbols_have_coherent_identity(self):
        arts = batch_canonical_quotes(["FTH", "NUAI", "AXTI", "SWBI", "CECO", "PFLT"])
        for sym, art in arts.items():
            if art.get("last") is None:
                self.assertEqual(art.get("freshness_state"), "DATA_UNAVAILABLE")
                continue
            self.assertIsNotNone(art.get("price_as_of"), sym)
            self.assertIsNotNone(art.get("quote_id"), sym)
            self.assertIsNotNone(art.get("source_record_id"), sym)
            self.assertIsNotNone(art.get("market_session"), sym)
            self.assertIn(art.get("freshness_state"), {
                "CURRENT", "PREMARKET_CURRENT", "AFTER_HOURS_CURRENT", "STALE", "DATA_UNAVAILABLE",
            }, sym)
            if art.get("price_source") == "market_quotes":
                self.assertIsInstance(art["quote_id"], int)
                self.assertTrue(str(art["source_record_id"]).startswith("market_quotes:"))
            if art.get("price_source") == "enrichment":
                self.assertIsInstance(art["quote_id"], str)
                self.assertTrue(str(art["quote_id"]).startswith("enrichment:"))
                # must not use raw mq int as identity
                self.assertNotIsInstance(art["quote_id"], int)


if __name__ == "__main__":
    unittest.main()
