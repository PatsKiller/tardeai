"""Market-data categories of the Market Risk Engine (DSN-20261031-market-risk-engine P2-T1, P2-T5).

Synthetic fixtures shaped like the 2026-10-30 selloff RCA (public market numbers only, no portfolio data).
No network, no DB: a fixture DataReader serves the rows.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.lib.market_risk import correlations
from scripts.lib.market_risk.categories import cross_asset, macro_credit, options_flow, technical, volatility
from scripts.lib.market_risk.contract import EvalContext, assert_no_behavior_fields
from scripts.lib.market_risk.policy import load_policy

NOW = datetime(2026, 10, 29, 22, 0, tzinfo=timezone.utc)  # 18:00 ET, after the 10-29 close


def bdays(n: int, end: date = date(2026, 10, 29)) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


class Reader:
    def __init__(self, bars=None, fred=None, options=None):
        self._bars, self._fred, self._opt = bars or {}, fred or {}, options or []

    def daily_bars(self, symbols, *, sessions, end):
        rows = []
        for s in symbols:
            for d, c in (self._bars.get(s) or [])[-sessions:]:
                rows.append({"symbol": s, "date": d.isoformat(), "close": c})
        return rows

    def fred(self, series, *, observations, end):
        return [
            {"series_id": s, "date": d.isoformat(), "value": v}
            for s in series
            for d, v in (self._fred.get(s) or [])[-observations:]
        ]

    def option_snapshots(self, symbols, *, sessions, end):
        return [r for r in self._opt if r["symbol"] in symbols]

    def quotes(self, *a, **k):
        return []

    def regime_indicators(self, **k):
        return []

    def sector_states(self, **k):
        return []

    def earnings_calendar(self, **k):
        return []

    def macro_calendar(self, **k):
        return []


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def ctx(policy, reader, now=NOW):
    return EvalContext(now=now, reader=reader, policy=policy, session="afterhours")


def flat(n, level, drift=0.0005, wiggle=0.004, seed=1.0):
    days = bdays(n)
    return [(d, level * math.exp(drift * i + wiggle * math.sin(i * seed))) for i, d in enumerate(days)]


def selloff_bars():
    days = bdays(260)
    # QQQ: steady climb, high 725.59 on 10-21, slide, retest 725.40 on 10-28, -2.7% on 10-29.
    qqq = [600 * math.exp(0.0007 * i) for i in range(len(days))]
    scale = 725.59 / qqq[days.index(date(2026, 10, 21))]
    qqq = [c * scale for c in qqq]
    i21 = days.index(date(2026, 10, 21))
    for k, v in zip(range(i21 + 1, len(days)), [712.0, 704.0, 709.0, 716.0, 725.40, 705.81]):
        qqq[k] = v
    # SMH: 8 straight down days into the end and -15% month to date.
    smh = [500 * math.exp(0.0006 * i) for i in range(len(days))]
    sep_end = max(i for i, d in enumerate(days) if d.month == 9)
    base = smh[sep_end]
    for k in range(sep_end + 1, len(days)):
        smh[k] = base * (1 - 0.15 * (k - sep_end) / (len(days) - 1 - sep_end))
    bars = {"QQQ": list(zip(days, qqq)), "SMH": list(zip(days, smh))}
    # VIX week low into the drop, 16.87 -> 16.59 while QQQ -2.7%.
    vix = [18.0 + 0.3 * math.sin(i) for i in range(len(days))]
    vix[-2], vix[-1] = 16.87, 16.59
    bars["^VIX"] = list(zip(days, vix))
    bars["SPY"] = flat(260, 650)
    return bars


def calm_bars():
    days = bdays(260)
    q = [600 * math.exp(0.0007 * i + 0.002 * math.sin(i)) for i in range(len(days))]
    q[-1] = max(q) * 1.001
    return {
        "QQQ": list(zip(days, q)),
        "SMH": flat(260, 500, wiggle=0.002),
        "SPY": flat(260, 650, wiggle=0.002),
        "^VIX": [(d, 14.0 + 0.2 * math.sin(i)) for i, d in enumerate(days)],
    }


# ── technical ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_technical_selloff_fires_retest_streak_and_semis(policy):
    o = technical.evaluate(ctx(policy, Reader(bars=selloff_bars())))
    keys = " ".join(e.detail for e in o.evidence)
    assert "QQQ failed retest of 725.59" in keys
    assert "SMH" in keys and "straight down sessions" in keys
    assert "month to date" in keys
    assert o.state in ("WARN", "STRESS") and o.score >= policy["technical"]["warn_score"]
    assert_no_behavior_fields(o.to_dict())


def test_technical_calm_is_calm(policy):
    o = technical.evaluate(ctx(policy, Reader(bars=calm_bars())))
    assert o.state == "CALM", o.headline


def test_technical_unknown_when_missing_or_stale(policy):
    assert technical.evaluate(ctx(policy, Reader())).state == "UNKNOWN"
    later = NOW + timedelta(days=10)
    o = technical.evaluate(ctx(policy, Reader(bars=selloff_bars()), now=later))
    assert o.state == "UNKNOWN" and o.score is None and "stale" in o.reason_unknown


# ── volatility ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_volatility_complacency_divergence_10_29(policy):
    o = volatility.evaluate(ctx(policy, Reader(bars=selloff_bars())))
    assert any("while VIX" in e.detail for e in o.evidence), o.headline
    # term structure, VVIX, SKEW absent -> UNKNOWN sub-signals, never zero
    unk = {e.label for e in o.evidence if e.value == "UNKNOWN"}
    assert {"VIX9D", "VIX3M", "VVIX", "SKEW"} <= unk
    assert o.state == "WARN" and o.score == policy["volatility"]["points"]["divergence"]


def test_volatility_inversion_and_level(policy):
    bars = selloff_bars()
    days = [d for d, _ in bars["^VIX"]]
    bars["^VIX"] = [(d, 20.0) for d in days[:-6]] + [(d, 21.0) for d in days[-6:-1]] + [(days[-1], 27.0)]
    bars["^VIX3M"] = [(d, 24.0) for d in days]
    bars["^VIX9D"] = [(d, 29.0) for d in days]
    o = volatility.evaluate(ctx(policy, Reader(bars=bars)))
    det = " ".join(e.detail for e in o.evidence)
    assert "inverted" in det and "VIX9D 29.0 > VIX 27.0" in det
    assert o.state == "STRESS"


def test_volatility_calm_and_unknown(policy):
    assert volatility.evaluate(ctx(policy, Reader(bars=calm_bars()))).state == "CALM"
    assert volatility.evaluate(ctx(policy, Reader(bars={"QQQ": calm_bars()["QQQ"]}))).state == "UNKNOWN"


# ── options flow wrapper ───────────────────────────────────────────────────────────────────────────────────────
def _opt_rows(today_vol):
    rows = []
    days = bdays(21)
    for i, d in enumerate(days[:-1]):
        for s, oi, vol in (("QQQ", 1.38, 0.96), ("SPY", 1.0, 1.0)):
            rows.append(
                {
                    "symbol": s,
                    "as_of": f"{d.isoformat()}T14:00:00+00:00",
                    "pc_oi_ratio": oi + 0.01 * (i % 3),
                    "pc_vol_ratio": vol + 0.01 * (i % 3),
                    "underlying_price": 700.0,
                }
            )
    d = days[-1].isoformat()
    rows.append(
        {
            "symbol": "QQQ",
            "as_of": f"{d}T14:00:00+00:00",
            "pc_oi_ratio": 2.856,
            "pc_vol_ratio": today_vol,
            "underlying_price": 712.0,
        }
    )
    rows.append(
        {
            "symbol": "SPY",
            "as_of": f"{d}T14:00:00+00:00",
            "pc_oi_ratio": 1.0,
            "pc_vol_ratio": 1.0,
            "underlying_price": 650.0,
        }
    )
    return rows


def test_options_flow_stress_10_29(policy):
    o = options_flow.evaluate(ctx(policy, Reader(options=_opt_rows(3.31))))
    assert o.state == "STRESS" and o.score == policy["options_flow_category"]["score"]["STRESS"]
    assert "QQQ" in o.headline


def test_options_flow_unknown_without_history(policy):
    rows = [r for r in _opt_rows(3.31) if r["as_of"].startswith("2026-10-29")]
    o = options_flow.evaluate(ctx(policy, Reader(options=rows)))
    assert o.state == "UNKNOWN" and o.score is None


# ── macro / credit ─────────────────────────────────────────────────────────────────────────────────────────────
def _fred(hy_end=3.40, ust=5.19):
    days = bdays(300, date(2026, 10, 28))
    hy = [3.0 + 0.01 * math.sin(i) for i in range(len(days))]
    for k in range(1, 6):
        hy[-k] = hy_end - 0.04 * (k - 1)
    hy[-6] = 3.18
    return {
        "BAMLH0A0HYM2": list(zip(days, hy)),
        "DGS10": [(d, ust) for d in days],
        "T10Y2Y": [(d, 0.5) for d in days],
        "DCOILWTICO": [(d, 96.0 if i < len(days) - 10 else 111.0) for i, d in enumerate(days)],
        "DTWEXBGS": [(d, 120.0) for d in days],
    }


def test_macro_credit_widening(policy):
    o = macro_credit.evaluate(ctx(policy, Reader(fred=_fred())))
    det = " ".join(e.detail for e in o.evidence)
    assert "HY OAS +22bp in 5 sessions" in det and "10y 5.19%" in det and "WTI +16% in 20 sessions" in det
    assert o.state in ("WARN", "STRESS")


def test_macro_credit_calm_and_unknown(policy):
    calm = _fred(hy_end=3.0, ust=4.0)
    calm["BAMLH0A0HYM2"] = [(d, 3.0) for d, _ in calm["BAMLH0A0HYM2"]]
    calm["DCOILWTICO"] = [(d, 80.0) for d, _ in calm["DCOILWTICO"]]
    assert macro_credit.evaluate(ctx(policy, Reader(fred=calm))).state == "CALM"
    assert macro_credit.evaluate(ctx(policy, Reader())).state == "UNKNOWN"


# ── correlations (P2-T5 positive control) and cross-asset ──────────────────────────────────────────────────────
def _pair_bars(flip: bool):
    days = bdays(280)
    spy, vix = [650.0], [18.0]
    for i in range(1, len(days)):
        r = 0.01 * math.sin(i * 1.7) + 0.003 * math.cos(i * 0.3)
        spy.append(spy[-1] * math.exp(r))
        k = -3.0 if (not flip or i < len(days) - 25) else 3.0  # inverse relationship, flipped for the last 25 days
        vix.append(vix[-1] * math.exp(k * r))
    return {"SPY": list(zip(days, spy)), "^VIX": list(zip(days, vix))}


def test_correlation_sign_flip_is_anomaly_and_restore_is_normal(policy):
    cfg = {**policy["correlations"], "pairs": [["SPY", "^VIX"]]}
    md = __import__("scripts.lib.market_risk.categories._marketdata", fromlist=["x"])

    def run(flip):
        by = md.closes_by_symbol(Reader(bars=_pair_bars(flip)).daily_bars(["SPY", "^VIX"], sessions=400, end=NOW))
        return correlations.anomalies(by, cfg)[0]

    hot = run(True)
    assert hot["status"] == "ANOMALY" and hot["sign_flip"] and hot["current"] > 0 > hot["mean"]
    cold = run(False)
    assert cold["status"] == "NORMAL" and not cold["sign_flip"]


def test_correlation_unknown_when_short(policy):
    cfg = {**policy["correlations"], "pairs": [["SPY", "TLT"]]}
    assert correlations.anomalies({}, cfg)[0]["status"] == "UNKNOWN"


def test_cross_asset_reports_anomaly_and_unknown_pairs(policy):
    o = cross_asset.evaluate(ctx(policy, Reader(bars=_pair_bars(True))))
    det = " ".join(e.detail for e in o.evidence)
    assert "correlation anomal" in det and "SPY~^VIX" in det
    assert any(e.value == "UNKNOWN" and "TLT" in e.label for e in o.evidence)
    assert o.state in ("CALM", "WARN") and o.score == policy["cross_asset"]["points"]["anomaly"]
    assert cross_asset.evaluate(ctx(policy, Reader(bars=_pair_bars(False)))).state == "CALM"
    assert cross_asset.evaluate(ctx(policy, Reader())).state == "UNKNOWN"
