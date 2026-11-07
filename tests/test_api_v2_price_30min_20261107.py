"""api_v2 serves a current price or nothing (LQ-20261107-07, operator price rule 2026-11-07).

Operator, verbatim: "a live price comes from Finviz (finviz_quote_cache.json, fresh = last_fetched <= 30 min);
if Finviz is down or stale, a fresh Schwab / Alpaca / moomoo quote; never yfinance, never a stored DB price
older than 30 min."

Before this change six request paths in `scripts/api_v2.py` read a stored `market_quotes` row of ANY age and
served it as the current price, and the holdings fallback labelled a zero-dollar broker CUSIP row
'technical_snapshot' although Schwab itself reported broker_market_value 0.0.

Every fixture here is synthetic: the repository is public.

ANCHOR: API_V2_PRICE_30MIN_20261107
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import api_v2  # noqa: E402


# ── the timestamp spelling the Finviz cache uses ───────────────────────────────────────────────


def test_et_spelling_becomes_an_iso_instant_with_its_own_offset():
    """"2026-11-07 01:45:01 ET" is not ISO; downstream freshness parsing drops the price as
    DATA_UNAVAILABLE if it is passed through unchanged."""
    out = api_v2._iso_quote_time("2026-11-07 01:45:01 ET")

    assert " ET" not in out
    parsed = __import__("datetime").datetime.fromisoformat(out)
    assert parsed.utcoffset() is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour) == (2026, 11, 7, 1)


def test_an_iso_timestamp_passes_through_and_junk_stays_junk():
    assert api_v2._iso_quote_time("2026-11-07T06:30:01+00:00") == "2026-11-07T06:30:01+00:00"
    assert api_v2._iso_quote_time("not a timestamp") == "not a timestamp"
    assert api_v2._iso_quote_time(None) is None
    assert api_v2._iso_quote_time("   ") is None


# ── one price source for the request paths, bounded to 30 minutes ──────────────────────────────


def _patch_batch(monkeypatch, payload, calls=None):
    import lib.data_broker.market_quote as mq

    def fake(db_query, symbols, max_age_hours=12, *, skip_live=False, **kw):
        if calls is not None:
            calls.update(symbols=list(symbols), max_age_hours=max_age_hours, skip_live=skip_live)
        return payload

    monkeypatch.setattr(mq, "get_price_batch", fake)


def test_the_window_is_thirty_minutes_and_the_provider_waterfall_is_off_for_bulk(monkeypatch):
    calls: dict = {}
    _patch_batch(monkeypatch, {}, calls)

    api_v2._fresh_price_batch(["nvda"])

    assert calls["max_age_hours"] == 0.5
    assert calls["skip_live"] is True          # a bulk page never blocks on 250 provider calls
    assert calls["symbols"] == ["NVDA"]


def test_a_single_symbol_request_may_use_the_bounded_broker_fallback(monkeypatch):
    calls: dict = {}
    _patch_batch(monkeypatch, {}, calls)

    api_v2._fresh_price_batch(["NVDA"], live=True)

    assert calls["skip_live"] is False
    assert calls["max_age_hours"] == 0.5


def test_a_fresh_quote_keeps_its_identity_and_gets_an_iso_as_of(monkeypatch):
    _patch_batch(monkeypatch, {"NVDA": {"price": "182.5", "chg_pct": 1.25,
                                        "as_of": "2026-11-07 01:45:01 ET",
                                        "source": "finviz_quote_cache"}})

    out = api_v2._fresh_price_batch(["NVDA"])

    assert out["NVDA"]["price"] == pytest.approx(182.5)
    assert out["NVDA"]["source"] == "finviz_quote_cache"
    assert " ET" not in out["NVDA"]["as_of"]


def test_a_zero_or_missing_price_is_absent_never_served(monkeypatch):
    _patch_batch(monkeypatch, {"AAA": {"price": 0.0, "as_of": "2026-11-07T06:30:01Z"},
                               "BBB": {"price": None, "as_of": "2026-11-07T06:30:01Z"},
                               "CCC": {"price": "  ", "as_of": "2026-11-07T06:30:01Z"},
                               "DDD": {"price": 12.0, "as_of": "2026-11-07T06:30:01Z",
                                       "source": "market_quotes"}})

    out = api_v2._fresh_price_batch(["AAA", "BBB", "CCC", "DDD"])

    assert set(out) == {"DDD"}


def test_an_unreadable_quote_source_is_no_price_not_a_stale_one(monkeypatch):
    import lib.data_broker.market_quote as mq

    def boom(*a, **k):
        raise RuntimeError("quote store unavailable")

    monkeypatch.setattr(mq, "get_price_batch", boom)

    assert api_v2._fresh_price_batch(["NVDA"]) == {}


def test_no_symbols_means_no_query(monkeypatch):
    calls: dict = {}
    _patch_batch(monkeypatch, {}, calls)

    assert api_v2._fresh_price_batch([]) == {}
    assert calls == {}


# ── the canonical watch quote: a current price replaces the stored selector's pick ──────────────


def _patch_canonical(monkeypatch, stored, state="FRESH", session="REGULAR"):
    import lib.watch_canonical_quote as wcq

    monkeypatch.setattr(wcq, "batch_canonical_quotes", lambda syms: {s: dict(v) for s, v in stored.items() if s in syms})
    monkeypatch.setattr(wcq, "derive_freshness", lambda as_of, hold_last_close=True: (state, session))


def test_a_current_quote_replaces_the_stored_artifact_and_carries_its_own_identity(monkeypatch):
    _patch_canonical(monkeypatch, {"NVDA": {"symbol": "NVDA", "last": 100.0, "price_as_of": "2026-10-30T20:00:00Z",
                                            "freshness_state": "STALE"}})
    _patch_batch(monkeypatch, {"NVDA": {"price": 182.5, "chg_pct": 1.25, "as_of": "2026-11-07T06:30:01+00:00",
                                        "source": "finviz_quote_cache"}})

    arts = api_v2._canonical_quotes_fresh(["NVDA"])

    q = arts["NVDA"]
    assert q["last"] == pytest.approx(182.5)
    assert q["price_source"] == "finviz_quote_cache"
    assert q["quote_id"] == "finviz_quote_cache:2026-11-07T06:30:01+00:00"
    assert q["freshness_state"] == "FRESH"
    assert q["market_state"] == "OK"


def test_a_quote_the_freshness_helper_cannot_place_never_wins(monkeypatch):
    _patch_canonical(monkeypatch, {"NVDA": {"symbol": "NVDA", "last": 100.0, "freshness_state": "STALE"}},
                     state="DATA_UNAVAILABLE")
    _patch_batch(monkeypatch, {"NVDA": {"price": 182.5, "as_of": "2026-11-07T06:30:01+00:00",
                                        "source": "finviz_quote_cache"}})

    arts = api_v2._canonical_quotes_fresh(["NVDA"])

    assert arts["NVDA"]["last"] == pytest.approx(100.0)          # the stored record, unaltered
    assert arts["NVDA"]["freshness_state"] == "STALE"


def test_a_symbol_with_no_current_quote_keeps_the_stored_artifact_flagged_by_its_own_state(monkeypatch):
    _patch_canonical(monkeypatch, {"NVDA": {"symbol": "NVDA", "last": 100.0, "freshness_state": "STALE"}})
    _patch_batch(monkeypatch, {})

    arts = api_v2._canonical_quotes_fresh(["NVDA"])

    assert arts["NVDA"]["freshness_state"] == "STALE"


# ── the zero-market-value broker row is labelled with the broker, not "technical_snapshot" ─────


def test_a_zero_market_value_cusip_row_is_labelled_with_its_broker():
    """Schwab reports broker_market_value 0.0 for a delisted CUSIP; the technicals never produced a price
    either, so "technical_snapshot" invented a source (three rows: 543354104, 628518102, 12507E201)."""
    px, source, _as_of = api_v2._holding_price_fallback(
        {"symbol": "543354104", "account": "schwab_taxable", "broker_market_value": 0.0}, {}, {})

    assert px == 0.0
    assert source == "schwab: no market value"


def test_a_delisted_flag_is_enough_without_a_value():
    _px, source, _ = api_v2._holding_price_fallback(
        {"symbol": "628518102", "broker": "schwab", "delisted": True}, {}, {})

    assert source == "schwab: no market value"


def test_a_real_technical_price_is_still_labelled_technical_snapshot():
    px, source, as_of = api_v2._holding_price_fallback(
        {"symbol": "NVDA", "broker_market_value": 1234.0},
        {"price": 182.5, "as_of": "2026-11-06T20:00:00Z"}, {})

    assert px == pytest.approx(182.5)
    assert source == "technical_snapshot"
    assert as_of == "2026-11-06T20:00:00Z"


# ── review fixes (independent review of the 30-min fold, 2026-11-07) ──────────────────────────────


def test_a_stored_artifact_without_a_current_quote_is_never_shown_as_current(monkeypatch):
    """derive_freshness(hold_last_close=True) kept a 90-min-old row CURRENT; the operator rule says no
    price ≤30 min means not current."""
    _patch_canonical(monkeypatch, {"NVDA": {"symbol": "NVDA", "last": 100.0, "price_source": "market_quotes",
                                            "freshness_state": "CURRENT", "market_state": "OK"}})
    _patch_batch(monkeypatch, {})

    q = api_v2._canonical_quotes_fresh(["NVDA"])["NVDA"]

    assert q["last"] == pytest.approx(100.0)
    assert q["freshness_state"] == "STALE"
    assert q["market_state"] == "STALE"


def test_an_enrichment_or_yfinance_stored_price_is_not_shown(monkeypatch):
    _patch_canonical(monkeypatch, {
        "AAA": {"symbol": "AAA", "last": 10.0, "price_source": "enrichment", "day_change_pct": 2.0,
                "freshness_state": "CURRENT"},
        "BBB": {"symbol": "BBB", "last": 20.0, "price_source": "market_quotes:yfinance",
                "freshness_state": "AFTER_HOURS_CURRENT"}})
    _patch_batch(monkeypatch, {})

    arts = api_v2._canonical_quotes_fresh(["AAA", "BBB"])

    assert arts["AAA"]["last"] is None and arts["AAA"]["day_change_pct"] is None
    assert arts["BBB"]["last"] is None
    assert {arts["AAA"]["freshness_state"], arts["BBB"]["freshness_state"]} == {"STALE"}


def test_an_unplaceable_current_quote_leaves_the_stored_artifact_stale_not_current(monkeypatch):
    _patch_canonical(monkeypatch, {"NVDA": {"symbol": "NVDA", "last": 100.0, "price_source": "market_quotes",
                                            "freshness_state": "CURRENT"}}, state="DATA_UNAVAILABLE")
    _patch_batch(monkeypatch, {"NVDA": {"price": 182.5, "as_of": "junk", "source": "finviz_quote_cache"}})

    assert api_v2._canonical_quotes_fresh(["NVDA"])["NVDA"]["freshness_state"] == "STALE"


def test_nan_and_infinite_prices_are_absent(monkeypatch):
    _patch_batch(monkeypatch, {"AAA": {"price": float("nan"), "as_of": "2026-11-07T06:30:01Z"},
                               "BBB": {"price": "inf", "as_of": "2026-11-07T06:30:01Z"},
                               "CCC": {"price": 5.0, "as_of": "2026-11-07T06:30:01Z", "source": "market_quotes"}})

    assert set(api_v2._fresh_price_batch(["AAA", "BBB", "CCC"])) == {"CCC"}


def test_a_finviz_price_does_not_borrow_another_rows_day_change(monkeypatch):
    _patch_batch(monkeypatch, {
        "AAA": {"price": 10.0, "chg_pct": 3.0, "as_of": "2026-11-07T06:30:01Z", "source": "finviz_quote_cache"},
        "BBB": {"price": 20.0, "chg_pct": 1.5, "as_of": "2026-11-07T06:30:01Z", "source": "market_quotes:schwab"}})

    out = api_v2._fresh_price_batch(["AAA", "BBB"])

    assert out["AAA"]["chg_pct"] is None
    assert out["BBB"]["chg_pct"] == pytest.approx(1.5)


def test_no_price_from_any_source_is_labelled_none_not_technical_snapshot():
    px, source, as_of = api_v2._holding_price_fallback({"symbol": "ZZZ", "broker_market_value": 50.0}, {}, {})

    assert px == 0.0
    assert source == "none"
    assert as_of == ""


def test_holdings_and_rotation_read_prices_with_source_and_as_of():
    """Source guards: portfolio_holdings prices Finviz through the filtered shared reader, and both rotation
    price maps carry the price's own source and as_of."""
    src = Path(api_v2.__file__).read_text(encoding="utf-8")

    assert '_pp_mod.finviz_cache(STATE_DIR / "finviz_quote_cache.json")' in src
    assert src.count('"source": _q.get("source"),') == 2
    assert src.count('"as_of": _q.get("as_of"),') >= 2
