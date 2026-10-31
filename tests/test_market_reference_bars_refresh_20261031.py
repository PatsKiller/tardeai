"""Daily bars for the Market Risk Engine's reference ETFs are refreshed on purpose, not as a side effect.

Before 2026-10-31 market_ohlcv_bars daily rows were written only when an on-demand technical lookup asked for a
symbol, so SPY stopped on 2026-10-09 and QQQ/SMH had none (builder H's audit, PR #2341). These tests pin the
fetch window arithmetic, that a dry run never writes, that --apply writes through the store function it is given,
and that a symbol the provider returns nothing for is named and fails the run. No network, no DB.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_reference_bars_refresh as mrb  # noqa: E402


class _Cur:
    def __init__(self, last):
        self.last = last

    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith("SELECT")  # the lane only reads through its own cursor

    def fetchall(self):
        return list(self.last.items())


class _Conn:
    def __init__(self, last):
        self.last = last

    def cursor(self):
        return _Cur(self.last)


def _bars(sym, n):
    return [
        {"symbol": sym, "timeframe": "daily", "bar_time": datetime(2026, 10, 1 + i, tzinfo=timezone.utc)}
        for i in range(n)
    ]


def test_fetch_window():
    today = date(2026, 10, 31)
    assert mrb.fetch_days(date(2026, 10, 9), today, None) == 25  # from the last stored bar
    assert mrb.fetch_days(date(2026, 10, 30), today, None) == mrb.INCREMENTAL_MIN_DAYS
    assert mrb.fetch_days(None, today, None) == mrb.fetch_days(date(2026, 10, 30), today, 400)  # never had bars
    assert mrb.fetch_days(None, today, 400) >= 400 * 365 / 252  # enough calendar days for 400 sessions


def test_dry_run_never_stores_and_apply_does(monkeypatch):
    monkeypatch.setattr(mrb, "reference_symbols", lambda: ["SPY", "QQQ"])
    stored = []

    def store(conn, bars):
        stored.extend(bars)
        return len(bars)

    fetch = lambda s, tf, days: _bars(s, 3)  # noqa: E731
    dry = mrb.run(
        apply=False, backfill_sessions=None, conn=_Conn({}), fetch=fetch, store=store, today=date(2026, 10, 31)
    )
    assert dry["mode"] == "dry_run" and dry["stored_bars"] == 0 and stored == []
    assert dry["fetched_bars"] == 6 and dry["empty"] == []
    live = mrb.run(
        apply=True, backfill_sessions=None, conn=_Conn({}), fetch=fetch, store=store, today=date(2026, 10, 31)
    )
    assert live["stored_bars"] == 6 and len(stored) == 6


def test_empty_symbol_is_named(monkeypatch):
    monkeypatch.setattr(mrb, "reference_symbols", lambda: ["SPY", "UUP"])
    out = mrb.run(
        apply=False,
        backfill_sessions=None,
        conn=_Conn({"SPY": date(2026, 10, 9)}),
        fetch=lambda s, tf, d: [] if s == "UUP" else _bars(s, 2),
        store=lambda c, b: 0,
        today=date(2026, 10, 31),
    )
    assert out["empty"] == ["UUP"]
    spy = next(r for r in out["rows"] if r["symbol"] == "SPY")
    assert spy["last_stored"] == "2026-10-09" and spy["requested_days"] == 25


def test_symbols_come_from_the_shared_config():
    syms = mrb.reference_symbols()
    for s in ("SPY", "QQQ", "SMH", "HYG", "UUP", "VIXY"):
        assert s in syms
