"""LQ-20261107-1392 — Home freshness: four defects, four producers/renderers, one rule each.

Measured live on 2026-11-08 (Sunday) before the fix:

1. the header REGIME tile painted a quiet dot beside a 55.23-hour-old snapshot (``stale: true`` in the
   very body the tile received) because it read useApi's TRANSPORT stale flag, never the envelope;
2. TODAY said "market-day session 2026-11-08" on a Sunday, while the same payload's ``market_session``
   said ``latest_open_session 2026-11-06`` — ``mark_session_date`` is the ET calendar date of the marks;
3. market risk's volatility category was UNKNOWN, "VIX stale (newest 2026-11-05T21:00:00+00:00)", while
   Schwab carried Friday's 16:00 print (25.64) — the VIX complex let FRED's T+1 Thursday observation beat
   a newer carried print, so the Friday print never reached the engine;
4. MU showed Thursday's close and "no session since the exit" although it exited Friday and Friday's close
   was stored — the newest completed session was flagged provisional unconditionally and ``reentry_stages``
   drops provisional bars.

(1) is pinned at the renderer by ``src/lib/homeRegimeHeaderTile.view.test.mjs`` (run by the app's own test
runner). These cases pin (2), (3) and (4) at their producers.

Operator amendments (2026-11-08 20:40 / 20:52 ET) as they apply here: every value names a source and an
``as_of``; a missing value is absent with a reason, never 0; a stale input is not scored; and a fix lands in
the producer, not in one renderer.

Synthetic fixtures only — the repository is public. No DB, no network.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import cio_truth as truth                                   # noqa: E402
from scripts.lib.market_regime import vix_complex as vc             # noqa: E402
from scripts.lib.market_risk import reader as rd                    # noqa: E402
from scripts.lib.market_risk import reentry_stages as rs            # noqa: E402
from scripts.lib.market_risk.categories import volatility           # noqa: E402
from scripts.lib.market_risk.contract import EvalContext            # noqa: E402
from scripts.lib.market_risk.policy import load_policy              # noqa: E402

ET = ZoneInfo("America/New_York")


def _weekdays(n: int, end: date) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


# ── 2. TODAY: the marks' calendar date is not a session ─────────────────────────────────────────────────────


class TestTheSessionTheMarksBelongTo:
    """`today_move_payload` may only publish a session date that could have been a session."""

    def _payload(self, *, marks: str | None, latest: str | None, status: str = "KNOWN", change=1234.5):
        today_pnl = {
            "mark_session_date": marks,
            "mark_session_source": "holdings.last_repriced",
            "mark_source": "finviz_overnight",
            "mark_batch_at": "2026-11-08T03:55:00+00:00",
            "market_session": {"status": status, "latest_open_session": latest,
                               "is_trading_day": status == "KNOWN" and latest == marks},
            "stored_row_evidence": {"census": {"missing_accounts": [], "partial_accounts": []}},
        }
        return truth.today_move_payload({"change": change, "change_pct": 1.1}, {}, today_pnl)

    def test_sunday_marks_carry_the_newest_opened_session_and_say_so(self):
        out = self._payload(marks="2026-11-08", latest="2026-11-06")
        assert out["session_date"] == "2026-11-06"
        assert "marks observed 2026-11-08" in out["session_source"]
        assert out["session_date"] != out["marks_observed"]
        # the observation itself is never lost
        assert out["marks_observed"] == "2026-11-08"
        assert out["marks_observed_source"] == "holdings.last_repriced"
        assert out["change"] == 1234.5

    def test_marks_taken_on_a_session_day_are_not_re_dated(self):
        out = self._payload(marks="2026-11-05", latest="2026-11-05")
        assert out["session_date"] == "2026-11-05"
        assert out["session_source"] == "holdings.last_repriced"
        assert out["marks_observed"] == "2026-11-05"

    def test_marks_older_than_the_newest_session_are_left_alone(self):
        # A stale mark is a real session's mark; the renderer's AGED SOURCE guard owns that case.
        out = self._payload(marks="2026-11-04", latest="2026-11-06")
        assert out["session_date"] == "2026-11-04"

    def test_an_unknown_calendar_is_never_corrected_by_guess(self):
        out = self._payload(marks="2026-11-08", latest=None, status="UNKNOWN")
        assert out["session_date"] == "2026-11-08"          # unchanged: the translation needs a proven session
        assert out["marks_observed"] == "2026-11-08"

    def test_no_marks_means_no_session_and_no_source(self):
        out = self._payload(marks=None, latest="2026-11-06")
        assert out["session_date"] is None and out["marks_observed"] is None
        assert out["session_source"] is None

    def test_the_helper_never_invents_a_session_for_a_bare_date(self):
        assert truth._mark_session("2026-11-08", None, "x") == ("2026-11-08", "x")
        assert truth._mark_session("2026-11-08", {"status": "UNKNOWN"}, "x") == ("2026-11-08", "x")
        assert truth._mark_session(None, {"status": "KNOWN", "latest_open_session": "2026-11-06"}, "x") == (None, None)


# ── 3. the VIX complex: the NEWER session wins, and the Friday print reaches MRE ────────────────────────────


def _schwab_carried(value: float, print_day: str) -> dict:
    """One accepted Schwab CBOE-index row, shaped exactly as ``read_quotes`` emits it."""
    return {"value": value, "source": "market_quotes_extended:schwab", "symbol": "$VIX", "age_hours": 55.5,
            "as_of": f"{print_day}T16:00:00-05:00", "session": "overnight", "session_date": "2026-11-09",
            "reference_basis": f"schwab_index_level_carried_print_{print_day}", "fresh": False,
            "carried_from": print_day, "bar_end": "2026-11-08T20:00:00-05:00"}


def _fred(value: float, observed: str) -> dict:
    return {"value": value, "source": "fred_economic_series", "series_id": "VIXCLS",
            "observation_date": observed, "as_of": observed, "age_days": 3, "session": "close",
            "session_date": observed, "reference_basis": "fred_close", "fresh": False}


class TestTheNewerVixSessionWins:
    def test_a_friday_carry_beats_thursdays_fred_close(self):
        values, how = vc.merge({"vix_close": _schwab_carried(25.64, "2026-11-06")},
                               {"vix_close": _fred(28.18, "2026-11-05")})
        assert values["vix_close"]["value"] == 25.64
        assert values["vix_close"]["carried_from"] == "2026-11-06"
        assert how["vix_close"] == "schwab"
        # FRED's observation is kept as evidence, not discarded
        assert values["vix_close"]["fred_value"] == 28.18
        assert values["vix_close"]["fred_observation_date"] == "2026-11-05"

    def test_a_fred_close_for_the_same_session_still_wins(self):
        values, how = vc.merge({"vix_close": _schwab_carried(25.64, "2026-11-06")},
                               {"vix_close": _fred(25.10, "2026-11-06")})
        assert how["vix_close"] == "fred" and values["vix_close"]["value"] == 25.10
        assert values["vix_close"]["schwab_carried_level"] == 25.64

    def test_a_newer_fred_observation_still_wins(self):
        values, how = vc.merge({"vix_close": _schwab_carried(25.64, "2026-11-06")},
                               {"vix_close": _fred(24.00, "2026-11-09")})
        assert how["vix_close"] == "fred" and values["vix_close"]["value"] == 24.00

    def test_no_fred_row_leaves_the_carried_print_alone(self):
        values, how = vc.merge({"vix_close": _schwab_carried(25.64, "2026-11-06")}, {})
        assert how["vix_close"] == "schwab" and values["vix_close"]["value"] == 25.64

    def test_an_undated_pair_is_not_re_ordered(self):
        # Absent dates must not be read as "older": the previous rule stands (FRED fills the gap).
        undated = {k: v for k, v in _fred(28.18, "2026-11-05").items()
                   if k not in ("observation_date", "as_of", "session_date")}
        values, how = vc.merge({"vix_close": _schwab_carried(25.64, "2026-11-06")}, {"vix_close": undated})
        assert how["vix_close"] == "fred"

    def test_the_session_of_a_carried_print_is_its_print_date_not_the_overnight_bar(self):
        # The store's session_date is the overnight bar's (2026-11-09); the print is what dates the value.
        assert vc._session_of(_schwab_carried(25.64, "2026-11-06")) == "2026-11-06"


class _CategoryReader:
    """A ``DataReader`` double: the rows the caller supplies, nothing else."""

    def __init__(self, bars):
        self._bars = bars

    def daily_bars(self, symbols, *, sessions, end):
        return [r for s in symbols for r in (self._bars.get(s) or [])[-sessions:]]


def _vix_row(day: date, close: float, source: str, provisional: bool = False) -> dict:
    close_at = datetime.combine(day, time(16, 0), tzinfo=ET)
    return {"symbol": "^VIX", "date": day.isoformat(), "close": close, "as_of": close_at.isoformat(),
            "source": source, "provisional": provisional}


def _flat(symbol: str, days: list[date], close: float) -> list[dict]:
    return [{"symbol": symbol, "date": d.isoformat(), "close": close,
             "as_of": datetime.combine(d, time(16, 0), tzinfo=ET).isoformat()} for d in days]


class TestVolatilitySeesFridaysPrint:
    SUNDAY = datetime(2026, 11, 8, 23, 0, tzinfo=ET)

    def _bars(self, *, with_friday: bool) -> dict:
        days = _weekdays(12, date(2026, 11, 5))
        out = {"^VIX": [_vix_row(d, 20.0 + i * 0.1, "fred_economic_series:VIXCLS") for i, d in enumerate(days)],
               "QQQ": _flat("QQQ", days, 500.0), "SPY": _flat("SPY", days, 600.0)}
        if with_friday:
            out["^VIX"].append(_vix_row(date(2026, 11, 6), 25.64, "vix_complex:schwab", provisional=True))
        return out

    def _eval(self, bars):
        ctx = EvalContext(now=self.SUNDAY, reader=_CategoryReader(bars), policy=load_policy())
        return volatility.evaluate(ctx)

    def test_the_friday_print_is_scored_on_sunday(self):
        got = self._eval(self._bars(with_friday=True))
        assert got.state != "UNKNOWN"
        assert got.reason_unknown is None
        vix = next(e for e in got.evidence if e.label == "VIX close")
        assert vix.value == pytest.approx(25.64)
        assert str(vix.as_of)[:10] == "2026-11-06"
        assert "schwab" in str(vix.source)

    def test_thursdays_close_alone_is_stale_and_says_which_date_it_used(self):
        got = self._eval(self._bars(with_friday=False))
        assert got.state == "UNKNOWN"
        assert "2026-11-05" in got.reason_unknown

    def test_no_vix_history_is_unknown_not_a_zero(self):
        got = self._eval({"QQQ": _flat("QQQ", _weekdays(12, date(2026, 11, 5)), 500.0)})
        assert got.state == "UNKNOWN" and "VIX history missing" in got.reason_unknown
        assert got.score is None
        assert not any(e.label == "VIX close" for e in got.evidence)


# ── 4. a completed session's close is not provisional ───────────────────────────────────────────────────────


class FakeQuoteReader(rd.PgReader):
    """PgReader with its SQL replaced by scripted quote rows."""

    def __init__(self, rows):  # noqa: D401 -- a test double has no connection to close, so no docstring contract
        self._fake_rows = rows

    def _rows(self, sql, params):  # noqa: ANN001 -- mirrors the parent PgReader signature it replaces
        return list(self._fake_rows)


def _q(day: date, hh: int, mm: int, price: float, prev_close: float | None = None) -> dict:
    return {"symbol": "ZZQ", "price": price, "prev_close": prev_close,
            "fetched_at": datetime.combine(day, time(hh, mm), tzinfo=ET)}


class TestACompletedSessionIsNotProvisional:
    THU, FRI, SUN = date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 8)

    def _week(self) -> list[dict]:
        return [_q(self.THU, 9, 31, 100.0, 99.0), _q(self.THU, 15, 59, 101.5, 99.0),
                _q(self.FRI, 9, 31, 102.0, 101.5), _q(self.FRI, 15, 59, 104.25, 101.5)]

    def test_sundays_series_ends_with_fridays_real_close(self):
        out = FakeQuoteReader(self._week())._quote_closes(
            ["ZZQ"], start=datetime.combine(self.THU, time(4), tzinfo=ET),
            end=datetime.combine(self.SUN, time(23), tzinfo=ET))
        assert [(r["date"], float(r["close"]), r["provisional"]) for r in out] == [
            ("2026-11-05", 101.5, False),
            ("2026-11-06", 104.25, False),   # the fix: no longer hidden behind provisional=True
        ]
        # every bar names how its close was derived
        assert out[0]["source"] == "market_quotes:alpaca_prev_close"
        assert out[1]["source"] == "market_quotes:alpaca_last"

    def test_a_session_still_open_at_end_is_provisional(self):
        out = FakeQuoteReader(self._week())._quote_closes(
            ["ZZQ"], start=datetime.combine(self.THU, time(4), tzinfo=ET),
            end=datetime.combine(self.FRI, time(11, 0), tzinfo=ET))
        assert [(r["date"], r["provisional"]) for r in out] == [("2026-11-05", False), ("2026-11-06", True)]

    def test_the_last_session_now_reaches_the_stage_verdict(self):
        bars = FakeQuoteReader(self._week())._quote_closes(
            ["ZZQ"], start=datetime.combine(self.THU, time(4), tzinfo=ET),
            end=datetime.combine(self.SUN, time(23), tzinfo=ET))
        out = rs.evaluate(symbol="ZZQ", exit_date="2026-11-06", exit_price=103.0, bars=bars,
                          group_ratio=[], hedging_series=[], market_tier="GREEN",
                          policy=load_policy())
        assert out["last_date"] == "2026-11-06"
        assert out["last_close"] == pytest.approx(104.25)
        assert "no session" not in str(out.get("note") or "")
        assert out["stage2"]["conditions"][0]["key"] == "above_exit"
        assert out["stage2"]["conditions"][0]["met"] is True

    def test_an_after_hours_print_is_still_not_the_close(self):
        rows = self._week() + [_q(self.FRI, 16, 45, 999.0, 101.5)]
        out = FakeQuoteReader(rows)._quote_closes(
            ["ZZQ"], start=datetime.combine(self.THU, time(4), tzinfo=ET),
            end=datetime.combine(self.SUN, time(23), tzinfo=ET))
        assert [float(r["close"]) for r in out] == [101.5, 104.25]
