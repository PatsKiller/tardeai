"""PgReader (DSN-20261031-market-risk-engine P1): as-of correctness, read-only session, no portfolio columns,
quote-derived closes, latest-snapshot regime read, FRED publication lag, macro-calendar fallback. No DB, no network."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.market_risk import reader as rd

ET = ZoneInfo("America/New_York")


def et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    def execute(self, sql, params=None):
        self.conn.log.append((sql, params))
        for needle, (cols, rows) in self.conn.routes.items():
            if needle in sql:
                self.description = [(c,) for c in cols]
                self._rows = (
                    [tuple(r[c] for c in cols) for r in rows(params) if True]
                    if callable(rows)
                    else [tuple(r[c] for c in cols) for r in rows]
                )
                return
        self.description, self._rows = [], []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, routes):
        self.routes, self.log, self.closed, self.readonly = routes, [], False, None

    def set_session(self, readonly=False):  # psycopg2 API: applies before the first transaction begins
        assert not self.log, "set_session after a statement"
        self.readonly = readonly

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def make(routes):
    conn = FakeConn(routes)
    return rd.PgReader(lambda: conn), conn


QCOLS = ["symbol", "price", "prev_close", "fetched_at"]

@pytest.mark.parametrize("hour,minute,second,microsecond,eligible", [
    (9, 29, 59, 999999, False), (9, 30, 0, 0, True), (15, 59, 59, 0, True),
    (16, 0, 0, 0, True), (16, 0, 59, 999999, True), (16, 1, 0, 0, False),
])
def test_current_regular_quote_keeps_the_full_session_after_close(hour, minute, second, microsecond, eligible):
    stamp = et(2026, 11, 2, hour, minute).replace(second=second, microsecond=microsecond)
    row = {"symbol": "ZZQ", "source": "alpaca", "price": Decimal("12.34"), "fetched_at": stamp}
    r, conn = make({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    quote = r.regular_session_quotes(["ZZQ"], end=et(2026, 11, 2, 20, 15))["ZZQ"]
    assert quote["status"] == ("available" if eligible else "unavailable")
    assert quote["price"] == (12.34 if eligible else None)
    assert quote["session_date"] == quote["expected_session_date"] == "2026-11-02"
    assert quote["source"] == "market_quotes:alpaca" and quote["session"] == "regular"
    assert conn.readonly is True and len(conn.log) == 1
    if eligible:
        assert quote["as_of"].endswith("Z")
    sql, params = conn.log[0]
    assert "fetched_at <= %s" in sql and params[0] == "alpaca"


def test_current_regular_quote_selects_monday_not_friday_premarket_or_later_prints():
    rows = [
        {"symbol": "ZZQ", "source": "alpaca", "price": 9.0, "fetched_at": et(2026, 10, 30, 16)},
        {"symbol": "ZZQ", "source": "alpaca", "price": 9.0, "fetched_at": et(2026, 11, 2, 7)},
        {"symbol": "ZZQ", "source": "alpaca", "price": 12.0, "fetched_at": et(2026, 11, 2, 16)},
        {"symbol": "ZZQ", "source": "alpaca", "price": 13.0, "fetched_at": et(2026, 11, 2, 17)},
    ]
    r, _ = make({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], list(reversed(rows)))})
    out = r.regular_session_quotes(["ZZQ", "ZZMISSING"], end=et(2026, 11, 2, 20))
    assert out["ZZQ"]["price"] == 12.0 and out["ZZQ"]["as_of"] == "2026-11-02T21:00:00Z"
    assert out["ZZMISSING"]["status"] == "unavailable" and out["ZZMISSING"]["price"] is None


@pytest.mark.parametrize("day,utc_hour", [(datetime(2026, 11, 2).date(), 14), (datetime(2031, 3, 10).date(), 13)])
def test_current_regular_quote_normalizes_dst_and_utc(day, utc_hour):
    stamp = datetime(day.year, day.month, day.day, utc_hour, 30, tzinfo=timezone.utc)
    row = {"symbol": "ZZQ", "source": "alpaca", "price": 12.0, "fetched_at": stamp}
    r, _ = make({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    local_end = datetime(day.year, day.month, day.day, 20, 15, tzinfo=ET)
    assert r.regular_session_quotes(["ZZQ"], end=local_end)["ZZQ"] == r.regular_session_quotes(["ZZQ"], end=local_end.astimezone(timezone.utc))["ZZQ"]
    assert r.regular_session_quotes(["ZZQ"], end=local_end)["ZZQ"]["status"] == "available"


def test_current_regular_quote_future_naive_invalid_and_early_close_fail_closed():
    day = (2026, 11, 27)
    rows = [
        {"symbol": "ZZQ", "source": "alpaca", "price": 12.0, "fetched_at": et(*day, 13).replace(second=59, microsecond=999999)},
        {"symbol": "ZZQ", "source": "alpaca", "price": 99.0, "fetched_at": et(*day, 13, 1)},
        {"symbol": "ZZQ", "source": "alpaca", "price": float("inf"), "fetched_at": et(*day, 12)},
        {"symbol": "ZZQ", "source": "finviz", "price": 99.0, "fetched_at": et(*day, 12)},
        {"symbol": "ZZQ", "source": "alpaca", "price": 99.0, "fetched_at": datetime(*day, 12)},
    ]
    r, _ = make({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], rows)})
    assert r.regular_session_quotes(["ZZQ"], end=et(*day, 18))["ZZQ"]["price"] == 12.0
    assert r.regular_session_quotes(["ZZQ"], end=et(*day, 10))["ZZQ"]["status"] == "unavailable"
    with pytest.raises(ValueError):
        r.regular_session_quotes(["ZZQ"], end=datetime(*day, 18))



@pytest.mark.parametrize("day,hour", [(datetime(2026, 11, 2).date(), 16), (datetime(2026, 11, 27).date(), 13)])
def test_fractional_display_quote_preserves_original_stage_and_vix_cutoffs(day, hour):
    """Main's exact-second close stays stage evidence; display alone admits the fractional print."""
    from datetime import time
    from scripts.lib.market_risk import reentry_stages

    assert rd.REGULAR_CLOSE_CUTOFF_ET == time(16, 0, 59)
    assert rd.EARLY_CLOSE_ET == time(13, 0, 59)
    exact = datetime.combine(day, time(hour, 0, 59), ET)
    fraction = exact.replace(microsecond=500000)
    rows = [
        {"symbol": "ZZQ", "source": "alpaca", "price": 10.0, "prev_close": 11.0, "fetched_at": exact},
        {"symbol": "ZZQ", "source": "alpaca", "price": 99.0, "prev_close": 11.0, "fetched_at": fraction},
    ]
    r, conn = make({"FROM market_quotes WHERE source": (["symbol", "source", "price", "prev_close", "fetched_at"], rows)})
    end = datetime.combine(day, time(20), ET)
    closes = r._quote_closes(["ZZQ"], start=datetime.combine(day, time(0), ET), end=end)
    assert len(closes) == 1 and closes[0]["close"] == 10.0
    assert datetime.fromisoformat(closes[0]["as_of"]) == exact
    assert closes[0]["provisional"] is True
    assert r.regular_session_quotes(["ZZQ"], end=end)["ZZQ"]["price"] == 99.0
    confirmed = [{"date": "2026-10-29", "close": 12.0}, {"date": "2026-10-30", "close": 11.0}]
    args = dict(symbol="ZZQ", exit_date="2026-10-29", exit_price=13.0, group_ratio=[],
                hedging_series=[], market_tier="GREEN", policy={})
    before = reentry_stages.evaluate(bars=confirmed, **args)
    after = reentry_stages.evaluate(bars=confirmed + closes, **args)
    assert after == before and after["last_close"] == 11.0 and after["last_date"] == "2026-10-30"
    r._vix_closes(start=datetime.combine(day, time(0), ET), end=end)
    snapshot = next(params for sql, params in conn.log if "FROM market_regime_indicators" in sql)
    assert snapshot[-1] == time(16, 0, 59), "VIX snapshot predicate retains main's exact-second cutoff"


