"""Event, AI-concentration, breadth and seasonal categories (DSN-20261031 P1-T6, P2-T6). Synthetic data only."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.market_risk import ai_concentration, event_calendar
from scripts.lib.market_risk.categories import breadth, event, seasonal
from scripts.lib.market_risk.contract import EvalContext, assert_no_behavior_fields
from scripts.lib.market_risk.policy import load_policy

ET = ZoneInfo("America/New_York")
POLICY = load_policy()

# Synthetic index-cap shares shaped like the 2026-10 cluster (not real index data).
WEIGHTS = {"MSFT": 0.08, "GOOGL": 0.07, "META": 0.05, "AMZN": 0.06, "INTC": 0.005, "AAPL": 0.09, "NVDA": 0.09}
EARNINGS = [
    {"symbol": "MSFT", "earnings_date": "2026-10-28", "timing": "AMC"},
    {"symbol": "GOOGL", "earnings_date": "2026-10-28", "timing": "AMC"},
    {"symbol": "META", "earnings_date": "2026-10-29", "timing": "AMC"},
    {"symbol": "AMZN", "earnings_date": "2026-10-29", "timing": "AMC"},
    {"symbol": "INTC", "earnings_date": "2026-10-29", "timing": "AMC"},
    {"symbol": "AAPL", "earnings_date": "2026-10-30", "timing": "AMC"},
]
MACRO = [{"date": "2026-10-28", "event": "fomc_decision", "name": "FOMC rate decision", "time_et": "14:00"}]


class Reader:
    def __init__(self, earnings=(), macro=(), sectors=(), bars=(), fail=False):
        self._e, self._m, self._s, self._b, self._fail = list(earnings), list(macro), list(sectors), list(bars), fail

    def _chk(self):
        if self._fail:
            raise ConnectionError("db down")

    def earnings_calendar(self, *, start, end):
        self._chk()
        return self._e

    def macro_calendar(self, *, start, end):
        self._chk()
        return self._m

    def sector_states(self, *, end):
        self._chk()
        return self._s

    def daily_bars(self, symbols, *, sessions, end):
        self._chk()
        return [b for b in self._b if b["symbol"] in set(symbols)]


def ctx(now, reader, weights=WEIGHTS, policy=POLICY, **extras):
    ex = {"index_weights": {"weights": weights, "as_of": "2026-10-23"}} if weights else {}
    ex.update(extras)
    return EvalContext(now=now, reader=reader, policy=policy, extras=ex)


def et(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET)


# ---- event calendar --------------------------------------------------------------------------------------------


def test_election_day():
    assert event_calendar.election_day(2026) == date(2026, 11, 3)
    assert event_calendar.election_day(2027) is None


def test_session_window_skips_weekend_and_today_after_close():
    assert event_calendar.next_sessions(et(2026, 10, 30, 17), 2) == [date(2026, 11, 2), date(2026, 11, 3)]
    assert event_calendar.next_sessions(et(2026, 10, 26, 6, 30), 1) == [date(2026, 10, 26)]


def test_rca_monday_10_26_is_stress():
    o = event.evaluate(ctx(et(2026, 10, 26, 6, 30), Reader(EARNINGS, MACRO)))
    assert o.state == "STRESS", o
    assert o.score >= POLICY["event"]["stress_score"]
    assert "MSFT" in o.headline and "FOMC" in o.headline
    assert_no_behavior_fields(o.to_dict())


def test_rca_wednesday_10_28_close_counts_tonights_reporters():
    now = et(2026, 10, 28, 16, 30)
    conc = event_calendar.evaluate_concentration(now, EARNINGS, MACRO, WEIGHTS, POLICY["event"])
    rep = conc["earnings"]["3"]["reporters"]
    assert {"MSFT", "GOOGL", "AMZN", "META"} <= set(rep)  # tonight's AMC still ahead at 16:30
    assert conc["macro"] == []  # FOMC already released at 14:00
    assert any(t["tag"] == "election_day" for t in conc["calendar"])
    assert event.evaluate(ctx(now, Reader(EARNINGS, MACRO))).state == "STRESS"


def test_after_amc_cutoff_tonights_reporters_drop_out():
    conc = event_calendar.evaluate_concentration(et(2026, 10, 28, 21), EARNINGS, [], WEIGHTS, POLICY["event"])
    assert "MSFT" not in conc["earnings"]["1"]["reporters"]


def test_quiet_week_is_calm():
    o = event.evaluate(ctx(et(2026, 11, 10, 9), Reader([], [])))
    assert o.state == "CALM", o


def test_missing_weights_is_reported_not_zero():
    o = event.evaluate(ctx(et(2026, 10, 26, 6, 30), Reader(EARNINGS, MACRO), weights=None))
    ev = {e.label: e.value for e in o.evidence}
    assert ev["index-cap share reporting"] == "not measured"
    assert "earnings share not measured" in o.headline


def test_reader_failure_is_unknown():
    o = event.evaluate(ctx(et(2026, 10, 26, 6, 30), Reader(fail=True)))
    assert o.state == "UNKNOWN" and o.score is None and "db down" in o.reason_unknown


# ---- P2-T6: AI earnings sensitivity alone forces event STRESS ---------------------------------------------------


def test_ai_sensitivity_alone_sets_event_stress():
    now = et(2026, 11, 10, 9)
    rows = [
        {"symbol": "NVDA", "earnings_date": "2026-11-10", "timing": "AMC"},
        {"symbol": "AMD", "earnings_date": "2026-11-11", "timing": "AMC"},
    ]
    w = {"NVDA": 0.12, "AMD": 0.04}
    conc = event_calendar.evaluate_concentration(now, rows, [], w, POLICY["event"])
    assert conc["event_concentration_score"] < POLICY["event"]["warn_score"]  # concentration alone is CALM
    o = event.evaluate(ctx(now, Reader(rows, []), weights=w))
    assert o.state == "STRESS"
    assert o.score >= POLICY["event"]["ai_sensitivity_stress_score"]


def test_ai_sensitivity_below_threshold_is_calm():
    now = et(2026, 11, 10, 9)
    rows = [{"symbol": "NVDA", "earnings_date": "2026-11-10", "timing": "AMC"}]
    o = event.evaluate(ctx(now, Reader(rows, []), weights={"NVDA": 0.10}))
    assert o.state == "CALM"


# ---- AI concentration technical feed -----------------------------------------------------------------------------


def _bars(drift_basket: float, drift_bench: float, n: int = 60):
    out, d0 = [], date(2026, 8, 1)
    days = [d0 + timedelta(days=i) for i in range(n)]
    for s in ai_concentration.basket(POLICY["ai_concentration"]):
        for i, d in enumerate(days):
            c = 100 * (1 + (0.002 * i if i < n - 20 else 0.002 * (n - 20) + drift_basket * (i - (n - 20))))
            out.append({"symbol": s, "date": d.isoformat(), "close": c})
    for s in ("RSP", "SPY"):
        for i, d in enumerate(days):
            out.append({"symbol": s, "date": d.isoformat(), "close": 100 * (1 + drift_bench * i)})
    return out


def test_ai_basket_breakdown_is_stress():
    series = ai_concentration._series(_bars(-0.006, 0.0))
    t = ai_concentration.technical_signal(series, POLICY["ai_concentration"])
    assert t["state"] == "STRESS", t
    assert t["participation"]["above_20_share"] < POLICY["ai_concentration"]["participation_stress"]
    assert t["drawdown_pct"] < 0


def test_ai_basket_uptrend_is_calm():
    series = ai_concentration._series(_bars(0.003, 0.0005))
    t = ai_concentration.technical_signal(series, POLICY["ai_concentration"])
    assert t["state"] == "CALM", t


def test_ai_module_evaluate_end_to_end():
    out = ai_concentration.evaluate(ctx(et(2026, 10, 28, 16, 30), Reader(EARNINGS, MACRO, bars=_bars(-0.006, 0.0))))
    assert out["technical"]["state"] == "STRESS"
    assert out["earnings_sensitivity"]["state"] == "STRESS"


def test_ai_no_bars_is_unknown():
    t = ai_concentration.technical_signal({}, POLICY["ai_concentration"])
    assert t["state"] == "UNKNOWN" and t["score"] is None


# ---- breadth --------------------------------------------------------------------------------------------------

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]


def _sectors(style, xlk, xlk_breadth, weak_n):
    rows = [{"as_of": "2026-10-29", "etf": "STYLE:equal_vs_cap", "state": style}]
    for i, e in enumerate(SECTORS):
        st = xlk if e == "XLK" else ("WEAKENING" if i <= weak_n - 1 else "LEADING")
        rows.append({"as_of": "2026-10-29", "etf": e, "state": st, "breadth_pct": xlk_breadth if e == "XLK" else 60})
    rows.append({"as_of": "2026-10-28", "etf": "XLK", "state": "LEADING", "breadth_pct": 70})  # older row ignored
    return rows


def test_rca_10_29_breadth_is_warn():
    o = breadth.evaluate(ctx(et(2026, 10, 29, 16, 45), Reader(sectors=_sectors("WEAKENING", "WEAKENING", 42, 5))))
    assert o.state == "WARN", o
    assert "RSP−SPY WEAKENING" in o.headline and "XLK WEAKENING 42% breadth" in o.headline
    assert any(e.value == "not measured" and e.source == "market_breadth_daily" for e in o.evidence)


def test_breadth_broad_deterioration_is_stress():
    o = breadth.evaluate(ctx(et(2026, 10, 29, 16, 45), Reader(sectors=_sectors("LAGGING", "LAGGING", 20, 11))))
    assert o.state == "STRESS", o


def test_breadth_healthy_is_calm():
    o = breadth.evaluate(ctx(et(2026, 10, 29, 16, 45), Reader(sectors=_sectors("LEADING", "LEADING", 70, 0))))
    assert o.state == "CALM", o


def test_breadth_without_rows_is_unknown():
    o = breadth.evaluate(ctx(et(2026, 10, 29, 16, 45), Reader()))
    assert o.state == "UNKNOWN" and o.score is None


# ---- seasonal -------------------------------------------------------------------------------------------------


def test_seasonal_oct_2026_is_low():
    o = seasonal.evaluate(ctx(et(2026, 10, 30, 9), Reader()))
    assert o.state == "CALM" and o.score < POLICY["seasonal"]["warn_score"]


@pytest.mark.parametrize("month_day", [(9, 18), (10, 30), (12, 31), (3, 31)])
def test_seasonal_never_stress_even_with_extreme_policy(month_day):
    pol = copy.deepcopy(POLICY)
    pol["seasonal"]["points"] = {k: 100 for k in pol["seasonal"]["points"]}
    pol["seasonal"]["max_score"] = 100
    pol["seasonal"]["warn_score"] = 1
    o = seasonal.evaluate(ctx(et(2026, *month_day, 12), Reader(), policy=pol))
    assert o.state in ("CALM", "WARN")
