"""LQ-20261107-455: no yfinance price reaches ticker_prices or the Market Risk Engine (operator price rule 2026-11-07).

Synthetic rows and stub fetchers only: no network, no DB, no broker. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import ast
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eod_consolidated_close_sync as eod  # noqa: E402
from scripts.lib import redeploy_price_history as rph  # noqa: E402
from scripts.lib.market_risk import reader as rd  # noqa: E402

ET = ZoneInfo("America/New_York")


def _et(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ── eod_consolidated_close_sync ──────────────────────────────────────────────

def test_eod_sync_writes_alpaca_and_never_names_yfinance_as_its_source():
    assert eod.SOURCE == "alpaca_eod"
    assert "yfinance" not in eod.SOURCE
    assert set(eod.FORBIDDEN_SOURCES) == {"yfinance", "yfinance_eod"}
    assert set(eod.FORBIDDEN_SOURCES) <= set(eod.REPLACEABLE_SOURCES)


def test_a_yfinance_row_is_replaced_even_when_within_tolerance():
    stored = [("AAA", "yfinance_eod", 10.00), ("BBB", "yfinance", 20.00), ("CCC", "market_quotes", 30.00)]
    ref = {"AAA": 10.001, "BBB": 20.0, "CCC": 30.01}  # all within the 1% tolerance
    plan = eod.plan_replacements(stored, ref)
    assert sorted(r["symbol"] for r in plan["replace"]) == ["AAA", "BBB"]
    assert plan["unchanged"] == 1  # the market_quotes row keeps the old tolerance rule
    assert {r["stored_source"] for r in plan["replace"]} == {"yfinance_eod", "yfinance"}


def test_a_yfinance_row_beyond_the_hold_back_is_reported_not_written():
    plan = eod.plan_replacements([("MOGU", "yfinance_eod", 1.0)], {"MOGU": 3.0})
    assert plan["replace"] == [] and [r["symbol"] for r in plan["held_back"]] == ["MOGU"]


def test_a_yfinance_row_without_an_alpaca_bar_is_no_reference_not_a_fallback():
    plan = eod.plan_replacements([("ZZZ", "yfinance_eod", 5.0)], {"ZZZ": None})
    assert plan == {"replace": [], "held_back": [], "unchanged": 0, "no_reference": 1}


def test_alpaca_eod_rows_are_never_rewritten():
    plan = eod.plan_replacements([("AAA", "alpaca_eod", 10.0)], {"AAA": 12.0})
    assert plan == {"replace": [], "held_back": [], "unchanged": 0, "no_reference": 0}


def test_alpaca_closes_picks_the_session_bar_by_its_et_date():
    calls = []

    def fetch(sym, days):
        calls.append((sym, days))
        if sym == "NONE":
            return []
        return [
            {"symbol": sym, "bar_time": _et(2026, 11, 5), "close": 9.0},
            {"symbol": sym, "bar_time": _et(2026, 11, 6), "close": 10.5},
        ]

    out = eod._alpaca_closes(["AAA", "NONE"], date(2026, 11, 6), fetch=fetch, today=date(2026, 11, 9))
    assert out == {"AAA": 10.5, "NONE": None}
    assert all(days >= 5 for _, days in calls) and calls[0][1] == 8  # 3 days back + 5


def test_alpaca_closes_a_missing_session_is_none():
    out = eod._alpaca_closes(["AAA"], date(2026, 11, 6), fetch=lambda s, d: [{"bar_time": _et(2026, 11, 5), "close": 1.0}],
                             today=date(2026, 11, 6))
    assert out == {"AAA": None}


# ── redeploy_price_history ───────────────────────────────────────────────────

def test_redeploy_backfill_closes_come_from_alpaca_bars():
    assert rph.PRICE_SOURCE == "alpaca"
    seen = []

    def fetch(sym, days):
        seen.append(days)
        return [{"bar_time": _et(2026, 11, 5), "close": 4.0}, {"bar_time": _et(2026, 11, 6), "close": 0},
                {"bar_time": None, "close": 5.0}, {"bar_time": _et(2026, 11, 6), "close": "bad"}]

    rows = rph._alpaca_close_rows("AAA", "5y", fetch=fetch)
    assert rows == [{"symbol": "AAA", "price_date": date(2026, 11, 5), "close_price": 4.0}]
    assert seen == [1827]
    assert rph._alpaca_close_rows("AAA", "5y", fetch=lambda s, d: []) == []


def test_redeploy_backfill_writes_no_yfinance_price():
    src = (ROOT / "scripts" / "lib" / "redeploy_price_history.py").read_text(encoding="utf-8")
    assert 'source="yfinance"' not in src and ".history(" not in src


# ── Market Risk Engine reader ────────────────────────────────────────────────

def test_reader_accepts_only_alpaca_close_sources():
    assert set(rd.TICKER_PRICE_CLOSE_SOURCES) == {"alpaca_eod", "alpaca"}
    assert rd.OHLCV_DAILY_SOURCES == ("alpaca",)
    for srcs in (rd.TICKER_PRICE_CLOSE_SOURCES, rd.OHLCV_DAILY_SOURCES):
        assert not any("yfinance" in s for s in srcs)


class _Cur:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, [], []

    def execute(self, sql, params=None):
        self.conn.log.append((sql, params))
        for key, (cols, rows) in self.conn.routes.items():
            if key in sql:
                self.description = [(c,) for c in cols]
                self._rows = [tuple(r.get(c) for c in cols) for r in rows]  # every row: the SQL filter is ignored
                return
        self.description, self._rows = [], []

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _Conn:
    def __init__(self, routes):
        self.routes, self.log = routes, []

    def set_session(self, **k):
        pass

    def cursor(self, *a, **k):
        return _Cur(self)

    def close(self):
        pass

    def rollback(self):
        pass

    def commit(self):
        pass


BCOLS = ["symbol", "bar_time", "open", "high", "low", "close", "volume", "source", "created_at"]
TPCOLS = ["symbol", "price_date", "close_price", "source", "created_at"]


def test_reader_ignores_a_yfinance_bar_and_close_even_when_the_sql_returns_them():
    end = _et(2031, 3, 9, 18)
    bars = [
        {"symbol": "XLC", "bar_time": _et(2031, 3, 5), "open": 1, "high": 2, "low": 1, "close": 777.0, "volume": 1,
         "source": "yfinance", "created_at": None},
        {"symbol": "XLC", "bar_time": _et(2031, 3, 6), "open": 1, "high": 2, "low": 1, "close": 106.0, "volume": 1,
         "source": "alpaca", "created_at": None},
    ]
    tp = [
        {"symbol": "XLC", "price_date": date(2031, 3, 3), "close_price": 555.0, "source": "yfinance_eod",
         "created_at": _et(2031, 3, 3, 17, 15)},
        {"symbol": "XLC", "price_date": date(2031, 3, 4), "close_price": 444.0, "source": "yfinance",
         "created_at": _et(2031, 3, 4, 17)},
        {"symbol": "XLC", "price_date": date(2031, 3, 9), "close_price": 109.0, "source": "alpaca_eod",
         "created_at": _et(2031, 3, 9, 17, 15)},
    ]
    conn = _Conn({"FROM market_ohlcv_bars": (BCOLS, bars), "FROM ticker_prices": (TPCOLS, tp)})
    out = rd.PgReader(lambda: conn).daily_bars(["XLC"], sessions=10, end=end)
    assert [(b["date"], b["close"], b["source"]) for b in out] == [
        ("2031-03-06", 106.0, "market_ohlcv_bars:alpaca"),
        ("2031-03-09", 109.0, "ticker_prices:alpaca_eod"),
    ]
    bar_sql, bar_params = next((s, p) for s, p in conn.log if "FROM market_ohlcv_bars" in s and "high" in s)
    assert "source = ANY(%s)" in bar_sql and list(rd.OHLCV_DAILY_SOURCES) in bar_params


def test_session_opens_ignore_a_yfinance_open():
    rows = [
        {"symbol": "SPY", "bar_time": _et(2031, 3, 5), "open": 500.0, "source": "yfinance", "created_at": None},
        {"symbol": "SPY", "bar_time": _et(2031, 3, 6), "open": 501.0, "source": "alpaca", "created_at": None},
    ]
    conn = _Conn({"FROM market_ohlcv_bars": (["symbol", "bar_time", "open", "source", "created_at"], rows)})
    out = rd.PgReader(lambda: conn).session_opens(["SPY"], sessions=10, end=_et(2031, 3, 9, 18))
    assert [(r["date"], r["open"]) for r in out] == [("2031-03-06", 501.0)]
    sql, params = conn.log[-1]
    assert "source = ANY(%s)" in sql and list(rd.OHLCV_DAILY_SOURCES) in params


# ── no yfinance import or price fallback in the touched writers ─────────────

TOUCHED = [
    "scripts/eod_consolidated_close_sync.py",
    "scripts/lib/market_risk/reader.py",
    "scripts/proposal_enrichment_loop.py",
    "scripts/backfill_ticker_prices.py",
]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def test_touched_price_writers_import_no_yfinance():
    for rel in TOUCHED:
        imps = _imports(ROOT / rel)
        assert "yfinance" not in imps, rel
        assert "price_db_sync.backfill_yfinance_history" not in imps, rel


def test_enrichment_live_price_has_no_yfinance_fallback(monkeypatch):
    import types

    import proposal_enrichment_loop as pel

    stub = types.ModuleType("market_quote_provider")
    stub.QUOTE_ONLY_MAX_AGE_SECONDS = 60
    stub.get_best_quote = lambda symbol, max_age_seconds=None: {"last_price": None}
    monkeypatch.setitem(sys.modules, "market_quote_provider", stub)
    boom = types.ModuleType("yfinance")
    called = []

    class _Ticker:  # would answer 99.0, so a fallback cannot hide behind the caller's except
        def __init__(self, sym):
            called.append(sym)
            self.fast_info = {"lastPrice": 99.0}

    boom.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", boom)
    assert pel.get_live_price("AAA") == (None, "none")
    assert called == []
    stub.get_best_quote = lambda symbol, max_age_seconds=None: {"last_price": 12.5, "provider": "alpaca"}
    assert pel.get_live_price("AAA") == (12.5, "alpaca")
