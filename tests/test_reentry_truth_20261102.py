"""The re-entry watch tells the truth (emergency, 2026-11-02).

Operator, in-session: "It's also not telling me the stuff I was stopped out of. Is it still flat? Is
it going down? Is it time to re-enter? ... Is this working?"

Two defects prove out here, both on today's shape:
- a 07:15 ET pre-market quote from the alpaca ``market_quotes`` snapshot became that day's "close"
  because the same-day rule had no 09:30 floor, shifting SMA10/20 and flipping verdicts;
- q uote-derived bars carry no open/high/low/volume, so Stage 1's green-candle and volume tests could
  never pass and were shown as "not met" rather than "not measured".

Hermetic: synthetic quotes and bars only (no real symbols, prices or names); no DB, no network.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.market_risk import reader as rd  # noqa: E402
from scripts.lib.market_risk import reentry_stages as rs  # noqa: E402

ET = ZoneInfo("America/New_York")


class FakeQuoteReader(rd.PgReader):
    """PgReader with its SQL replaced by scripted quote rows."""

    def __init__(self, rows):  # noqa: D401 - test double, no connection
        self._fake_rows = rows

    def _rows(self, sql, params):  # noqa: ANN001 - the parent's signature
        return list(self._fake_rows)


def q(symbol, when, price, prev_close=None):
    return {"symbol": symbol, "price": price, "prev_close": prev_close,
            "fetched_at": datetime.combine(_day(when), time(*when[1:]), tzinfo=ET)}


def _day(d):
    return d if isinstance(d, date) else d[0]


def test_a_pre_market_quote_never_becomes_the_days_close():
    friday, monday = date(2026, 10, 30), date(2026, 11, 2)
    rows = [
        {"symbol": "AAA", "price": 10.0, "prev_close": 9.8,
         "fetched_at": datetime(2026, 10, 30, 9, 31, tzinfo=ET)},
        {"symbol": "AAA", "price": 10.2, "prev_close": 9.8,
         "fetched_at": datetime(2026, 10, 30, 15, 59, tzinfo=ET)},
        # today's only quote so far: pre-market. It is NOT a close.
        {"symbol": "AAA", "price": 10.3, "prev_close": 10.2,
         "fetched_at": datetime(2026, 11, 2, 7, 15, tzinfo=ET)},
    ]
    out = FakeQuoteReader(rows)._quote_closes(["AAA"], start=friday, end=monday)

    assert [r["date"] for r in out] == ["2026-10-30"], out
    assert out[0]["close"] == 10.2
    assert out[0]["provisional"] is False


def test_a_same_day_close_comes_only_from_the_regular_session():
    monday = date(2026, 11, 2)
    rows = [
        {"symbol": "AAA", "price": 11.0, "prev_close": 10.9,
         "fetched_at": datetime(2026, 11, 2, 9, 31, tzinfo=ET)},
        {"symbol": "AAA", "price": 11.5, "prev_close": 10.9,
         "fetched_at": datetime(2026, 11, 2, 15, 59, tzinfo=ET)},
        {"symbol": "AAA", "price": 12.0, "prev_close": 10.9,
         "fetched_at": datetime(2026, 11, 2, 16, 30, tzinfo=ET)},
    ]
    out = FakeQuoteReader(rows)._quote_closes(["AAA"], start=monday, end=monday)

    assert len(out) == 1
    assert out[0]["close"] == 11.5
    assert out[0]["provisional"] is True


def test_an_early_close_day_uses_the_early_cutoff():
    from scripts.market_session import market_early_closes

    early = sorted(date.fromisoformat(d) for d in market_early_closes(2026)
                   if date.fromisoformat(d).weekday() < 5)[0]
    rows = [
        {"symbol": "AAA", "price": 20.0, "prev_close": 19.9,
         "fetched_at": datetime.combine(early, time(12, 59), tzinfo=ET)},
        {"symbol": "AAA", "price": 21.0, "prev_close": 19.9,
         "fetched_at": datetime.combine(early, time(13, 30), tzinfo=ET)},
    ]
    out = FakeQuoteReader(rows)._quote_closes(["AAA"], start=early, end=early)

    assert len(out) == 1 and out[0]["close"] == 20.0, out


def _bar(day, close, *, provisional=False, open_=None, volume=None):
    return {"date": day.isoformat(), "open": open_, "high": None, "low": None,
            "close": close, "volume": volume, "provisional": provisional}


def test_a_provisional_bar_never_decides_the_verdict():
    start = date(2026, 10, 20)
    bars = [_bar(start + timedelta(days=i), 100 - i * 2, open_=None, volume=None) for i in range(6)]
    bars.append(_bar(start + timedelta(days=6), 120.0, provisional=True))  # a fake "today" spike

    out = rs.evaluate(
        symbol="AAA", exit_date=start.isoformat(), exit_price=101.0, bars=bars,
        group_ratio=[], hedging_series=[], market_tier="GREEN", policy={})

    assert out["last_date"] == bars[-2]["date"], out
    assert out["verdict"] == "Still falling", out


def test_missing_open_and_volume_read_as_not_measured():
    start = date(2026, 10, 20)
    bars = [_bar(start + timedelta(days=i), 100 - i, open_=None, volume=None) for i in range(6)]

    out = rs.evaluate(
        symbol="AAA", exit_date=start.isoformat(), exit_price=101.0, bars=bars,
        group_ratio=[], hedging_series=[], market_tier="GREEN", policy={})
    conds = {c["key"]: c for c in out["stage1"]["conditions"]}

    assert conds["follow_through"]["measured"] is False
    assert conds["follow_through"]["text"].startswith("not measured")
    assert conds["volume"]["measured"] is False
    assert conds["volume"]["text"].startswith("not measured")