def test_session_is_read_only_before_any_query():
    r, conn = make({})
    r.quotes(["SPY"], start=et(2026, 10, 29, 4), end=et(2026, 10, 29, 20))
    # read-only from the first transaction (data-feed review of #2383): set_session, not a later-only SET
    assert conn.readonly is True and not any("default_transaction_read_only" in q for q, _ in conn.log)


def test_naive_instant_refused():
    r, _ = make({})
    with pytest.raises(ValueError):
        r.quotes(["SPY"], start=datetime(2026, 10, 29), end=datetime(2026, 10, 30))


def test_quote_closes_use_next_session_prev_close_and_flag_the_newest_provisional():
    quotes = [
        {
            "symbol": "QQQ",
            "price": Decimal("725.0"),
            "prev_close": Decimal("720.0"),
            "fetched_at": et(2026, 10, 28, 9, 45),
        },
        {
            "symbol": "QQQ",
            "price": Decimal("725.59"),
            "prev_close": Decimal("720.0"),
            "fetched_at": et(2026, 10, 28, 15, 58),
        },
        {
            "symbol": "QQQ",
            "price": Decimal("710.0"),
            "prev_close": Decimal("725.60"),
            "fetched_at": et(2026, 10, 29, 7, 15),
        },
        {
            "symbol": "QQQ",
            "price": Decimal("706.0"),
            "prev_close": Decimal("725.60"),
            "fetched_at": et(2026, 10, 29, 15, 59),
        },
        {
            "symbol": "QQQ",
            "price": Decimal("690.0"),
            "prev_close": Decimal("725.60"),
            "fetched_at": et(2026, 10, 29, 16, 45),
        },
    ]
    r, _ = make({"FROM market_ohlcv_bars": (["symbol"], []), "FROM market_quotes WHERE source": (QCOLS, quotes)})
    bars = r.daily_bars(["QQQ"], sessions=10, end=et(2026, 10, 29, 18, 15))
    assert [(b["date"], b["close"], b["provisional"]) for b in bars] == [
        ("2026-10-28", 725.60, False),  # from 10-29's first quote prev_close, not 10-28's last print
        ("2026-10-29", 706.0, True),  # last regular-hours quote; the 16:45 after-hours print is ignored
    ]


