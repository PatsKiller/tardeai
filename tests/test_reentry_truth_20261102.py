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


# ---------------------------------------------------------------- delivery and the watch list
from scripts.lib.market_risk import book_precision as bp  # noqa: E402
from scripts.lib.market_risk import reentry_watch as rw  # noqa: E402


def _watch(verdict, *, status="RE_ENTER_IF", exit_date="2026-10-30"):
    return {"symbol": "AAA", "status": status, "stance": "RE_ENTER" if status == "RE_ENTER" else "RE_ENTER_IF",
            "headline": "trend repaired", "conditions": [], "met": 0, "of": 5,
            "exit_date": exit_date, "exit_price": 100.0, "last_close": 101.0, "as_of": "2026-11-01",
            "stages": {"verdict": verdict, "swing_low": 98.0}}


def _doc(verdict, **kw):
    return {"AAA": _watch(verdict, **kw), "_stages_contract": rw.STAGES_CONTRACT}


def _prior(verdict):
    return {"AAA": {"stages": {"verdict": verdict}}, "_stages_contract": rw.STAGES_CONTRACT}


def test_a_stage_verdict_change_queues_one_card():
    cards = rw.stage_cards(_doc("Early setup"), _prior("Still falling"), {"reentry_watch": {}})
    assert len(cards) == 1
    assert cards[0]["key"] == "market_risk:reentry:AAA:2026-10-30:Early setup"
    assert "Early setup" in cards[0]["text"] and "was Still falling" in cards[0]["text"]
    assert "invalidation level" in cards[0]["text"]
    assert "no order, size or stop" in cards[0]["text"]
    assert cards[0]["intent"]["priority"] == "P2"


def test_no_stage_card_without_a_change():
    assert rw.stage_cards(_doc("Early setup"), _prior("Early setup"), {"reentry_watch": {}}) == []


def test_no_stage_card_without_a_prior_verdict():
    assert rw.stage_cards(_doc("Confirmed"), {"_stages_contract": rw.STAGES_CONTRACT},
                          {"reentry_watch": {}}) == []


def test_a_prior_without_the_contract_is_a_first_classification():
    """Deploy day: verdicts from the old computation must not page as a change."""
    prior = {"AAA": {"stages": {"verdict": "Confirmed"}}}
    assert rw.stage_cards(_doc("Early setup"), prior, {"reentry_watch": {}}) == []


def test_an_invalidated_transition_queues_a_card():
    cards = rw.stage_cards(_doc("Invalidated"), _prior("Early setup"), {"reentry_watch": {}})
    assert len(cards) == 1 and cards[0]["key"].endswith(":Invalidated")


def test_re_enter_and_a_stage_change_send_both_cards():
    watch = {"AAA": _watch("Early setup", status="RE_ENTER"), "_stages_contract": rw.STAGES_CONTRACT}
    prior = {"AAA": {"status": "RE_ENTER_IF", "stages": {"verdict": "Still falling"}},
             "_stages_contract": rw.STAGES_CONTRACT}
    cards = rw.stage_cards(watch, prior, {"reentry_watch": {}})
    assert len(cards) == 2, cards
    assert {c["intent"]["transition"] for c in cards} == {"reentry", "reentry_stage"}


def test_a_trim_is_not_a_residual_and_a_stop_remainder_is():
    # SCHD: trimming 20 of 6000.253 leaves 5980.253 held.
    assert bp._is_fractional_residual(5980.253, 20.0, 1.0) is False
    # PFLT: a stop sold at least the remaining 1.15 shares.
    assert bp._is_fractional_residual(1.15, 10.0, 1.0) is True
    # dust below the materiality floor
    assert bp._is_fractional_residual(0.4, 0.0, 1.0) is True
    # a fractional holding with no sale is a position
    assert bp._is_fractional_residual(130.4985, 0.0, 1.0) is False


def test_a_stop_must_match_the_sale_session():
    acct = bp._acct_key("Schwab-1")
    rows = [("AAA", "Schwab-1", 100.0, "2026-10-29T15:00:00Z")]
    assert bp._stop_basis("AAA", acct, 100.5, rows, "2026-10-30") == "manual sell"
    rows = [("AAA", "Schwab-1", 100.0, "2026-10-30T15:00:00Z")]
    assert bp._stop_basis("AAA", acct, 100.5, rows, "2026-10-30") == "stop"
    assert bp._stop_basis("AAA", bp._acct_key("Other"), 100.5, rows, "2026-10-30") == "manual sell"


def test_the_card_guard_refuses_stop_and_order_wording():
    import pytest

    with pytest.raises(ValueError):
        rw._guard("RE-ENTRY WATCH · AAA · set a stop at 98.00")
    with pytest.raises(ValueError):
        rw._guard("RE-ENTRY WATCH · AAA · sell 10 shares")
    rw._guard("RE-ENTRY WATCH · AAA · invalidation level (swing low) 98.00 — no order, size or stop is implied")
