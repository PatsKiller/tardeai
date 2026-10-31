"""Sector and theme attribution, shock-type inputs and the heat-map payload (DSN-20261031-market-risk-engine, precision).

Operator 2026-10-31: "I would have wanted to be aware of which sectors got hit because consumer [staples] like Pfizer,
Walmart, and Procter & Gamble did not get affected." Every evaluation names the groups under stress, the groups holding
up, and whether money is rotating into defensives. Deterministic; no model. Thresholds live in
``config/market_risk_policy.yaml`` ``sectors:`` and are standard-score bands of each series against its OWN trailing
history (stated rule, not fitted to October): a group is STRESS when its 5-session return is at least ``stress_z``
standard deviations below its own 5-session-return mean AND it lags SPY by ``rs_stress_z`` standard deviations of its
own relative-return history; RESILIENT when it beats SPY by ``resilient_rs_z`` or rises while SPY falls.

Read only through ``ctx.reader.daily_bars``; a group with too little history is UNKNOWN, never zero. Advisory only
(``MBI_BEHAVIOR = 0``): the block carries returns, states and evidence, never a size, order, stop or weight.
"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import mean, pstdev
from typing import Any

from scripts.lib.market_risk import contract as c

STATE_TIER = {"STRESS": "RED", "WEAK": "YELLOW", "NEUTRAL": "NONE", "RESILIENT": "GREEN", "UNKNOWN": "UNKNOWN"}


def _closes(reader: Any, symbols: list[str], sessions: int, end: datetime) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for r in reader.daily_bars(symbols, sessions=sessions, end=end) or []:
        cl = r.get("close")
        if cl is None:
            continue
        out.setdefault(str(r["symbol"]), []).append((str(r["date"])[:10], float(cl)))
    for k in out:
        out[k].sort()
    return out


def _index(series: dict[str, list[tuple[str, float]]], members: list[str]) -> list[tuple[str, float]]:
    """Equal-weight index of members on the dates all members share, normalised to 1.0 at the first shared date."""
    have = [m for m in members if series.get(m)]
    if not have:
        return []
    dates = set.intersection(*({d for d, _ in series[m]} for m in have))
    if not dates:
        return []
    ordered = sorted(dates)
    look = {m: dict(series[m]) for m in have}
    base = {m: look[m][ordered[0]] for m in have}
    return [(d, mean(look[m][d] / base[m] for m in have if base[m])) for d in ordered]


def _ret(idx: list[tuple[str, float]], n: int, back: int = 0) -> float | None:
    if len(idx) <= n + back:
        return None
    a, b = idx[-1 - back - n][1], idx[-1 - back][1]
    return (b / a - 1.0) * 100.0 if a else None


def _hist_rets(idx: list[tuple[str, float]], n: int, window: int) -> list[float]:
    vals = [x[1] for x in idx]
    out = []
    for i in range(max(n, len(vals) - window), len(vals)):
        if i - n >= 0 and vals[i - n]:
            out.append((vals[i] / vals[i - n] - 1.0) * 100.0)
    return out


def _z(x: float | None, hist: list[float]) -> float | None:
    if x is None or len(hist) < 30:
        return None
    sd = pstdev(hist)
    return None if sd <= 0 else (x - mean(hist)) / sd


def _corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 5 or len(a) != len(b):
        return None
    ma, mb = mean(a), mean(b)
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return None if not va or not vb else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)


def _daily(idx: list[tuple[str, float]]) -> list[float]:
    v = [x[1] for x in idx]
    return [(v[i] / v[i - 1] - 1.0) for i in range(1, len(v)) if v[i - 1]]


def _avg_pairwise_corr(dailies: list[list[float]], win: int, back: int = 0) -> float | None:
    cut = [d[len(d) - win - back : len(d) - back] if back else d[-win:] for d in dailies if len(d) >= win + back]
    if len(cut) < 3:
        return None
    cs = [_corr(cut[i], cut[j]) for i in range(len(cut)) for j in range(i + 1, len(cut))]
    cs = [x for x in cs if x is not None]
    return mean(cs) if cs else None


def measure(ctx: c.EvalContext) -> dict[str, Any]:
    """The ``sectors`` block: per-group metrics and states, stressed/resilient/rotating lists, dispersion,
    cross-sector correlation and factor spreads, each with ``as_of``."""
    cfg = (ctx.policy or {}).get("sectors") or {}
    groups = cfg.get("groups") or []
    bench = str(cfg.get("benchmark") or "SPY")
    window = int(cfg.get("z_window_sessions") or 252)
    need = window + 30
    symbols = sorted({bench, *[s for g in groups for s in g.get("symbols") or []], *(cfg.get("factor_symbols") or [])})
    series = _closes(ctx.reader, symbols, need, ctx.now)
    b_idx = _index(series, [bench])
    b5 = _ret(b_idx, 5)
    b20 = _ret(b_idx, 20)
    b1 = _ret(b_idx, 1)
    as_of = b_idx[-1][0] if b_idx else None
    rows: list[dict[str, Any]] = []
    sector_dailies: list[list[float]] = []
    r5_sectors: list[float] = []
    r1_sectors: list[float] = []
    for g in groups:
        idx = _index(series, list(g.get("symbols") or []))
        row: dict[str, Any] = {
            "key": g["key"],
            "label": g["label"],
            "kind": g.get("kind", "sector"),
            "symbols": list(g.get("symbols") or []),
        }
        if len(idx) < 60 or b5 is None:
            row.update(state="UNKNOWN", tier="UNKNOWN", reason_unknown="insufficient history", as_of=as_of)
            rows.append(row)
            continue
        r1, r5, r20 = _ret(idx, 1), _ret(idx, 5), _ret(idx, 20)
        rs5 = None if r5 is None else r5 - b5
        rs20 = None if (r20 is None or b20 is None) else r20 - b20
        hist5 = _hist_rets(idx, 5, window)
        bhist5 = _hist_rets(b_idx, 5, window)
        k = min(len(hist5), len(bhist5))
        rs_hist = [x - y for x, y in zip(hist5[-k:], bhist5[-k:])]
        z5, zrs = _z(r5, hist5), _z(rs5, rs_hist)
        hist1, bhist1 = _hist_rets(idx, 1, window), _hist_rets(b_idx, 1, window)
        k1 = min(len(hist1), len(bhist1))
        rs1 = None if (r1 is None or b1 is None) else r1 - b1
        z1, zrs1 = _z(r1, hist1), _z(rs1, [x - y for x, y in zip(hist1[-k1:], bhist1[-k1:])])
        hi20 = max(x[1] for x in idx[-20:])
        dd20 = (idx[-1][1] / hi20 - 1.0) * 100.0 if hi20 else None
        state = "NEUTRAL"
        rs_t = float(cfg.get("rs_stress_z", -1.0))

        def _le(a: float | None, t: float) -> bool:
            return a is not None and a <= t

        if (_le(z5, float(cfg.get("stress_z", -1.5))) and _le(zrs, rs_t)) or (
            _le(z1, float(cfg.get("stress_z_1d", -2.0))) and _le(zrs1, rs_t)
        ):
            state = "STRESS"
        elif (_le(z5, float(cfg.get("weak_z", -1.0))) and _le(zrs, 0.0)) or (
            _le(z1, float(cfg.get("weak_z_1d", -1.5))) and _le(zrs1, 0.0)
        ):
            state = "WEAK"
        elif (
            (zrs is not None and zrs >= float(cfg.get("resilient_rs_z", 0.75)))
            or (b5 < 0 and r5 is not None and r5 >= 0)
            or (b1 is not None and b1 < 0 and r1 is not None and r1 >= 0 and zrs1 is not None and zrs1 >= 1.0)
        ):
            state = "RESILIENT"
        row.update(
            r1=_rnd(r1),
            r5=_rnd(r5),
            r20=_rnd(r20),
            rs1=_rnd(rs1),
            rs5=_rnd(rs5),
            rs20=_rnd(rs20),
            z1=_rnd(z1),
            zrs1=_rnd(zrs1),
            z5=_rnd(z5),
            zrs5=_rnd(zrs),
            dd20=_rnd(dd20),
            state=state,
            tier=STATE_TIER[state],
            as_of=idx[-1][0],
            evidence=f"{g['label']} {r1:+.1f}% 1d / {r5:+.1f}% 5d vs SPY {b1:+.1f}% / {b5:+.1f}%",
        )
        if g.get("kind") == "sector":
            sector_dailies.append(_daily(idx))
            if r5 is not None:
                r5_sectors.append(r5)
            if r1 is not None:
                r1_sectors.append(r1)
        rows.append(row)
    known = [r for r in rows if r["state"] != "UNKNOWN"]
    stressed = [r["label"] for r in known if r["state"] == "STRESS" and r["kind"] in ("sector", "theme")]
    weak = [r["label"] for r in known if r["state"] == "WEAK" and r["kind"] in ("sector", "theme")]
    resilient = [r["label"] for r in known if r["state"] == "RESILIENT" and r["kind"] == "sector"]
    by_key = {r["key"]: r for r in rows}
    defensive = by_key.get(str(cfg.get("defensive_key") or "defensive")) or {}
    growth_keys = set(cfg.get("growth_keys") or [])
    rotating = []
    if defensive.get("state") == "RESILIENT" and any(
        by_key.get(k, {}).get("state") in ("STRESS", "WEAK") for k in growth_keys
    ):
        rotating.append("into defensives (staples / healthcare / utilities) out of growth")
    # dispersion, cross-sector correlation (and its own z), factor spreads
    disp = pstdev(r5_sectors) if len(r5_sectors) >= 5 else None
    disp_hist: list[float] = []
    corr_now = _avg_pairwise_corr(sector_dailies, int(cfg.get("corr_window_sessions") or 10))
    corr_hist = [
        x
        for back in range(5, min(window, 250), 5)
        if (x := _avg_pairwise_corr(sector_dailies, int(cfg.get("corr_window_sessions") or 10), back)) is not None
    ]
    sec_idx = [_index(series, list(g.get("symbols") or [])) for g in groups if g.get("kind") == "sector"]
    for back in range(5, min(window, 250), 5):
        vals = [v for idx in sec_idx if (v := _ret(idx, 5, back)) is not None]
        if len(vals) >= 5:
            disp_hist.append(pstdev(vals))
    factors: dict[str, Any] = {}
    for name, (a, b) in (cfg.get("factor_pairs") or {}).items():
        ia, ib = _index(series, [a]), _index(series, [b])
        ra, rb = _ret(ia, 5), _ret(ib, 5)
        if ra is None or rb is None:
            factors[name] = {"state": "UNKNOWN", "reason_unknown": f"no bars for {a}/{b}"}
            continue
        ha, hb = _hist_rets(ia, 5, window), _hist_rets(ib, 5, window)
        k = min(len(ha), len(hb))
        spread_hist = [x - y for x, y in zip(ha[-k:], hb[-k:])]
        factors[name] = {"pair": [a, b], "spread5": _rnd(ra - rb), "z": _rnd(_z(ra - rb, spread_hist))}
    down = max(sum(1 for v in r5_sectors if v < 0), sum(1 for v in r1_sectors if v < 0))
    hit_sectors = [r for r in known if r["kind"] == "sector" and r["state"] in ("STRESS", "WEAK")]
    block = {
        "schema": "MarketRiskSectors@v1",
        "as_of": as_of,
        "benchmark": {"symbol": bench, "r1": _rnd(b1), "r5": _rnd(b5), "r20": _rnd(b20)},
        "groups": rows,
        "stressed": stressed,
        "weak": weak,
        "resilient": resilient,
        "rotating": rotating,
        "sectors_down": down,
        "sectors_measured": len(r5_sectors),
        "sectors_hit": len(hit_sectors),
        "dispersion": {"value": _rnd(disp), "z": _rnd(_z(disp, disp_hist))},
        "correlation": {"value": _rnd(corr_now), "z": _rnd(_z(corr_now, corr_hist))},
        "factors": factors,
        "defensive": {k: defensive.get(k) for k in ("state", "r5", "rs5")},
    }
    c.assert_no_behavior_fields(block)
    return block


def _rnd(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


def card_line(block: dict[str, Any] | None) -> str:
    """'Hit: Semis, Technology, AI basket · Holding: Staples, Healthcare, Utilities' — empty when nothing is known."""
    if not block:
        return ""
    hit = list(block.get("stressed") or []) + [f"{x} (weak)" for x in block.get("weak") or []]
    hold = list(block.get("resilient") or [])
    parts = []
    if hit:
        parts.append("Hit: " + ", ".join(hit))
    if hold:
        parts.append("Holding: " + ", ".join(hold))
    if block.get("rotating"):
        parts.append("Rotation " + block["rotating"][0])
    return " · ".join(parts)


def heatmap(block: dict[str, Any] | None, exposure: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Heat-map payload: one row per group with 1/5/20-day move, relative strength vs SPY, tier, state and — live only
    — the book's look-through exposure share to that group. Never written into repo fixtures."""
    out = []
    for r in (block or {}).get("groups") or []:
        row = {
            k: r.get(k) for k in ("key", "label", "kind", "r1", "r5", "r20", "rs5", "rs20", "state", "tier", "as_of")
        }
        if exposure is not None:
            row["book_exposure_share"] = exposure.get(r["key"])
        out.append(row)
    return out