def test_bars_preferred_and_in_progress_session_excluded():
    bcols = ["symbol", "bar_time", "open", "high", "low", "close", "volume", "source", "created_at"]
    bars = [
        {
            "symbol": "SPY",
            "bar_time": et(2026, 10, 28, 0),
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": Decimal("680"),
            "volume": 1,
            "source": "yfinance",
            "created_at": et(2026, 10, 28, 17),
        },
        {
            "symbol": "SPY",
            "bar_time": et(2026, 10, 29, 0),
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": Decimal("670"),
            "volume": 1,
            "source": "yfinance",
            "created_at": et(2026, 10, 29, 9),
        },
    ]
    r, _ = make({"FROM market_ohlcv_bars": (bcols, bars), "FROM market_quotes WHERE source": (QCOLS, [])})
    out = r.daily_bars(["SPY"], sessions=5, end=et(2026, 10, 29, 12))
    assert [b["date"] for b in out] == ["2026-10-28"]
    assert out[0]["source"] == "market_ohlcv_bars:yfinance" and out[0]["close"] == 680.0


def test_regime_indicators_read_only_the_latest_snapshot_before_end():
    rcols = [
        "snapshot_id",
        "indicator_key",
        "indicator_group",
        "value",
        "value_text",
        "signal",
        "source_key",
        "payload",
        "created_at",
    ]
    r, conn = make(
        {
            "ORDER BY created_at DESC LIMIT 1": (["snapshot_id"], [{"snapshot_id": "SNAP_B"}]),
            "WHERE snapshot_id = %s": (
                rcols,
                [
                    {
                        "snapshot_id": "SNAP_B",
                        "indicator_key": "vix_close",
                        "indicator_group": "volatility",
                        "value": Decimal("21.3"),
                        "value_text": None,
                        "signal": "high",
                        "source_key": "yahoo_finance",
                        "payload": {},
                        "created_at": et(2026, 10, 30, 16, 5),
                    }
                ],
            ),
        }
    )
    rows = r.regime_indicators(end=et(2026, 10, 30, 16, 10))
    assert rows[0]["snapshot_id"] == "SNAP_B" and rows[0]["value"] == 21.3 and rows[0]["as_of"]
    sql, params = conn.log[-1]
    assert params[0] == "SNAP_B"


