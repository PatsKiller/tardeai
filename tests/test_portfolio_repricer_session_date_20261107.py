"""LQ-20261107-493: portfolio_repricer dates ticker_prices by the session the close belongs to.

The repricer runs every 15 minutes, all day, every day. The old writer stamped ``CURRENT_DATE``:

* the 00:15 ET run on Saturday 2026-11-07 created a ``2026-11-07`` row (XLB, XLI, V and 20 other held
  symbols) holding Friday's close: a session that never existed;
* from 00:00 until the bell on a trading day, the day's row held the previous session's close.

LQ-20261107-83 (re-landed here) resolves the session from the clock. This file pins the write
itself: the ``price_date`` and the conflict rule that reach ``write_ticker_prices``. Only the evening
after a session's own close may overwrite that session's row; a pre-market, weekend or holiday run
fills a missing row and never replaces a completed close with a mark observed later.

Synthetic holdings and quotes only. No database: psycopg2 and the writer are faked.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_repricer  # noqa: E402

ET = ZoneInfo("America/New_York")


def _run(monkeypatch, now):
    """Run ``_sync_ticker_prices`` at ``now`` and return the captured writer calls."""
    calls = []

    class _Cur:
        pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            return None

        def close(self):
            return None

    fake_pg = types.SimpleNamespace(connect=lambda **_k: _Conn())
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    monkeypatch.setattr(portfolio_repricer, "_load_env", lambda _root: None)
    monkeypatch.setattr(portfolio_repricer, "_latest_quote_prices",
                        lambda _cur, syms: {s: 100.0 for s in syms if s})

    def _write(_cur, rows, **kw):
        calls.append({"rows": list(rows), **kw})
        return types.SimpleNamespace(rows_accepted=len(rows), rows_rejected=[])

    monkeypatch.setattr(portfolio_repricer, "write_ticker_prices", _write)
    portfolio = {"holdings": [
        {"symbol": "AAA", "shares": 2, "market_value": 200.0, "price": 100.0},
        {"symbol": "BBB", "shares": 1, "canonical_mark": 100.5, "price": 100.5},
        {"symbol": "CASH", "is_cash": True, "market_value": 5.0},
    ]}
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    # Freeze the module clock rather than pass ``now``, so the same test runs against a writer
    # that never took a clock argument (fail-on-old measures behaviour, not a signature).
    monkeypatch.setattr(portfolio_repricer, "datetime", _Frozen)
    portfolio_repricer._sync_ticker_prices(portfolio, root=ROOT)
    return calls


def _dates(call):
    """The price_date a write stamps: explicit per row, else CURRENT_DATE (the pre-LQ-83 shape)."""
    if call.get("current_date"):
        return {"CURRENT_DATE"}
    return {r.get("price_date") or "CURRENT_DATE" for r in call["rows"]}


@pytest.mark.parametrize("now,session", [
    (datetime(2026, 11, 7, 0, 15, tzinfo=ET), "2026-11-06"),   # Saturday 00:15: Friday's close
    (datetime(2026, 11, 8, 13, 0, tzinfo=ET), "2026-11-06"),   # Sunday: still Friday's close
    (datetime(2026, 11, 6, 0, 0, tzinfo=ET), "2026-11-05"),    # Friday 00:00, before the bell
    (datetime(2026, 11, 9, 7, 30, tzinfo=ET), "2026-11-06"),   # Monday pre-market: Friday
])
def test_an_earlier_session_is_filled_never_overwritten(monkeypatch, now, session):
    calls = _run(monkeypatch, now)
    assert len(calls) == 1
    dates = _dates(calls[0])
    assert dates == {session}, f"{now}: rows dated {dates}, expected the session {session}"
    assert calls[0]["on_conflict"] == "nothing", (
        "a run after the session's own evening must not replace that session's close")


def test_the_evening_of_the_session_overwrites_its_own_row(monkeypatch):
    calls = _run(monkeypatch, datetime(2026, 11, 6, 16, 10, tzinfo=ET))
    assert len(calls) == 1
    assert _dates(calls[0]) == {"2026-11-06"}
    assert calls[0]["on_conflict"] == "overwrite"
    assert calls[0]["source"] == "portfolio_repricer"
    assert sorted(r["symbol"] for r in calls[0]["rows"]) == ["AAA", "BBB"]


def test_the_open_session_writes_nothing(monkeypatch):
    assert _run(monkeypatch, datetime(2026, 11, 6, 12, 0, tzinfo=ET)) == []


def test_no_weekend_or_holiday_date_is_ever_written(monkeypatch):
    """Every 15-minute tick of a long weekend lands on a trading day (Thanksgiving 2026-11-26)."""
    from datetime import timedelta

    t = datetime(2026, 11, 25, 16, 0, tzinfo=ET)
    seen = set()
    while t < datetime(2026, 11, 30, 10, 0, tzinfo=ET):
        for c in _run(monkeypatch, t):
            seen |= _dates(c)
        t += timedelta(minutes=15)
    assert seen == {"2026-11-25", "2026-11-27"}, seen
