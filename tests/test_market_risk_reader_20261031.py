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
        self.routes, self.log, self.closed = routes, [], False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def make(routes):
    conn = FakeConn(routes)
    return rd.PgReader(lambda: conn), conn


QCOLS = ["symbol", "price", "prev_close", "fetched_at"]


def test_session_is_read_only_before_any_query():
    r, conn = make({})
    r.quotes(["SPY"], start=et(2026, 10, 29, 4), end=et(2026, 10, 29, 20))
    assert conn.log[0][0] == "SET default_transaction_read_only = on"


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
