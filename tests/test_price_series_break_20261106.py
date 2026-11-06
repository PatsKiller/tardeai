"""PKG-SELLOFF-INTEL-20261106 F: a price-history break (an unadjusted split) never becomes a market move.

The 11-06 page said "SOXX -79.1% off 52w high". The 52-week high (654.58, June) came from split-adjusted daily bars; the
last two closes came from quote snapshots after a ~3-for-1 split on 11-05 (451.20 -> 130.94). The engine compared the
two. These tests pin the guard: the technical category measures only the sessions after such a break and says so, a
short series names its real span instead of "52w", and the sector attribution drops a broken member from its group.

Synthetic fixtures only: invented prices on public ETF tickers, no holdings, no account data. No network, no DB.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone

from scripts.lib.market_risk import sectors
from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.categories import technical
from scripts.lib.market_risk.contract import EvalContext
from scripts.lib.market_risk.policy import load_policy

END = date(2031, 3, 7)  # a Friday
NOW = datetime(2031, 3, 7, 22, 0, tzinfo=timezone.utc)  # 17:00 ET, after the close
POLICY = load_policy()


def bdays(n: int, end: date = END) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


class Reader:
    def __init__(self, bars):
        self._bars = bars

    def daily_bars(self, symbols, *, sessions, end):
        return [
            {"symbol": s, "date": d.isoformat(), "close": c}
            for s in symbols
            for d, c in (self._bars.get(s) or [])[-sessions:]
        ]


def drift(n: int, start: float, step_pct: float) -> list[float]:
    out, px = [], start
    for _ in range(n):
        out.append(round(px, 4))
        px *= 1 + step_pct / 100
    return out


def series(closes: list[float]) -> list[tuple[date, float]]:
    return list(zip(bdays(len(closes)), closes))


def split_soxx(after: int) -> list[float]:
    """300 sessions climbing to ~650, then a 3-for-1 split on a -13% day, then ``after - 1`` more sessions."""
    pre = drift(300 - after, 300.0, 0.3)
    post_first = pre[-1] * 0.87 / 3
    return pre + drift(after, post_first, -0.1)


# -- the helper ---------------------------------------------------------------------------------------------------


def test_price_break_finds_the_split_and_ignores_real_moves():
    assert md.price_break(drift(50, 100.0, 1.0)) is None
    # a -20% day (the market-wide circuit breaker) and a +40% day are moves, not breaks
    assert md.price_break([100.0, 80.0, 112.0, 113.0]) is None
    i, ratio = md.price_break([451.20, 130.935, 136.8])
    assert i == 1 and round(ratio, 3) == 0.290
    # a reverse split is a break too; the NEWEST break wins
    i, ratio = md.price_break([10.0, 40.0, 41.0, 13.0, 13.5])
    assert i == 3 and round(ratio, 3) == 0.317
    # the threshold is the policy's, both directions inclusive
    assert md.price_break([100.0, 250.0]) == (1, 2.5)
    assert md.price_break([100.0, 249.0]) is None
    assert md.price_break([100.0, 0.0, 50.0]) is None  # a zero close is missing data, not a step


def test_policy_states_the_ratio():
    assert POLICY["technical"]["series_break_ratio"] == 2.5
    assert POLICY["sectors"]["series_break_ratio"] == 2.5


# -- technical ----------------------------------------------------------------------------------------------------


def _technical(bars):
    obs = technical.evaluate(EvalContext(now=NOW, reader=Reader(bars), policy=POLICY))
    text = " | ".join(f"{e.label}: {e.detail}" for e in obs.evidence)
    return obs, text


def _flat_others(n=300):
    return {s: series(drift(n, 100.0, 0.05)) for s in ("QQQ", "SPY", "SMH", "IWM")}


def test_split_two_sessions_ago_is_not_a_79_percent_drawdown():
    bars = {**_flat_others(), "SOXX": series(split_soxx(after=2))}
    obs, text = _technical(bars)
    assert "SOXX -7" not in text
    assert not any("SOXX" in (e.detail or "") and "off 52w high" in (e.detail or "") for e in obs.evidence)
    brk = [e for e in obs.evidence if e.label == "price history break"]
    assert len(brk) == 1
    assert brk[0].detail.startswith(f"SOXX price history breaks on {bdays(2)[0].isoformat()}")
    assert "likely an unadjusted split" in brk[0].detail and "only the 2 sessions since are used" in brk[0].detail
    assert round(brk[0].value, 2) == 0.29
    # two sessions are under min_sessions: SOXX is out of the measured set, not scored on a mixed series
    assert not any(e.label == "last close" and (e.detail or "").startswith("SOXX") for e in obs.evidence)


def test_control_same_prices_without_the_guard_would_read_minus_79():
    """The bug as it was: max of the mixed series against the post-split close."""
    closes = split_soxx(after=2)
    assert round(md.pct(closes[-1], max(closes[-252:])), 0) <= -70


def test_after_a_break_the_drawdown_names_its_real_span():
    # 40 sessions after the split, falling 0.5% a day: about -18% off the post-split high, which is a real drawdown
    pre = drift(260, 300.0, 0.3)
    post = drift(40, pre[-1] / 3, -0.5)
    bars = {**_flat_others(), "SOXX": series(pre + post)}
    obs, _ = _technical(bars)
    soxx = [e for e in obs.evidence if (e.detail or "").startswith("SOXX") and "high" in (e.detail or "")]
    details = " | ".join(e.detail for e in soxx)
    assert "off 40-session high" in details
    assert "52w" not in details
    assert any(e.label == "price history break" for e in obs.evidence)


def test_no_break_keeps_the_52_week_label():
    closes = drift(220, 100.0, 0.2) + drift(80, 150.0, -0.4)
    bars = {**_flat_others(), "SOXX": series(closes)}
    obs, text = _technical(bars)
    assert "SOXX" in text and "off 52w high" in text
    assert not any(e.label == "price history break" for e in obs.evidence)


# -- sectors ------------------------------------------------------------------------------------------------------


def _sector_policy():
    pol = copy.deepcopy(POLICY)
    s = pol["sectors"]
    s["groups"] = [
        {"key": "semis", "label": "Semis", "kind": "theme", "symbols": ["SMH", "SOXX"]},
        {"key": "soxx_only", "label": "SOXX alone", "kind": "theme", "symbols": ["SOXX"]},
        {"key": "staples", "label": "Staples", "kind": "sector", "symbols": ["XLP"]},
    ]
    s["factor_symbols"] = []
    s["factor_pairs"] = {}
    return pol


def _measure(bars):
    return sectors.measure(EvalContext(now=NOW, reader=Reader(bars), policy=_sector_policy()))


def test_sectors_drop_a_broken_member_and_say_so():
    n = 300
    bars = {
        "SPY": series(drift(n, 500.0, 0.03)),
        "SMH": series(drift(n, 200.0, 0.04)),
        "XLP": series(drift(n, 80.0, 0.02)),
        "SOXX": series(split_soxx(after=2)),
    }
    b = _measure(bars)
    rows = {r["key"]: r for r in b["groups"]}
    assert [p["symbol"] for p in b["price_breaks"]] == ["SOXX"]
    assert b["price_breaks"][0]["date"] == bdays(2)[0].isoformat()
    # Semis is measured on SMH alone: same 5-session return as SMH by itself, not a -70% blend
    semis = rows["semis"]
    assert semis["price_breaks"][0]["symbol"] == "SOXX"
    assert semis["state"] != "UNKNOWN"
    smh_only = _measure({k: v for k, v in bars.items() if k != "SOXX"})
    assert semis["r5"] == {r["key"]: r for r in smh_only["groups"]}["semis"]["r5"]
    assert semis["r5"] > -5
    # a group whose only member broke is UNKNOWN with the reason, never a number
    alone = rows["soxx_only"]
    assert alone["state"] == "UNKNOWN"
    assert "SOXX price history breaks on" in alone["reason_unknown"]
    assert "left out of its groups" in alone["reason_unknown"]
    assert alone.get("r5") is None
    # untouched groups carry no break field
    assert "price_breaks" not in rows["staples"]


def test_sectors_without_a_break_are_unchanged():
    n = 300
    bars = {
        "SPY": series(drift(n, 500.0, 0.03)),
        "SMH": series(drift(n, 200.0, 0.04)),
        "XLP": series(drift(n, 80.0, 0.02)),
        "SOXX": series(drift(n, 300.0, 0.05)),
    }
    b = _measure(bars)
    assert b["price_breaks"] == []
    assert all("price_breaks" not in r for r in b["groups"])
    assert {r["key"]: r for r in b["groups"]}["soxx_only"]["state"] != "UNKNOWN"
