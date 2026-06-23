#!/usr/bin/env python3
"""Tests for Schwab quote provider + session-aware freshness gates."""
import json
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_quote_provider import (
    _parse_schwab_timestamp,
    fetch_schwab_quote,
    resolve_quote_max_age_minutes,
    check_fresh_quote,
    INTRADAY_MAX_AGE_MINUTES,
    SWING_EXTENDED_MAX_AGE_MINUTES,
)


class TestSchwabTimestamp(unittest.TestCase):
    def test_ms_epoch(self):
        dt = _parse_schwab_timestamp(1710000000000)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_iso_string(self):
        dt = _parse_schwab_timestamp("2026-06-22T20:15:00Z")
        self.assertEqual(dt.year, 2026)


class TestSchwabQuoteFetch(unittest.TestCase):
    @patch("schwab_transport.get_quotes")
    def test_fetch_normalizes_bid_ask(self, mock_get):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        mock_get.return_value = {
            "status": "ok",
            "quotes": {
                "AAPL": {
                    "last": 195.50,
                    "bid": 195.45,
                    "ask": 195.55,
                    "volume": 1200000,
                    "updated": now_ms,
                }
            },
        }
        q = fetch_schwab_quote("AAPL")
        self.assertIsNotNone(q)
        self.assertEqual(q["provider"], "schwab")
        self.assertEqual(q["last_price"], 195.50)
        self.assertTrue(q["is_execution_eligible"])

    @patch("schwab_transport.get_quotes")
    def test_fetch_missing_returns_none(self, mock_get):
        mock_get.return_value = {"status": "needs_account_link"}
        self.assertIsNone(fetch_schwab_quote("AAPL"))


class TestSessionAwareFreshness(unittest.TestCase):
    def test_intraday_always_15(self):
        self.assertEqual(resolve_quote_max_age_minutes("momentum_scalp", session="afterhours"),
                         INTRADAY_MAX_AGE_MINUTES)

    def test_swing_relaxes_afterhours(self):
        self.assertEqual(resolve_quote_max_age_minutes("swing_breakout", session="afterhours"),
                         SWING_EXTENDED_MAX_AGE_MINUTES)

    def test_swing_strict_during_regular(self):
        self.assertEqual(resolve_quote_max_age_minutes("swing_breakout", session="regular"),
                         INTRADAY_MAX_AGE_MINUTES)

    @patch("market_quote_provider.get_best_quote")
    @patch("market_session.current_market_session", return_value="afterhours")
    def test_afterhours_blocks_finviz_for_swing(self, _sess, mock_best):
        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_best.return_value = {
            "provider": "finviz_cache",
            "last_price": 42.0,
            "quote_timestamp": stale_ts,
            "is_delayed": True,
        }
        r = check_fresh_quote("EVC", strategy_id="swing_breakout")
        self.assertFalse(r["ok"])
        self.assertIn("afterhours_requires_realtime_provider", r["reason"])

    @patch("market_quote_provider.get_best_quote")
    @patch("market_session.current_market_session", return_value="afterhours")
    def test_afterhours_accepts_schwab_for_swing(self, _sess, mock_best):
        fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        mock_best.return_value = {
            "provider": "schwab",
            "last_price": 42.0,
            "bid": 41.9,
            "ask": 42.1,
            "quote_timestamp": fresh_ts,
            "is_delayed": False,
        }
        r = check_fresh_quote("EVC", strategy_id="swing_breakout")
        self.assertTrue(r["ok"])
        self.assertEqual(r["provider"], "schwab")


if __name__ == "__main__":
    unittest.main()