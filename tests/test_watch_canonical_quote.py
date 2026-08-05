#!/usr/bin/env python3
"""CASE-bound quote identity + freshness tests — same-record contract."""
from __future__ import annotations

import json
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
    apply_canonical_quote_overlay,
    unavailable_watch_quote_fields,
)

ET = ZoneInfo("America/New_York")


class TestComposeCaseBoundary(unittest.TestCase):
    def test_market_quotes_newer_uses_mq_day_change_pct(self):
        """market_quotes winner: price, change, timestamp, identity all from mq."""
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
        # Same-record: mq day_change_pct, NOT wi_change_pct
        self.assertAlmostEqual(art["day_change_pct"], -7.6, places=4)
        self.assertNotAlmostEqual(art["day_change_pct"], -9.9854, places=4)
        self.assertIsNotNone(art["price_as_of"])
        self.assertIsNotNone(art["market_session"])
        self.assertNotEqual(art["freshness_state"], "DATA_UNAVAILABLE")
        self.assertNotIn("mq_id_unused", art)
        self.assertNotIn("enrichment:99", str(art.get("quote_id")))

    def test_enrichment_newer_uses_wi_change_pct_no_mq_id(self):
        """enrichment winner: wi fields only; losing mq.id absent from artifact."""
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
        self.assertAlmostEqual(art["day_change_pct"], 2.5, places=4)
        # Losing mq.id must not appear anywhere in selected artifact
        self.assertNotIn("mq_id_unused", art)
        blob = json.dumps(art, default=str)
        self.assertNotIn("111", blob)
        self.assertNotIn("market_quotes:111", blob)
        self.assertNotEqual(art["quote_id"], 111)
        self.assertNotEqual(art["source_record_id"], "market_quotes:111")

    def test_missing_mq_id_fail_closed(self):
        """Price+timestamp present but mq_id absent → DATA_UNAVAILABLE."""
        mq_ts = datetime(2026, 8, 4, 16, 0, tzinfo=ET)
        art = compose_quote_artifact(
            symbol="X",
            mq_id=None,
            mq_price=10.0,
            mq_fetched_at=mq_ts,
            mq_source="alpaca",
            mq_day_change_pct=1.0,
            wi_id=None,
            wi_price=None,
            wi_last_enriched_at=None,
            wi_change_pct=None,
            now=mq_ts + timedelta(minutes=5),
        )
        self.assertIsNone(art["last"])
        self.assertIsNone(art["quote_id"])
        self.assertIsNone(art["source_record_id"])
        self.assertEqual(art["freshness_state"], "DATA_UNAVAILABLE")
        self.assertEqual(art["market_state"], "DATA_UNAVAILABLE")
        self.assertIn("canonical_quote_identity", art["missing"])
        self.assertEqual(art["winning_branch"], "market_quotes")

    def test_missing_wi_id_fail_closed(self):
        """Enrichment path without wi_id fails closed."""
        wi_ts = datetime(2026, 8, 4, 16, 0, tzinfo=ET)
        art = compose_quote_artifact(
            symbol="Y",
            mq_id=None,
            mq_price=None,
            mq_fetched_at=None,
            mq_source=None,
            mq_day_change_pct=None,
            wi_id=None,
            wi_price=11.0,
            wi_last_enriched_at=wi_ts,
            wi_change_pct=0.5,
            now=wi_ts + timedelta(minutes=5),
        )
        self.assertIsNone(art["last"])
        self.assertIsNone(art["quote_id"])
        self.assertEqual(art["freshness_state"], "DATA_UNAVAILABLE")
        self.assertIn("canonical_quote_identity", art["missing"])
        self.assertEqual(art["winning_branch"], "enrichment")

    def test_equal_timestamps_select_enrichment(self):
        """Documented branch: equal timestamps → enrichment (strict > for mq)."""
        ts = datetime(2026, 8, 4, 15, 0, tzinfo=ET)
        art = compose_quote_artifact(
            symbol="EQ",
            mq_id=7,
            mq_price=50.0,
            mq_fetched_at=ts,
            mq_source="alpaca",
            mq_day_change_pct=1.0,
            wi_id=8,
            wi_price=51.0,
            wi_last_enriched_at=ts,
            wi_change_pct=2.0,
            now=ts + timedelta(minutes=10),
        )
        self.assertEqual(art["winning_branch"], "enrichment")
        self.assertEqual(art["last"], 51.0)
        self.assertAlmostEqual(art["day_change_pct"], 2.0, places=4)
        self.assertEqual(art["quote_id"], "enrichment:8")
        blob = json.dumps(art, default=str)
        self.assertNotIn('"7"', blob.replace(" ", ""))
        # raw mq id 7 must not be quote_id
        self.assertNotEqual(art["quote_id"], 7)

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
        obs = datetime(2026, 8, 4, 15, 0, tzinfo=ET)
        now = datetime(2026, 8, 4, 15, 30, tzinfo=ET)
        fresh, session = derive_freshness(obs, now=now)
        self.assertEqual(session, "regular")
        self.assertEqual(fresh, "CURRENT")
        now2 = datetime(2026, 8, 4, 20, 30, tzinfo=ET)
        fresh2, _ = derive_freshness(obs, now=now2)
        self.assertEqual(fresh2, "STALE")

    def test_stale_timestamp_labeled_on_artifact(self):
        obs = datetime(2026, 8, 4, 10, 0, tzinfo=ET)
        now = datetime(2026, 8, 4, 16, 0, tzinfo=ET)  # 6h later → STALE
        art = compose_quote_artifact(
            symbol="ST",
            mq_id=1,
            mq_price=10.0,
            mq_fetched_at=obs,
            mq_source="alpaca",
            mq_day_change_pct=0.0,
            wi_id=None, wi_price=None, wi_last_enriched_at=None, wi_change_pct=None,
            now=now,
        )
        self.assertEqual(art["freshness_state"], "STALE")
        self.assertEqual(art["market_state"], "STALE")
        self.assertEqual(art["last"], 10.0)

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
            self.assertNotIn("mq_id_unused", art)
            if art.get("price_source") == "market_quotes":
                self.assertIsInstance(art["quote_id"], int)
                self.assertTrue(str(art["source_record_id"]).startswith("market_quotes:"))
            if art.get("price_source") == "enrichment":
                self.assertIsInstance(art["quote_id"], str)
                self.assertTrue(str(art["quote_id"]).startswith("enrichment:"))
                self.assertNotIsInstance(art["quote_id"], int)
                blob = json.dumps(art, default=str)
                # no raw market_quotes: prefix in enrichment artifact identity fields
                self.assertNotIn("market_quotes:", art.get("source_record_id") or "")


