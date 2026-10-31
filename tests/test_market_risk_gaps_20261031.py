"""Gap-close for the integrated Market Risk Engine (DSN-20261031): sector-ETF breadth proxy, overnight-gap proxy for
extended hours (known from the open only), IMPROVING inputs for the Green tier. Offline: no network, no database."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.lib.market_risk import breadth_proxy, contract as c
from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.categories import breadth, extended_hours, technical, volatility
from scripts.lib.market_risk.fixture_reader import ET, FixtureReader, close_instant
from scripts.lib.market_risk.policy import load_policy

POL = load_policy()
PC = POL["breadth"]["proxy"]
SECTORS = PC["universe"]


def _days(n: int, end: date = date(2024, 6, 28)) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


class Bars:
    """Minimal DataReader over synthetic closes {symbol: [floats]} aligned on the same sessions."""

    def __init__(self, series: dict[str, list[float]], opens: dict[str, float] | None = None, end: date | None = None):
        n = max(len(v) for v in series.values())
        self.days = _days(n, end or date(2024, 6, 28))
        self.series, self.opens = series, opens or {}

    def daily_bars(self, symbols, *, sessions, end):
        out = []
        for s in symbols:
            v = self.series.get(s) or []
            rows = []
            for d, cl in zip(self.days[-len(v) :], v):
                if close_instant(d) <= end:
                    rows.append(
                        {
                            "symbol": s,
                            "date": d.isoformat(),
                            "open": cl,
                            "high": cl * 1.005,
                            "low": cl * 0.995,
                            "close": cl,
                            "as_of": close_instant(d).isoformat(),
                        }
                    )
            out += rows[-sessions:]
        return out

    def session_opens(self, symbols, *, sessions, end):
        nxt = self.next_day()
        t = datetime(nxt.year, nxt.month, nxt.day, 9, 30, tzinfo=ET)
        return [
            {"symbol": s, "date": nxt.isoformat(), "open": o, "as_of": t.isoformat()}
            for s, o in self.opens.items()
            if s in set(symbols) and t <= end
        ]

    def next_day(self) -> date:
        d = self.days[-1] + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    def sector_states(self, *, end):
        return []

    def quotes(self, symbols, *, start, end):
        return []


def _trend(start: float, step: float, n: int) -> list[float]:
    return [start * (1 + step) ** i for i in range(n)]


# ── breadth proxy ─────────────────────────────────────────────────────────────────────────────────
def test_breadth_proxy_washout_is_stress_and_healthy_is_calm():
    down = {s: _trend(100, 0.0005, 260) + _trend(100 * 1.0005**259, -0.012, 40) for s in SECTORS}
    m = breadth_proxy.measure(down, {}, PC)
    sc, why = breadth_proxy.score(m, PC)
    assert m["pct_above_50"] == 0 and m["pct_at_low"] == 1.0 and m["mcclellan"] < 0
    assert sc >= POL["breadth"]["stress_score"], (sc, why)
    up = {s: _trend(100, 0.001, 300) for s in SECTORS}
    sc_up, _ = breadth_proxy.score(breadth_proxy.measure(up, {}, PC), PC)
    assert sc_up < POL["breadth"]["warn_score"]


def test_breadth_proxy_too_few_members_is_none_not_zero():
    few = {s: _trend(100, 0.001, 300) for s in SECTORS[: PC["min_members"] - 1]}
    assert breadth_proxy.measure(few, {}, PC) is None


def test_breadth_thrust_is_improving():
    # 270 calm sessions, a 12-session washout, then a 10-session broad rally: participation 0% -> 100% above 20-day.
    base = _trend(100, 0.0003, 270)
    wash = _trend(base[-1], -0.01, 12)
    rally = _trend(wash[-1], 0.012, 10)
    m = breadth_proxy.measure({s: base + wash + rally for s in SECTORS}, {}, PC)
    assert breadth_proxy.improving(m, PC), m


def test_breadth_category_uses_proxy_when_sector_states_absent():
    down = {s: _trend(100, 0.0005, 260) + _trend(100 * 1.0005**259, -0.012, 40) for s in SECTORS}
    r = Bars(down)
    now = close_instant(r.days[-1])
    o = breadth.evaluate(c.EvalContext(now=now, reader=r, policy=POL))
    assert o.state == "STRESS" and any(e.source == "daily_bars:sector_spdrs" for e in o.evidence)
    c.assert_no_behavior_fields(o.to_dict())


def test_breadth_unknown_without_any_source():
    r = Bars({"SPY": _trend(100, 0.001, 30)})
    o = breadth.evaluate(c.EvalContext(now=close_instant(r.days[-1]), reader=r, policy=POL))
    assert o.state == "UNKNOWN" and o.score is None


# ── overnight-gap proxy (extended hours) ─────────────────────────────────────────────────────────
def _gap_reader(open_px: float) -> Bars:
    s = {"SPY": _trend(500, 0.0002, 40), "QQQ": _trend(400, 0.0002, 40)}
    return Bars(s, opens={"SPY": s["SPY"][-1] * (1 + open_px / 100), "QQQ": s["QQQ"][-1] * (1 + open_px / 100)})


def test_gap_down_at_open_is_stress():
    r = _gap_reader(-2.5)
    d = r.next_day()
    o = extended_hours.evaluate(
        c.EvalContext(now=datetime(d.year, d.month, d.day, 9, 31, tzinfo=ET), reader=r, policy=POL)
    )
    assert o.state == "STRESS" and o.score >= 80, (o.state, o.score, o.headline)
    assert "opened" in o.headline


def test_gap_is_unknown_before_the_open():
    r = _gap_reader(-2.5)
    d = r.next_day()
    o = extended_hours.evaluate(
        c.EvalContext(now=datetime(d.year, d.month, d.day, 9, 29, tzinfo=ET), reader=r, policy=POL)
    )
    assert o.state == "UNKNOWN"


def test_small_gap_is_calm():
    r = _gap_reader(+0.1)
    d = r.next_day()
    o = extended_hours.evaluate(
        c.EvalContext(now=datetime(d.year, d.month, d.day, 9, 31, tzinfo=ET), reader=r, policy=POL)
    )
    assert o.state == "CALM"


def test_fixture_session_opens_never_leak_the_rest_of_the_bar():
    fr = FixtureReader()
    d = date(2020, 2, 24)
    before = fr.session_opens(["SPY"], sessions=1, end=datetime(2020, 2, 24, 9, 29, tzinfo=ET))
    after = fr.session_opens(["SPY"], sessions=1, end=datetime(2020, 2, 24, 9, 31, tzinfo=ET))
    assert before[-1]["date"] < d.isoformat() and after[-1]["date"] == d.isoformat()
    assert set(after[-1]) == {"symbol", "date", "open", "as_of"}
    bars = fr.daily_bars(["SPY"], sessions=1, end=datetime(2020, 2, 24, 9, 31, tzinfo=ET))
    assert bars[-1]["date"] < d.isoformat()  # the day's close is not knowable at 09:31


# ── IMPROVING inputs ─────────────────────────────────────────────────────────────────────────────
def test_calm_with_improving_signal_is_improving_but_warn_is_not_softened():
    ev = c.Evidence("x", 1, None, "t", "x")
    cfg = {"points": {"a": 40}, "warn_score": 30, "stress_score": 60, "stale_after_hours": 24}
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    assert md.observation("t", cfg, [], [], now, headline_prefix="T", improving=[ev]).state == "IMPROVING"
    assert md.observation("t", cfg, [("a", ev)], [], now, headline_prefix="T", improving=[ev]).state == "WARN"


def test_technical_recovery_after_correction_is_improving():
    seq = (
        _trend(100, 0.001, 140) + _trend(100 * 1.001**139, -0.006, 20) + _trend(100 * 1.001**139 * 0.994**19, 0.009, 14)
    )
    r = Bars({"SPY": seq})
    o = technical.evaluate(c.EvalContext(now=close_instant(r.days[-1]), reader=r, policy=POL))
    assert any("50-day after" in (e.detail or "") for e in o.evidence), o.headline


def test_volatility_falling_is_improving():
    vix = [30.0] * 15 + _trend(30, -0.04, 15)
    r = Bars({"^VIX": vix, "QQQ": _trend(400, 0.002, 30)})
    o = volatility.evaluate(c.EvalContext(now=close_instant(r.days[-1]), reader=r, policy=POL))
    assert o.state == "IMPROVING", (o.state, o.headline)


@pytest.mark.parametrize("key", ["breadth", "technical", "volatility", "macro_credit", "extended_hours"])
def test_every_new_threshold_lives_in_policy(key):
    assert key in POL


# ── review of #2362, B2: UNKNOWN never raises the score or the tier (regression of the reviewer's p_score fuzz) ──────
def _ob(cat: str, state: str, score: float | None, now: datetime) -> c.CategoryObservation:
    return c.CategoryObservation(
        category=cat,
        state=state,
        score=None if state == "UNKNOWN" else score,
        observed_at=now.isoformat(),
        headline=cat,
        reason_unknown="x" if state == "UNKNOWN" else None,
    )


def test_calm_to_unknown_never_raises_score_or_tier_fuzz():
    import random

    from scripts.lib.market_risk import scoring

    now = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)
    rnd = random.Random(1)
    states = ["CALM", "IMPROVING", "WARN", "STRESS", "UNKNOWN"]
    raised = []
    for _ in range(4000):
        spec = {k: (rnd.choice(states), rnd.uniform(0, 100)) for k in c.CATEGORIES}
        calm = [k for k, (st, _) in spec.items() if st == "CALM"]
        if not calm:
            continue
        a = scoring.compose([_ob(k, *spec[k], now) for k in c.CATEGORIES], POL, now=now)
        k = rnd.choice(calm)
        spec[k] = ("UNKNOWN", None)
        b = scoring.compose([_ob(k2, *spec[k2], now) for k2 in c.CATEGORIES], POL, now=now)
        if (b.score or 0) > (a.score or 0) + 1e-9 or scoring.SEVERITY[b.tier] > scoring.SEVERITY[a.tier]:
            raised.append((k, a.score, b.score, a.tier, b.tier))
    assert not raised, raised[:3]


def test_warns_alone_never_reach_orange_whatever_the_score():
    from scripts.lib.market_risk import scoring

    now = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)
    a = scoring.compose([_ob(k, "WARN", 59, now) for k in c.CATEGORIES], POL, now=now)
    assert a.score > 60 and scoring.SEVERITY[a.tier] < scoring.SEVERITY["ORANGE"], (a.score, a.tier)
