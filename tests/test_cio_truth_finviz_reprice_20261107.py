"""CIO truth marks every non-cash holding at the Finviz live price (operator 2026-11-07). Synthetic fixtures only."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
from lib import cio_truth as ct  # noqa: E402

NOW = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
DOC = {"holdings": [
    {"account": "acct_a", "symbol": "ZZTA", "shares": 10, "price": 20.0, "market_value": 200.0, "day_change": 5.0,
     "price_source": "finviz_elite"},
    {"account": "acct_a", "symbol": "ZZNB", "shares": 4, "price": 50.0, "market_value": 200.0, "day_change": None},
    {"account": "acct_a", "symbol": "CASH", "is_cash": True, "shares": 100, "market_value": 100.0},
]}
FV = {"ZZTA": {"price": 18.0, "last_fetched": "2026-10-05 23:50:00 ET"}, "_meta": {"x": 1}}


def test_rows_take_the_finviz_price_value_and_day_delta():
    out = ct.finviz_reprice(DOC, FV, now=NOW)["holdings"]
    a = out[0]
    assert a["price"] == 18.0 and a["market_value"] == 180.0 and a["price_source"] == "finviz"
    assert a["day_change"] == -15.0          # 5 + (18 - 20) * 10
    assert out[1]["price"] == 50.0 and out[1].get("price_source") is None   # no Finviz row: stored mark kept
    assert out[2]["market_value"] == 100.0
    assert DOC["holdings"][0]["price"] == 20.0   # input never mutated


def test_portfolio_total_uses_the_finviz_mark():
    p = ct.portfolio_for(ct.finviz_reprice(DOC, FV, now=NOW), now=NOW)
    assert p["total_usd"] == 480.0


def test_no_cache_changes_nothing():
    assert ct.finviz_reprice(DOC, {}, now=NOW) is DOC


def test_backup_broker_quote_serves_when_finviz_is_stale():
    stale_fv = {"ZZTA": {"price": 18.0, "last_fetched": "2026-10-05 20:00:00 ET"}}
    q = {"ZZTA": {"price": 19.0, "as_of": "2026-10-06T03:55:00+00:00", "source": "data_broker.market_quotes:schwab"}}
    a = ct.finviz_reprice(DOC, stale_fv, now=NOW, quotes=q)["holdings"][0]
    assert a["price"] == 19.0 and "schwab" in a["price_source"] and a["price_stale"] is False


def test_yfinance_is_never_a_backup():
    q = {"ZZTA": {"price": 19.0, "as_of": "2026-10-06T03:55:00+00:00", "source": "data_broker.market_quotes:yfinance"}}
    a = ct.finviz_reprice(DOC, {}, now=NOW, quotes=q)["holdings"][0]
    assert a["price"] == 20.0   # stored mark kept; no approved live source