class TestUiProvenanceContract(unittest.TestCase):
    def test_watchcard_exposes_provenance_attrs(self):
        src = (ROOT / "apps/command-center-v3/src/components/rockville/WatchCardV2.tsx").read_text()
        for attr in (
            "data-quote-id",
            "data-source-record-id",
            "data-market-session",
            "data-freshness-state",
            "data-market-state",
            "quoteId",
            "sourceRecordId",
            "marketSession",
            "freshnessState",
            "marketState",
        ):
            self.assertIn(attr, src, msg=attr)
        hub = (ROOT / "apps/command-center-v3/src/pages/WatchHub.tsx").read_text()
        self.assertIn("quoteId={c.quote_id}", hub)
        self.assertIn("sourceRecordId={c.source_record_id}", hub)
        self.assertIn("freshnessState={c.freshness_state}", hub)


class TestOverlayFailClosed(unittest.TestCase):
    def _legacy_item(self, symbol="FTH", price=25.35, chg=-9.9):
        return {
            "symbol": symbol,
            "price": price,
            "change_pct": chg,
            "price_as_of": "2026-08-04T12:00:00-04:00",
            "price_source": "enrichment",
            "quote_id": "legacy-should-die",
            "source_record_id": "legacy:1",
        }

    def test_selector_raises_nulls_legacy_and_typed_error(self):
        items = [self._legacy_item("FTH"), self._legacy_item("NUAI", 5.0, 1.0)]

        def boom(_syms, **_kw):
            raise RuntimeError("db connection failed with secret=hunter2")

        apply_canonical_quote_overlay(items, batch_fn=boom)
        for it in items:
            self.assertIsNone(it["price"], msg=it["symbol"])
            self.assertIsNone(it["change_pct"], msg=it["symbol"])
            self.assertIsNone(it["price_as_of"], msg=it["symbol"])
            self.assertIsNone(it["price_source"], msg=it["symbol"])
            self.assertIsNone(it["quote_id"], msg=it["symbol"])
            self.assertIsNone(it["source_record_id"], msg=it["symbol"])
            self.assertIsNone(it["market_session"], msg=it["symbol"])
            self.assertEqual(it["freshness_state"], "DATA_UNAVAILABLE")
            self.assertEqual(it["market_state"], "DATA_UNAVAILABLE")
            self.assertEqual(it["quote_missing"], ["canonical_market_quote"])
            self.assertEqual(it["quote_error_code"], "CANONICAL_QUOTE_SELECTOR_FAILED")
            # legacy values must not survive
            self.assertNotEqual(it.get("price"), 25.35)
            self.assertNotIn("legacy-should-die", str(it.get("quote_id")))

    def test_selector_returns_no_artifact_fail_closed(self):
        items = [self._legacy_item("ZZZ", price=99.0, chg=3.0)]

        def empty(_syms, **_kw):
            return {}  # no per-symbol artifact

        apply_canonical_quote_overlay(items, batch_fn=empty)
        it = items[0]
        self.assertIsNone(it["price"])
        self.assertIsNone(it["change_pct"])
        self.assertEqual(it["freshness_state"], "DATA_UNAVAILABLE")
        self.assertEqual(it["quote_error_code"], "CANONICAL_QUOTE_SELECTOR_FAILED")
        self.assertIsNone(it["quote_id"])

    def test_data_unavailable_artifact_clears_legacy_price(self):
        items = [self._legacy_item("X", price=11.0, chg=2.0)]

        def ua(_syms, **_kw):
            return {
                "X": {
                    "symbol": "X",
                    "last": None,
                    "day_change_pct": None,
                    "price_as_of": None,
                    "price_source": None,
                    "quote_id": None,
                    "source_record_id": None,
                    "market_session": None,
                    "freshness_state": "DATA_UNAVAILABLE",
                    "market_state": "DATA_UNAVAILABLE",
                    "missing": ["canonical_market_quote"],
                    "winning_branch": None,
                }
            }

        apply_canonical_quote_overlay(items, batch_fn=ua)
        it = items[0]
        self.assertIsNone(it["price"])
        self.assertIsNone(it["change_pct"])
        self.assertEqual(it["freshness_state"], "DATA_UNAVAILABLE")
        self.assertNotEqual(it.get("price"), 11.0)

    def test_success_path_overlays_complete_artifact(self):
        items = [self._legacy_item("FTH", price=1.0, chg=0.0)]

        def ok(_syms, **_kw):
            return {
                "FTH": {
                    "symbol": "FTH",
                    "last": 25.35,
                    "day_change_pct": -7.6,
                    "price_as_of": "2026-08-04T16:45:00-04:00",
                    "price_source": "market_quotes",
                    "quote_id": 4386078,
                    "source_record_id": "market_quotes:4386078",
                    "market_session": "afterhours",
                    "freshness_state": "AFTER_HOURS_CURRENT",
                    "market_state": "OK",
                    "missing": [],
                    "winning_branch": "market_quotes",
                }
            }

        apply_canonical_quote_overlay(items, batch_fn=ok)
        it = items[0]
        self.assertEqual(it["price"], 25.35)
        self.assertAlmostEqual(it["change_pct"], -7.6, places=4)
        self.assertEqual(it["quote_id"], 4386078)
        self.assertEqual(it["source_record_id"], "market_quotes:4386078")
        self.assertEqual(it["freshness_state"], "AFTER_HOURS_CURRENT")
        self.assertNotIn("quote_error_code", it)

    def test_unavailable_helper_shape(self):
        f = unavailable_watch_quote_fields()
        self.assertIsNone(f["price"])
        self.assertEqual(f["quote_error_code"], "CANONICAL_QUOTE_SELECTOR_FAILED")
        self.assertEqual(f["freshness_state"], "DATA_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
