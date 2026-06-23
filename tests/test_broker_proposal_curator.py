#!/usr/bin/env python3
"""Tests for broker_proposal_curator.py (unit — no DB required for criteria logic)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from datetime import datetime, timezone

from broker_proposal_curator import _criteria_from_row, MIN_LIVE_RR


def test_criteria_fresh_when_live_quote():
    row = {
        "proposed_entry": 100,
        "proposed_stop": 95,
        "proposed_target1": 115,
        "current_price": 101,
        "updated_at": (datetime.now(timezone.utc)).isoformat(),
        "quote_last": 101.5,
        "quote_provider": "schwab",
        "refreshed_at": datetime.now(timezone.utc).isoformat()[:19],
        "strategy_id": "momentum_scalp",
    }
    c = _criteria_from_row(row)
    assert c["status"] in ("fresh", "warn")
    assert c["price_stale"] is False


def test_criteria_stale_without_refresh():
    old = "2020-01-01T12:00:00+00:00"
    row = {
        "proposed_entry": 100,
        "proposed_stop": 95,
        "proposed_target1": 115,
        "current_price": 101,
        "updated_at": old,
        "strategy_id": "momentum_scalp",
    }
    c = _criteria_from_row(row)
    assert c["status"] == "stale"
    assert c["price_stale"] is True


def test_min_rr_env_readable():
    assert MIN_LIVE_RR >= 1.0


if __name__ == "__main__":
    test_criteria_fresh_when_live_quote()
    test_criteria_stale_without_refresh()
    test_min_rr_env_readable()
    print("OK")