def test_fred_applies_publication_lag():
    r, conn = make({"FROM fred_economic_series": (["series_id"], [])})
    r.fred(["BAMLH0A0HYM2"], observations=20, end=et(2026, 10, 29, 18))
    sql, params = conn.log[-1]
    assert str(params[1]) == "2026-10-28"  # the 10-29 print is published on 10-30


def test_sector_states_never_select_portfolio_columns():
    r, conn = make({"FROM sector_momentum_state": (["etf"], [])})
    r.sector_states(end=et(2026, 10, 29, 18))
    sql = conn.log[-1][0]
    assert "book_" not in sql


def test_option_snapshots_filter_on_created_at():
    r, conn = make({"FROM option_chain_snapshots": (["as_of"], [])})
    r.option_snapshots(["QQQ"], sessions=20, end=et(2026, 10, 30, 10, 15))
    sql, params = conn.log[-1]
    assert "created_at <= %s" in sql and params[2] == et(2026, 10, 30, 10, 15)


def test_macro_calendar_falls_back_to_overrides_with_a_visible_note(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))  # no runtime calendar there
    r, _ = make({})
    ev = r.macro_calendar(start=et(2026, 10, 27, 0), end=et(2026, 10, 29, 0))
    assert any(e["event"] == "fomc_decision" and e["date"] == "2026-10-28" for e in ev)
    assert r.macro_calendar_note.startswith("runtime calendar unavailable")


def test_earnings_calendar_reports_both_next_and_last_dates():
    cols = [
        "symbol",
        "sector",
        "industry",
        "instrument_type",
        "next_earnings_date",
        "last_earnings_date",
        "earnings_updated_at",
    ]
    rows = [
        {
            "symbol": "AMZN",
            "sector": "Consumer",
            "industry": "x",
            "instrument_type": "stock",
            "next_earnings_date": datetime(2027, 2, 1).date(),
            "last_earnings_date": datetime(2026, 10, 29).date(),
            "earnings_updated_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
        }
    ]
    r, _ = make({"FROM symbol_profiles": (cols, rows)})
    ev = r.earnings_calendar(start=et(2026, 10, 27, 0), end=et(2026, 10, 31, 0))
    assert [(e["symbol"], e["kind"], e["date"]) for e in ev] == [("AMZN", "last", "2026-10-29")]


# Stored observation for the current Home card is separate from regular-session bar evidence.
def _observed_module(name, relative):
    # Fresh by-path loads prevent an earlier test's empty module stub from becoming the producer under test.
    import importlib.util
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _observed_reader(routes):
    module = _observed_module("test_observed_reentry_reader", "scripts/lib/market_risk/reader.py")
    conn = FakeConn(routes)
    return module.PgReader(lambda: conn), conn


def _observed_joiner():
    return _observed_module("test_observed_reentry_join", "scripts/lib/market_risk_book_join.py")


