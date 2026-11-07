"""Regression tests for the 2026-11-07 price-fold review findings (LQ-20261107-03/-14 follow-up)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import defense_cash_alternatives as dca  # noqa: E402
import stop_drift_alert as sda  # noqa: E402
from lib import stop_alert_price as sap  # noqa: E402


def test_sub_dollar_price_never_rounds_to_zero():
    assert sda._px_round(0.0003) == 0.0003
    assert sda._px_round(0.123456) == 0.1235
    assert sda._px_round(12.3456) == 12.35


def test_unpriced_held_row_is_kept_when_asked():
    doc = {"holdings": [{"symbol": "FUND", "account": "acct_a", "canonical_mark_type": "proxy",
                         "not_for_valuation": True, "shares": 10, "price": 5.0}]}
    assert sap.holdings_marks(doc, finviz={}, quotes={}) == []
    kept = sap.holdings_marks(doc, finviz={}, quotes={}, keep_unpriced=True)
    assert len(kept) == 1 and kept[0]["shares"] == 10 and kept[0]["price"] is None


def _query_factory(mq_rows, tp_rows):
    def query(sql, params):
        return mq_rows if "market_quotes" in sql else tp_rows
    return query


def test_defense_day_old_close_is_flagged_stale():
    now = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
    q = _query_factory([], [{"symbol": "BBB", "close_price": 20.0, "price_date": now - timedelta(days=1)}])
    out = dca.load_prices(q, ["BBB"], now=now)
    assert out["BBB"]["stale"] is True


def test_defense_market_quote_carries_provider_and_yfinance_is_not_fresh():
    now = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
    q = _query_factory([{"symbol": "CCC", "price": 10.0, "day_change_pct": 0.1, "volume": 1,
                         "fetched_at": now - timedelta(minutes=2), "provider": "yfinance"}], [])
    out = dca.load_prices(q, ["CCC"], now=now)
    row = out["CCC"]
    assert row["source"] == "market_quotes:yfinance"
    assert row["stale"] is True  # a yfinance quote is never a fresh mark


def test_api_v2_fresh_batch_refuses_yfinance(monkeypatch):
    import api_v2
    from lib.data_broker import market_quote

    def fake_batch(q, syms, **kw):
        return {"AAA": {"price": 5.0, "as_of": None, "source": "data_broker.market_quotes:yfinance"},
                "BBB": {"price": 6.0, "as_of": None, "source": "finviz_quote_cache"}}
    monkeypatch.setattr(market_quote, "get_price_batch", fake_batch)
    out = api_v2._fresh_price_batch(["AAA", "BBB"])
    assert "AAA" not in out and out["BBB"]["price"] == 6.0
