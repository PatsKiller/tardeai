#!/usr/bin/env python3
"""Tests for broker queue hygiene + symbol-active guards."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import broker_queue_hygiene as bqh


class TestBrokerQueueHygiene(unittest.TestCase):
    def test_classify_past_expiry(self):
        now = datetime(2026, 6, 23, 18, 0, tzinfo=timezone.utc)
        row = {
            "id": 282,
            "symbol": "CRMT",
            "strategy_id": "momentum_scalp",
            "proposed_entry": 3.01,
            "proposed_stop": 2.86,
            "current_price": 2.97,
            "price_drift_pct": -1.3,
            "created_at": now - timedelta(hours=20),
            "expires_at": now - timedelta(hours=2),
        }
        clf = bqh.classify_broker_queue_row(row, now=now)
        self.assertEqual(clf["action"], "expire")
        self.assertIn("expires_at", clf["reasons"][0])

    def test_classify_entry_missed_drift(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": 1,
            "symbol": "TEST",
            "strategy_id": "momentum_scalp",
            "proposed_entry": 10.0,
            "proposed_stop": 9.0,
            "price_drift_pct": 5.0,
            "created_at": now - timedelta(hours=2),
            "expires_at": now + timedelta(hours=4),
        }
        clf = bqh.classify_broker_queue_row(row, now=now)
        self.assertEqual(clf["action"], "expire")

    def test_classify_superseded(self):
        now = datetime.now(timezone.utc)
        older = {
            "id": 282,
            "symbol": "CRMT",
            "strategy_id": "momentum_scalp",
            "proposed_entry": 3.01,
            "created_at": now - timedelta(days=1),
            "expires_at": now + timedelta(hours=2),
        }
        newer = {"id": 284, "created_at": now, "origin": "auto"}
        clf = bqh.classify_broker_queue_row(older, now=now, newer_same_symbol=newer)
        self.assertEqual(clf["action"], "reject")
        self.assertTrue(any("Superseded" in r for r in clf["reasons"]))

    def test_classify_keep_fresh(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": 1,
            "symbol": "FRESH",
            "strategy_id": "momentum_scalp",
            "proposed_entry": 10.0,
            "proposed_stop": 9.5,
            "price_drift_pct": 0.5,
            "created_at": now - timedelta(hours=1),
            "expires_at": now + timedelta(hours=6),
        }
        clf = bqh.classify_broker_queue_row(row, now=now)
        self.assertEqual(clf["action"], "keep")

    def test_active_symbol_statuses_include_approved(self):
        self.assertIn("APPROVED_FOR_PAPER_TEST", bqh.ACTIVE_SYMBOL_STATUSES)

    def test_classify_thesis_invalid_watchlist(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": 99,
            "symbol": "TEST",
            "strategy_id": "momentum_scalp",
            "origin": "watchlist",
            "proposed_entry": 10.0,
            "proposed_stop": 9.0,
            "proposed_target1": 12.0,
            "created_at": now - timedelta(hours=2),
            "thesis_validity": {"ok": True, "zone_status": "invalid"},
        }
        clf = bqh.classify_broker_queue_row(row, now=now)
        self.assertEqual(clf["action"], "expire")
        self.assertTrue(any("invalid" in r.lower() for r in clf["reasons"]))

    def test_classify_at_risk_young_keeps(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": 100,
            "symbol": "YOUNG",
            "strategy_id": "momentum_scalp",
            "origin": "watchlist",
            "proposed_entry": 10.0,
            "proposed_stop": 9.5,
            "proposed_target1": 11.5,
            "price_drift_pct": 0.2,
            "created_at": now - timedelta(hours=6),
            "expires_at": now + timedelta(days=2),
            "thesis_validity": {"ok": True, "zone_status": "at_risk"},
        }
        clf = bqh.classify_broker_queue_row(row, now=now)
        self.assertEqual(clf["action"], "keep")


if __name__ == "__main__":
    unittest.main()