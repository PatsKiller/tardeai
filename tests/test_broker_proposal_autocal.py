#!/usr/bin/env python3
"""Tests for broker_proposal_autocal.py"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from broker_proposal_autocal import (
    _is_stale_row,
    apply_live_quotes_to_rows,
    batch_live_quotes,
)


def test_stale_row_detects_old_updated_at():
    row = {"updated_at": (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()}
    assert _is_stale_row(row) is True


def test_fresh_row_not_stale():
    row = {"updated_at": datetime.now(timezone.utc).isoformat()}
    assert _is_stale_row(row) is False


def test_apply_live_quotes_clears_stale_zone():
    old = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    rows = [{
        "id": 1,
        "symbol": "DLR",
        "proposed_entry": 192.0,
        "proposed_stop": 182.4,
        "proposed_target1": 211.2,
        "current_price": 190.0,
        "updated_at": old,
        "strategy_id": "income",
    }]
    qmap = {
        "DLR": {
            "last": 196.0,
            "provider": "schwab",
            "refreshed_at": datetime.now(timezone.utc).isoformat()[:19],
        }
    }
    out = apply_live_quotes_to_rows(rows, qmap)
    assert out[0]["price_stale"] is False
    assert (out[0].get("thesis_validity") or {}).get("zone_status") != "stale_price"


def test_batch_live_quotes_mock():
    with patch("schwab_transport.get_quotes") as gq:
        gq.return_value = {
            "status": "ok",
            "quotes": {"AAA": {"last": 10.5, "bid": 10.4, "ask": 10.6}},
        }
        import schwab_transport  # noqa: F401 — ensure patch target exists
        with patch.dict("sys.modules", {"schwab_transport": type(sys)("schwab_transport")}):
            pass
    # smoke: empty symbols
    assert batch_live_quotes([]) == {}


if __name__ == "__main__":
    test_stale_row_detects_old_updated_at()
    test_fresh_row_not_stale()
    test_apply_live_quotes_clears_stale_zone()
    test_batch_live_quotes_mock()
    print("OK")