def test_observed_reentry_quote_uses_premarket_source_without_changing_regular_bar():
    stamp = datetime(2026, 11, 4, 14, 0, 4, tzinfo=timezone.utc)
    row = {"symbol": "ZZQ", "source": "alpaca", "price": Decimal("132.99"), "fetched_at": stamp}
    r, conn = _observed_reader({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    quote = r.current_session_quotes(["ZZQ"], end=et(2026, 11, 4, 9, 17))["ZZQ"]
    assert quote["schema"] == "ReentryObservedQuote@v1"
    assert quote["status"] == "available" and quote["price"] == 132.99
    assert quote["session"] == "premarket" and quote["session_date"] == "2026-11-04"
    assert quote["source"] == "market_quotes:alpaca" and quote["as_of"] == "2026-11-04T14:00:04Z"
    assert quote["evaluated_at"] == "2026-11-04T14:17:00Z"
    assert conn.readonly is True and len(conn.log) == 1


@pytest.mark.parametrize("overrides,status", [
    ({"fetched_at": datetime(2026, 11, 4, 14, 18, tzinfo=timezone.utc)}, "unavailable"),
    ({"fetched_at": datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)}, "stale"),
    ({"fetched_at": datetime(2026, 11, 4, 14, 0)}, "unavailable"),
    ({"source": "another-provider"}, "unavailable"),
    ({"price": float("inf")}, "unavailable"),
    ({"price": float("nan")}, "unavailable"),
    ({"price": True}, "unavailable"),
    ({"price": "132.99"}, "unavailable"),
    ({"price": -1}, "unavailable"),
])
def test_observed_reentry_quote_fails_closed(overrides, status):
    row = {"symbol": "ZZQ", "source": "alpaca", "price": 132.99,
           "fetched_at": datetime(2026, 11, 4, 14, 0, 4, tzinfo=timezone.utc), **overrides}
    r, _conn = _observed_reader({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    quote = r.current_session_quotes(["ZZQ"], end=et(2026, 11, 4, 9, 17))["ZZQ"]
    assert quote["status"] == status and quote["status"] != "available"


def test_reentry_api_quote_refresh_keeps_historical_stage_but_exposes_invalidation_price():
    refresh_reentry_quotes = _observed_joiner().refresh_reentry_quotes
    stage = {"verdict": "Confirmed", "last_close": 140.47, "last_date": "2026-11-03",
             "invalidation_level": 134.50, "sma20": 150.0}
    projection = {"state": "evaluated", "as_of": "2026-11-03T21:00:00Z", "reentry_watch": {
        "ZZQ": {"exit_price": 137.19, "stages": stage,
                "current_quote": {"status": "available", "price": 140.47}}, "_contract": "ignored"}}
    calls = []
    def quote_reader(symbols, *, end):
        calls.append((symbols, end))
        return {"ZZQ": {"schema": "ReentryObservedQuote@v1", "status": "available", "price": 132.99,
                        "session": "premarket", "session_date": "2026-11-04", "source": "market_quotes:alpaca",
                        "as_of": "2026-11-04T14:00:04Z", "evaluated_at": "2026-11-04T14:17:00Z"}}
    out = refresh_reentry_quotes(projection, now=et(2026, 11, 4, 9, 17), quote_reader=quote_reader)
    quote = out["reentry_watch"]["ZZQ"]["current_quote"]
    assert calls[0][0] == ["ZZQ"] and len(calls) == 1
    assert quote["price"] == 132.99 < stage["invalidation_level"]
    assert quote["pct_vs_exit"] == pytest.approx(-3.061447627)
    assert out["reentry_watch"]["ZZQ"]["stages"] == stage
    assert projection["reentry_watch"]["ZZQ"]["current_quote"]["price"] == 140.47
    assert out["quote_checked_at"] == "2026-11-04T14:17:00Z"


def test_reentry_api_refresh_failure_never_keeps_yesterdays_quote():
    refresh_reentry_quotes = _observed_joiner().refresh_reentry_quotes
    stage = {"verdict": "Confirmed", "last_close": 140.47, "invalidation_level": 134.50}
    old = {"state": "evaluated", "reentry_watch": {"ZZQ": {"stages": stage,
           "current_quote": {"status": "available", "price": 140.47}}}}
    def broken_reader(*_args, **_kwargs):
        raise OSError("synthetic read refused")
    out = refresh_reentry_quotes(old, now=et(2026, 11, 4, 9, 17), quote_reader=broken_reader)
    quote = out["reentry_watch"]["ZZQ"]["current_quote"]
    assert quote["status"] == "unavailable" and quote["price"] is None
    assert quote["reason"] == "CURRENT_QUOTE_READER_UNAVAILABLE"
    assert out["reentry_watch"]["ZZQ"]["stages"] == stage


def test_reentry_join_refreshes_quote_even_when_holdings_are_unreadable(monkeypatch):
    joiner = _observed_joiner()
    stage = {"verdict": "Confirmed", "last_close": 140.47, "invalidation_level": 134.50}
    projection = {"state": "stale", "as_of": "2026-11-03T21:00:00Z",
                  "reentry_watch": {"ZZQ": {"exit_price": 137.19, "stages": stage}}}
    row = {"symbol": "ZZQ", "source": "alpaca", "price": 132.99,
           "fetched_at": datetime(2026, 11, 4, 14, 0, 4, tzinfo=timezone.utc)}
    conn = FakeConn({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    monkeypatch.setattr(joiner, "_import", lambda _name: object())
    out = joiner.join(projection, now=et(2026, 11, 4, 9, 17), store={}, get_conn=lambda **_kwargs: conn)
    assert out["book_exposure_error"] == "holdings store unreadable"
    assert out["reentry_watch"]["ZZQ"]["current_quote"]["price"] == 132.99
    assert out["reentry_watch"]["ZZQ"]["stages"] == stage
    assert conn.closed is True and conn.readonly is True
    assert len(conn.log) == 1



def test_reentry_api_quote_close_failure_is_explicit_unknown():
    refresh_reentry_quotes = _observed_joiner().refresh_reentry_quotes
    class CloseFailure(FakeConn):
        def close(self):
            self.closed = True
            raise OSError("synthetic close failure")
    row = {"symbol": "ZZQ", "source": "alpaca", "price": 132.99,
           "fetched_at": datetime(2026, 11, 4, 14, 0, 4, tzinfo=timezone.utc)}
    conn = CloseFailure({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    old = {"state": "evaluated", "reentry_watch": {"ZZQ": {"exit_price": 137.19,
           "current_quote": {"status": "available", "price": 140.47}}}}
    out = refresh_reentry_quotes(old, now=et(2026, 11, 4, 9, 17), get_conn=lambda **_kwargs: conn)
    quote = out["reentry_watch"]["ZZQ"]["current_quote"]
    assert quote["status"] == "unavailable" and quote["price"] is None
    assert quote["reason"] == "CURRENT_QUOTE_READER_UNAVAILABLE"
    assert conn.closed is True



@pytest.mark.parametrize("hour,session", [(6, "premarket"), (10, "regular"), (18, "afterhours")])
def test_observed_reentry_quote_carries_each_sessions_own_timestamp(hour, session):
    row = {"symbol": "ZZQ", "source": "alpaca", "price": 12.5,
           "fetched_at": et(2026, 11, 4, hour)}
    r, _conn = _observed_reader({"FROM market_quotes WHERE source": (["symbol", "source", "price", "fetched_at"], [row])})
    local = r.current_session_quotes(["ZZQ"], end=et(2026, 11, 4, hour, 17))["ZZQ"]
    utc = r.current_session_quotes(["ZZQ"], end=et(2026, 11, 4, hour, 17).astimezone(timezone.utc))["ZZQ"]
    assert local == utc and local["status"] == "available" and local["session"] == session
    assert local["as_of"] == row["fetched_at"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
