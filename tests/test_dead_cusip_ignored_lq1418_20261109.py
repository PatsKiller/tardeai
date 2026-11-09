"""ANCHOR: DEAD_CUSIP_IGNORED_LQ1418_20261109 — read-side ignore of CUSIP-only delisted holdings.

Synthetic symbols only (public repo). Does not read the live book, a broker, or a network quote.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DEAD = "000000AA0"
PRICED = "000000BB1"
TICKER = "ZZZT"
NOW = datetime(2026, 11, 9, 5, 40, tzinfo=timezone.utc)


def _book() -> dict:
    return {
        "holdings": [
            {"symbol": TICKER, "account": "acct-a", "current_price": 10.0, "market_value": 50.0, "shares": 5},
            {"symbol": DEAD, "account": "acct-a", "current_price": 0, "market_value": 0, "shares": 3},
            {"symbol": PRICED, "account": "acct-a", "current_price": 12.5, "market_value": 100.0, "shares": 8},
        ],
        "positions": [
            {"symbol": DEAD, "current_price": None, "market_value": None},
            {"symbol": TICKER, "current_price": 10.0, "market_value": 50.0},
        ],
        "accounts": [
            {"id": "acct-a", "holdings": [
                {"symbol": DEAD, "current_price": 0, "market_value": 0},
                {"symbol": TICKER, "current_price": 10.0, "market_value": 50.0},
            ]},
        ],
    }


def _symbols(rows) -> list[str]:
    return [str(r.get("symbol")) for r in rows]


def test_document_filter_drops_only_the_unpriced_cusip():
    from scripts.lib.dead_cusip_holdings import without_dead_cusip_holdings

    out = without_dead_cusip_holdings(_book())
    assert _symbols(out["holdings"]) == [TICKER, PRICED]
    assert _symbols(out["positions"]) == [TICKER]
    assert _symbols(out["accounts"][0]["holdings"]) == [TICKER]
    assert without_dead_cusip_holdings(None) == {}
    assert without_dead_cusip_holdings({"holdings": "nope"}).get("holdings") == "nope"


def test_load_document_file_fallback_hides_the_dead_row(tmp_path: Path):
    from scripts.lib.holdings_document import load_document

    store = tmp_path / "holdings.json"
    store.write_text(json.dumps(_book()), encoding="utf-8")  # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture under pytest tmp_path, not a live store
    doc = load_document(store, use_cache=False)
    assert DEAD not in _symbols(doc["holdings"])
    assert TICKER in _symbols(doc["holdings"])
    assert PRICED in _symbols(doc["holdings"])


def _alert_policy() -> dict:
    return {
        "promo_positions": [],
        "opt_in": [],
        "promo_max_usd": 100.0,
        "de_minimis_usd": 100.0,
        "exclude_promo_from_stop_exit_alerts": True,
        "exclude_tiny_from_stop_exit_alerts": True,
    }


def test_alerts_skip_an_injected_dead_row(tmp_path: Path):
    from scripts.lib.held_position_alerts import load_holdings, positions_for

    path = tmp_path / "holdings.json"
    path.write_text(json.dumps(_book()), encoding="utf-8")  # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture under pytest tmp_path, not a live store
    loaded = load_holdings(path)
    assert DEAD not in _symbols(loaded["holdings"])
    assert positions_for(DEAD, _book(), policy=_alert_policy()) == []
    assert positions_for(TICKER, _book(), policy=_alert_policy())


def test_office_and_portfolio_state_drop_the_dead_row(tmp_path: Path):
    from scripts.lib.cio_office_state import compact_holdings_rows, load_holdings_document as office_load
    from scripts.lib.cio_portfolio_state_v1 import build_portfolio_state
    from scripts.lib.cio_portfolio_state_v1 import load_holdings_document as state_load

    path = tmp_path / "holdings.json"
    path.write_text(json.dumps(_book()), encoding="utf-8")  # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture under pytest tmp_path, not a live store
    office = office_load(path)
    assert DEAD not in _symbols(office["holdings"])
    assert DEAD not in _symbols(compact_holdings_rows(_book()))
    state = state_load(path)
    assert DEAD not in _symbols(state["holdings"])
    built = build_portfolio_state(_book())
    assert DEAD not in [p["symbol"] for p in built["positions"]]
    assert TICKER in [p["symbol"] for p in built["positions"]]


def test_canonical_marks_keep_the_broker_row_and_skip_the_quote(tmp_path: Path):
    from scripts.reconcile_holdings_canonical_marks import reconcile

    original = {"symbol": DEAD, "account": "acct-a", "current_price": 0, "market_value": 0, "shares": 3}
    doc = {"holdings": [dict(original), {"symbol": TICKER, "account": "acct-a", "shares": 5,
                                         "current_price": 10, "market_value": 50, "is_cash": False}]}
    out = reconcile(doc, NOW)
    dead = next(r for r in out["holdings"] if r["symbol"] == DEAD)
    live = next(r for r in out["holdings"] if r["symbol"] == TICKER)
    assert dead == original
    assert "transformed_at" not in dead
    assert live.get("transformed_at")
    assert not (tmp_path / "holdings.json").exists()


def test_quote_backup_uses_finviz_cache_and_ignores_a_cusip(monkeypatch):
    import scripts.lib.gap_resolver as gr
    import scripts.lib.portfolio_positions as pp

    class Boom:
        def Ticker(self, *_a, **_k):
            raise AssertionError("quote library called")

        def download(self, *_a, **_k):
            raise AssertionError("download called")

    monkeypatch.setitem(sys.modules, "yfinance", Boom())
    calls = {"n": 0}

    def fake_cache(path=None):
        calls["n"] += 1
        return {TICKER: {"price": 11.0, "as_of": "2026-11-09T00:00:00Z", "source": "finviz"}}

    monkeypatch.setattr(pp, "finviz_cache", fake_cache)
    ctx = gr.Context(now=lambda: NOW, live=True)
    quote = gr._yf_quote(gr.DataGap(domain="quote_price", subject=TICKER, question="price"), ctx)
    assert quote.outcome == "answered"
    assert quote.provider == "finviz"
    assert quote.answer["price"] == 11.0
    assert calls["n"] == 1

    def refuse_cache(path=None):
        raise AssertionError("cache read for a cusip")

    monkeypatch.setattr(pp, "finviz_cache", refuse_cache)
    ignored = gr._yf_quote(gr.DataGap(domain="quote_price", subject=DEAD, question="price"), ctx)
    assert ignored.outcome == "no_answer"
    assert ignored.provider == "finviz"

    analyst = gr._yf_analyst(gr.DataGap(domain="analyst_opinion", subject=TICKER, question="analyst"), ctx)
    assert analyst.outcome == "no_answer"
    assert analyst.provider == "yfinance_on_demand"


def test_seasonality_network_helper_does_not_download(monkeypatch):
    from scripts.lib.cio_seasonality_analytics import _try_public_monthly_returns, load_monthly_returns

    class Boom:
        @staticmethod
        def download(*_a, **_k):
            raise AssertionError("download called")

    monkeypatch.setitem(sys.modules, "yfinance", Boom())
    assert _try_public_monthly_returns() == []
    rows = load_monthly_returns(allow_network=True)
    assert rows
    assert all(r.get("source") != "yfinance_GSPC" for r in rows)


def test_multi_source_refresh_skips_cusip_and_reads_finviz(monkeypatch, tmp_path: Path):
    import scripts.lib.multi_source_quote_refresh as mod

    class Boom:
        def Tickers(self, *_a, **_k):
            raise AssertionError("quote library called")

    monkeypatch.setitem(sys.modules, "yfinance", Boom())
    urls: list[str] = []

    def no_network(url, timeout=5):
        urls.append(str(url))
        raise OSError("no network in this test")

    monkeypatch.setattr(mod, "_cc_urlopen", no_network)
    cache = tmp_path / "data" / "portfolios" / "state" / "finviz_quote_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({  # nosemgrep: tq-py-nonatomic-store-write -- synthetic quote cache under pytest tmp_path, not a live store
        TICKER: {"price": 11.25, "source": "finviz", "last_fetched": "2026-11-09T00:00:00Z"},
        DEAD: {"price": 4.0, "source": "finviz", "last_fetched": "2026-11-09T00:00:00Z"},
    }), encoding="utf-8")
    result = mod.MultiSourceRefresh(str(tmp_path))._do_refresh()
    assert result["status"] == "refreshed"
    assert result["symbols"] == 1
    assert urls
    assert all(DEAD not in u for u in urls)
    assert all(TICKER in u for u in urls)
