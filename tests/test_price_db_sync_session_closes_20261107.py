"""LQ-20261107-406: the session close the evening lanes read has to exist before they read it.

Measured on 2026-11-07 (read-only): ``ticker_prices`` held 1,101 bars for 2026-11-06 out of
5,577 quoted symbols, and **SPY had none** — the benchmark ``sector_momentum_engine`` dates
every sector against. It intersected each ETF's dates with SPY's, took 2026-11-05 as "today",
upserted 11-05 again, and the desk served a one-session-stale close with no error. The one
full-universe writer runs at 07:20 ET, before the session, so it can only ever write *yesterday*
(11-05: 5,493 bars, all off the morning print); every other caller is per-symbol.

These tests pin the fill that closes the gap: broker-read closes (``market_quotes``) only, the
session resolved as the newest weekday whose feed printed a close inside the configured window,
and a write that cannot displace a bar another lane already wrote for that session.

LQ-20261107-459 (same file, same writer): the close is the FIRST print at or after 16:00 inside a
configured window, not the last print of the date. A date whose only post-close prints are
after-hours refreshes has no close, and a symbol with no print inside the window is reported
(``no_close_print``) instead of having an after-hours price stored under its name.
"""

from __future__ import annotations

import inspect
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.writers import ticker_prices_writer as tp  # noqa: E402
from scripts import price_db_sync as pds  # noqa: E402

ET = __import__("zoneinfo").ZoneInfo("America/New_York")


def norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def at(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


class ScriptedCursor:
    """Returns one scripted result per execute(), in order; records every statement."""

    def __init__(self, results=None, rowcount: int = 0):
        self.results = list(results or [])
        self.calls: list[tuple[str, object]] = []
        self.rowcount = rowcount
        self._last = []
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append((norm(sql), params))
        self._last = self.results.pop(0) if self.results else []

    def fetchall(self):
        return list(self._last)

    def fetchone(self):
        return self._last[0] if self._last else None

    def close(self):
        self.closed = True

    @property
    def sqls(self):
        return [s for s, _ in self.calls]


class FakeConn:
    def __init__(self, cur: ScriptedCursor):
        self.cur = cur
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


def writes(cur: ScriptedCursor) -> list[str]:
    return [s for s in cur.sqls if "INSERT" in s.upper()]


# ── which date is a session close ────────────────────────────────────────────


def test_a_weekend_date_is_never_a_session():
    """2026-11-07 is a Saturday and has 48 quote rows; Friday 11-06 is the closed session."""
    cur = ScriptedCursor([[
        # session, last print, quotes, prints inside the close window, first of them, iso dow
        (date(2026, 11, 7), at(2026, 11, 7, 9, 14), 48, 0, None, 6),
        (date(2026, 11, 6), at(2026, 11, 6, 16, 45, 2), 5511, 13, at(2026, 11, 6, 16, 0, 4), 5),
    ]])
    d, why = pds.resolve_session_close_date(cur, ["SPY", "XLK"], today=date(2026, 11, 8))
    assert d == date(2026, 11, 6)
    assert "16:00:04" in why and "16:45" in why and "is a weekend" in why


def test_a_premarket_or_intraday_last_quote_is_not_a_close():
    """The defect in one line: a date whose last quote is at 11:39 has no close to write."""
    cur = ScriptedCursor([[
        (date(2026, 11, 6), at(2026, 11, 6, 11, 39), 41, 0, None, 5),
        (date(2026, 11, 5), at(2026, 11, 5, 16, 45, 2), 5500, 13, at(2026, 11, 5, 16, 0, 3), 4),
    ]])
    d, why = pds.resolve_session_close_date(cur, ["SPY"], today=date(2026, 11, 7))
    assert d == date(2026, 11, 5)
    assert "11:39" in why and "no close print" in why


def test_a_date_whose_only_post_close_prints_are_after_hours_has_no_close():
    """LQ-459: 16:45 is after the close, not the close. A date with prints but none in the
    window is skipped, so the after-hours refresh can never become a session close."""
    cur = ScriptedCursor([[
        (date(2026, 11, 6), at(2026, 11, 6, 16, 45, 2), 39, 0, None, 5),
        (date(2026, 11, 5), at(2026, 11, 5, 16, 45, 2), 5500, 13, at(2026, 11, 5, 16, 0, 3), 4),
    ]])
    d, why = pds.resolve_session_close_date(cur, ["SPY"], today=date(2026, 11, 7))
    assert d == date(2026, 11, 5)
    assert "2026-11-06 has no close print in 16:00-16:10 ET" in why


def test_the_newest_post_close_session_wins():
    cur = ScriptedCursor([[
        (date(2026, 11, 6), at(2026, 11, 6, 19, 59), 5511, 5511, at(2026, 11, 6, 16, 0, 4), 5),
        (date(2026, 11, 5), at(2026, 11, 5, 16, 45, 2), 5500, 5500, at(2026, 11, 5, 16, 0, 3), 4),
    ]])
    d, _ = pds.resolve_session_close_date(cur, ["SPY"], today=date(2026, 11, 7))
    assert d == date(2026, 11, 6)


def test_no_quoted_date_returns_none_with_a_reason():
    cur = ScriptedCursor([[]])
    d, why = pds.resolve_session_close_date(cur, ["SPY"], today=date(2026, 11, 7))
    assert d is None and why


# ── the plan is read-only and classifies every symbol ────────────────────────


def test_the_plan_writes_nothing_and_names_every_symbol_it_cannot_fill():
    session = date(2026, 11, 6)
    cur = ScriptedCursor([[
        # symbol, close print inside the window, when, last print of the day,
        # bar_close, bar_source, prior_close
        ("SPY", 735.40, at(2026, 11, 6, 16, 0, 4), at(2026, 11, 6, 16, 45, 2), None, None, 732.29),
        ("XLK", 164.79, at(2026, 11, 6, 16, 0, 4), at(2026, 11, 6, 16, 45, 2), None, None, 161.75),
        ("RSP", 216.025, at(2026, 11, 6, 16, 0, 8), at(2026, 11, 6, 16, 0, 8), 216.025,
         "market_quotes", 216.86),
        ("XLF", 1000.0, at(2026, 11, 6, 16, 0, 4), at(2026, 11, 6, 16, 0, 4), None, None, 57.53),
        ("XLU", None, None, at(2026, 11, 6, 16, 45, 2), None, None, 43.14),
    ]])
    plan = pds.plan_session_closes(cur, session, ["SPY", "XLK", "RSP", "XLF", "XLU", "XLB"])
    assert writes(cur) == []
    assert plan["would_write"] == ["SPY", "XLK"]
    assert plan["has_bar"] == ["RSP"]
    assert plan["outliers"] == ["XLF"]
    assert plan["no_close_print"] == ["XLU"]            # quoted that day, not inside the window
    assert plan["no_quote"] == ["XLB"]                  # not quoted at all
    by = {r["symbol"]: r for r in plan["rows"]}
    assert by["SPY"]["close"] == 735.40 and by["SPY"]["quoted_at"].startswith("2026-11-06")
    assert by["XLU"]["close"] is None and "no print inside 16:00-16:10 ET" in by["XLU"]["detail"]
    assert by["XLU"]["last_quote"].endswith("16:45:02")


# ── the fill: dry run writes nothing, apply fills only the missing bars ──────


def _plan_rows():
    return [
        ("SPY", 735.40, at(2026, 11, 6, 16, 0, 4), at(2026, 11, 6, 16, 45, 2), None, None, 732.29),
        ("XLK", 164.79, at(2026, 11, 6, 16, 0, 4), at(2026, 11, 6, 16, 45, 2), None, None, 161.75),
        ("RSP", 216.025, at(2026, 11, 6, 16, 0, 8), at(2026, 11, 6, 16, 0, 8), 216.025,
         "market_quotes", 216.86),
    ]


def test_a_dry_run_reports_the_plan_and_executes_no_write(monkeypatch):
    cur = ScriptedCursor([_plan_rows()])
    conn = FakeConn(cur)
    monkeypatch.setattr(pds, "_get_conn", lambda: conn)

    res = pds.sync_session_closes(["SPY", "XLK", "RSP"], session=date(2026, 11, 6), dry_run=True)

    assert res["ok"] is True and res["dry_run"] is True and res["written"] == 0
    assert res["would_write"] == ["SPY", "XLK"] and res["has_bar"] == ["RSP"]
    assert writes(cur) == []
    assert conn.committed == 0                              # a dry run commits nothing


def test_apply_is_narrowed_to_the_session_and_cannot_displace_an_existing_bar(monkeypatch):
    cur = ScriptedCursor([_plan_rows()], rowcount=2)
    conn = FakeConn(cur)
    monkeypatch.setattr(pds, "_get_conn", lambda: conn)

    res = pds.sync_session_closes(["SPY", "XLK", "RSP"], session=date(2026, 11, 6))

    assert res["ok"] is True and res["written"] == 2
    assert len(writes(cur)) == 1
    sql, params = cur.calls[-1]
    assert "fetched_at::date = %(session)s" in sql      # one session, not every day
    assert "DO NOTHING" in sql.upper()                  # never displaces a bar already written
    assert "DO UPDATE" not in sql.upper()
    # LQ-459: the write itself takes the FIRST print inside the window, not the last of the day
    assert "fetched_at ASC" in sql and "fetched_at DESC" not in sql
    assert "(fetched_at AT TIME ZONE 'America/New_York')::time >= %(close_time)s" in sql
    assert params["session"] == date(2026, 11, 6)
    assert (params["close_time"].hour, params["close_time"].minute) == (16, 0)
    assert (params["close_end"].hour, params["close_end"].minute) == (16, 10)
    assert params["syms"] == ["SPY", "XLK"]             # RSP already had its bar
    assert conn.committed == 1


def test_an_unresolvable_session_returns_not_ok_and_writes_nothing(monkeypatch):
    cur = ScriptedCursor([[]])                          # no quoted date at all
    conn = FakeConn(cur)
    monkeypatch.setattr(pds, "_get_conn", lambda: conn)

    res = pds.sync_session_closes(["SPY"])

    assert res["ok"] is False and res["written"] == 0
    assert writes(cur) == [] and conn.committed == 0


# ── the source and the default statement ────────────────────────────────────


def test_the_fill_reads_broker_quotes_only_never_yfinance():
    src = (inspect.getsource(pds.plan_session_closes)
           + inspect.getsource(pds.sync_session_closes)
           + inspect.getsource(pds.resolve_session_close_date))
    assert "import yfinance" not in src and "yf.Ticker" not in src
    assert "'market_quotes'" in tp._quotes_sync_sql("", "\n AND fetched_at::date = %(session)s")


def test_the_default_quotes_sync_statement_is_unchanged_by_the_new_bounds():
    """The 07:20 full sync must emit exactly the statement it emitted before (golden test)."""
    default = tp._quotes_sync_sql("AND UPPER(symbol) = ANY(%(syms)s)")
    explicit = tp._quotes_sync_sql("AND UPPER(symbol) = ANY(%(syms)s)", "",
                                   only_missing=False)
    assert norm(default) == norm(explicit)
    assert "%(session)s" not in default and "DO UPDATE SET" in default.upper()
    assert "DO NOTHING" in tp._quotes_sync_sql("", only_missing=True).upper()
