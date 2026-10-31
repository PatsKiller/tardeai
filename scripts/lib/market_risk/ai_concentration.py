"""AI concentration risk (DSN-20261031-market-risk-engine §5.7, P2-T6).

Two deterministic outputs, consumed by categories owned elsewhere:

* ``technical_signal`` — basket participation (share above its 20/50-session average), basket relative strength vs
  RSP/SPY over ``rs_sessions``, and basket drawdown. Participation below ``participation_stress`` or relative
  strength at or below ``rs_stress_pct`` is STRESS. The technical category calls this; this module never scores
  the composite itself.
* ``earnings_sensitivity`` — index-cap share of basket members reporting in the next 1/3/5 sessions, optionally
  times each name's implied move. A share at or above ``event.ai_sensitivity_stress_share`` within
  ``event.ai_sensitivity_window_sessions`` sets the event category to STRESS (categories/event.py).

Inputs come only through the ``DataReader`` the engine passes in. Advisory only (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from scripts.lib.market_risk import event_calendar
from scripts.lib.market_risk.contract import EvalContext, Evidence, assert_no_behavior_fields

_RANK = {"UNKNOWN": -1, "CALM": 0, "IMPROVING": 0, "WARN": 1, "STRESS": 2}


def basket(cfg: dict) -> list[str]:
    syms = list(cfg.get("basket") or [])
    if cfg.get("include_optional"):
        syms += [s for s in cfg.get("optional") or [] if s not in syms]
    return [s.upper() for s in syms]


def _series(rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        try:
            c = float(r["close"])
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(str(r["symbol"]).upper(), []).append((str(r.get("date") or r.get("as_of"))[:10], c))
    for s in out.values():
        s.sort()
    return out


def _sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _ret(closes: list[float], n: int) -> float | None:
    if len(closes) <= n or closes[-n - 1] == 0:
        return None
    return (closes[-1] / closes[-n - 1] - 1.0) * 100.0


def participation(series: dict[str, list[tuple[str, float]]], names: list[str]) -> dict[str, Any]:
    a20 = a50 = n20 = n50 = 0
    for s in names:
        closes = [c for _, c in series.get(s, [])]
        m20, m50 = _sma(closes, 20), _sma(closes, 50)
        if m20 is not None:
            n20 += 1
            a20 += closes[-1] > m20
        if m50 is not None:
            n50 += 1
            a50 += closes[-1] > m50
    return {
        "above_20_share": round(a20 / n20, 4) if n20 else None,
        "above_50_share": round(a50 / n50, 4) if n50 else None,
        "measured": n20,
        "of": len(names),
    }


def basket_return(series: dict, names: list[str], n: int, weights: dict[str, float] | None = None) -> float | None:
    num = den = 0.0
    for s in names:
        r = _ret([c for _, c in series.get(s, [])], n)
        if r is None:
            continue
        w = float((weights or {}).get(s, 1.0)) or 1.0
        num += w * r
        den += w
    return num / den if den else None


def drawdown_pct(series: dict, names: list[str]) -> float | None:
    """Equal-weight basket index drawdown from its high over the bars supplied (negative percent)."""
    common = None
    for s in names:
        ds = {d for d, _ in series.get(s, [])}
        common = ds if common is None else common & ds
    if not common:
        return None
    dates = sorted(common)
    idx = []
    for d in dates:
        vals = [dict(series[s])[d] / series[s][0][1] for s in names if s in series]
        idx.append(sum(vals) / len(vals))
    return round((idx[-1] / max(idx) - 1.0) * 100.0, 2)


def technical_signal(series: dict, cfg: dict, weights: dict[str, float] | None = None) -> dict[str, Any]:
    names = basket(cfg)
    part = participation(series, names)
    rs = {}
    b_ret = basket_return(series, names, int(cfg["rs_sessions"]), weights)
    for bm in cfg.get("benchmarks") or []:
        r = _ret([c for _, c in series.get(bm.upper(), [])], int(cfg["rs_sessions"]))
        rs[bm.upper()] = round(b_ret - r, 2) if (b_ret is not None and r is not None) else None
    worst_rs = min((v for v in rs.values() if v is not None), default=None)
    p = part["above_20_share"]
    if p is None and worst_rs is None:
        return {"state": "UNKNOWN", "score": None, "reason_unknown": "no basket bars", "participation": part, "rs": rs}
    state = "CALM"
    if (p is not None and p < cfg["participation_stress"]) or (
        worst_rs is not None and worst_rs <= cfg["rs_stress_pct"]
    ):
        state = "STRESS"
    elif (p is not None and p < cfg["participation_warn"]) or (worst_rs is not None and worst_rs <= cfg["rs_warn_pct"]):
        state = "WARN"
    calm, floor = float(cfg["participation_calm"]), 0.0
    p_score = 100.0 * max(0.0, min(1.0, (calm - p) / (calm - floor))) if p is not None else 0.0
    r_score = 100.0 * max(0.0, min(1.0, worst_rs / float(cfg["rs_full_pct"]))) if worst_rs is not None else 0.0
    dd = drawdown_pct(series, names)
    newest = max((d for s in names for d, _ in series.get(s, [])[-1:]), default=None)
    out = {
        "state": state,
        "score": round(max(p_score, r_score), 1),
        "participation": part,
        "rs_vs": rs,
        "drawdown_pct": dd,
        "observed_at": newest,
        "headline": (
            f"AI basket: {round(100 * p) if p is not None else '?'}% above 20-day · RS {worst_rs:+.1f} pts vs benchmark"
            if worst_rs is not None
            else f"AI basket: {round(100 * p) if p is not None else '?'}% above 20-day"
        ),
    }
    assert_no_behavior_fields(out)
    return out


def earnings_sensitivity(
    now: datetime,
    earnings_rows: list[dict],
    weights: dict[str, float] | None,
    cfg: dict,
    event_cfg: dict,
    implied_moves: dict[str, float] | None = None,
) -> dict[str, Any]:
    if not weights:
        return {"state": "UNKNOWN", "reason_unknown": "index weights unavailable"}
    names = basket(cfg)
    by_window = {}
    for n in event_cfg.get("windows_sessions", [1, 3, 5]):
        r = event_calendar.earnings_share(now, earnings_rows, weights, int(n), event_cfg, symbols=names)
        if implied_moves:
            r["move_weighted"] = round(sum(w * float(implied_moves.get(s, 0.0)) for s, w in r["reporters"].items()), 6)
        by_window[str(n)] = r
    n_key = int(event_cfg["ai_sensitivity_window_sessions"])
    drive = by_window.get(str(n_key)) or event_calendar.earnings_share(
        now, earnings_rows, weights, n_key, event_cfg, symbols=names
    )
    stress = drive["share"] >= float(event_cfg["ai_sensitivity_stress_share"])
    return {
        "state": "STRESS" if stress else "CALM",
        "window_sessions": n_key,
        "share": drive["share"],
        "reporters": drive["reporters"],
        "by_window": by_window,
    }


def evaluate(ctx: EvalContext) -> dict[str, Any]:
    """Full module output for the engine (technical feed + earnings sensitivity)."""
    cfg = ctx.policy["ai_concentration"]
    names = basket(cfg) + [b.upper() for b in cfg.get("benchmarks") or []]
    rows = ctx.reader.daily_bars(names, sessions=int(cfg["lookback_sessions"]), end=ctx.now)
    weights = (ctx.extras.get("index_weights") or {}).get("weights")
    series = _series(rows)
    tech = technical_signal(series, cfg, weights)
    earn = ctx.reader.earnings_calendar(
        start=ctx.now, end=ctx.now + timedelta(days=int(cfg.get("earnings_lookahead_days", 10)))
    )
    sens = earnings_sensitivity(ctx.now, earn, weights, cfg, ctx.policy["event"], ctx.extras.get("implied_moves"))
    out = {"technical": tech, "earnings_sensitivity": sens}
    assert_no_behavior_fields(out)
    return out


def evidence_for(tech: dict) -> tuple[Evidence, ...]:
    p = tech.get("participation") or {}
    ev = [
        Evidence(
            "AI basket share above 20-day average",
            p.get("above_20_share"),
            tech.get("observed_at"),
            "daily_bars",
            f"{p.get('measured')}/{p.get('of')} names measured",
        )
    ]
    for bm, v in (tech.get("rs_vs") or {}).items():
        ev.append(Evidence(f"AI basket 20-session return minus {bm}", v, tech.get("observed_at"), "daily_bars"))
    return tuple(ev)


def worse(a: str, b: str) -> str:
    return a if _RANK.get(a, -1) >= _RANK.get(b, -1) else b
