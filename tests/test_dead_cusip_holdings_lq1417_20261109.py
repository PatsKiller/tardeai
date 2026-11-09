"""LQ-20261107-1417: CUSIP-only, delisted (unpriced) holdings are ignored.

Synthetic fixtures only (public repo): the CUSIP-shaped strings below are
made up and do not identify real securities.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.security_identity import is_dead_cusip_holding  # noqa: E402

FAKE_CUSIP = "000000AA0"


def test_unpriced_cusip_is_dead():
    assert is_dead_cusip_holding({"symbol": FAKE_CUSIP, "current_price": 0.0, "market_value": 0.0})
    assert is_dead_cusip_holding({"symbol": FAKE_CUSIP, "current_price": None, "market_value": None})


def test_priced_cusip_is_kept():
    assert not is_dead_cusip_holding({"symbol": FAKE_CUSIP, "current_price": 98.5, "market_value": 0})
    assert not is_dead_cusip_holding({"symbol": FAKE_CUSIP, "current_price": 0, "market_value": 1000})


def test_ticker_without_price_is_not_dead():
    assert not is_dead_cusip_holding({"symbol": "ZZZT", "current_price": 0, "market_value": 0})
    assert not is_dead_cusip_holding(None)
    assert not is_dead_cusip_holding({"symbol": "", "market_value": 0})


def test_gain_guardian_skips_dead_cusip(tmp_path, monkeypatch):
    import holdings_gain_guardian as gg

    hold = tmp_path / "holdings.json"
    hold.write_text(json.dumps({
        "portfolio_totals": {"total_value": 10000},
        "holdings": [
            {"symbol": "ZZZT", "account": "acct_a", "market_value": 10000, "current_price": 100, "shares": 100},
            {"symbol": FAKE_CUSIP, "account": "acct_b", "market_value": 0.0, "current_price": 0.0, "shares": 50},
        ],
    }))
    monkeypatch.setattr(gg, "HOLDINGS_PATH", hold)
    syms = [h["symbol"] for h in gg._holdings({}, None)]
    assert syms == ["ZZZT"]
