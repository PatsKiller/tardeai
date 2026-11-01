"""Durable leadership-turn detector (DSN-20261031-market-risk-engine, rotation advisor).

Operator 2026-10-31, verbatim: "And on a larger note, if stuff is turning for the long term, I should have advisement of
what I should be getting into".

Deterministic; no model. For every sector and theme group in ``config/market_risk_policy.yaml`` ``sectors.groups`` it
separates a multi-week change of leadership from a bounce, using only price and volume:

* relative strength vs SPY over 20 / 60 / 120 sessions (sign of the relative trend) and its persistence (share of the
  window spent above the relative-strength line's own 20-session average);
* the group's own trend (above its 50- and 200-day averages);
* breadth inside the group (members above their 50-day average) and new-high participation (members within 5% of a
  52-week high) where the group has more than one member;
* volume confirmation (up-day volume over down-day volume);
* the macro backdrop the group has historically led under (rates, dollar, credit), from policy.

Classes: ``LEADERSHIP_CONFIRMED`` (durable), ``LEADERSHIP_EMERGING`` (watch), ``LEADERSHIP_FADING``, ``BOUNCE_ONLY``,
``NEUTRAL``, ``UNKNOWN`` (too little history: never zero). The rule is stated in the policy block and fixed before the
backtest. Advisory only (``MBI_BEHAVIOR = 0``): the block carries states and evidence, never a size, order, price, stop
or weight.
"""

from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any, Optional

from scripts.lib.market_risk import contract as c

CLASSES = ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING", "LEADERSHIP_FADING", "BOUNCE_ONLY", "NEUTRAL", "UNKNOWN")
MACRO_SYMBOLS = ("TLT", "UUP", "HYG")


def _cfg(policy: dict[str, Any]) -> dict[str, Any]:
    return dict((policy or {}).get("leadership") or {})


def _groups(policy: dict[str, Any]) -> list[dict[str, Any]]:
    kinds = set(_cfg(policy).get("candidate_groups_kinds") or ["sector", "theme"])
    return [g for g in ((policy or {}).get("sectors") or {}).get("groups") or [] if g.get("kind") in kinds]


# --------------------------------------------------------------------------- panel (aligned series)


def build_panel(
    bars: dict[str, list[tuple[str, float, Optional[float]]]], groups: list[dict[str, Any]], benchmark: str = "SPY"
) -> dict[str, Any]:
    """Align every series on the benchmark's dates. ``bars[sym]`` is a date-sorted list of (date, close, volume).
    Returns {"dates": [...], "bench": [...], "sym": {sym: (closes, volumes)}, "groups": {key: {...}}} where a
    group's index is the equal-weight mean of its members normalised at the first shared date."""
    bench = bars.get(benchmark) or []
    dates = [d for d, _, _ in bench]
    look = {s: {d: (cl, v) for d, cl, v in rows} for s, rows in bars.items()}
    sym: dict[str, tuple[list[Optional[float]], list[Optional[float]]]] = {}
    for s, m in look.items():
        sym[s] = ([m.get(d, (None, None))[0] for d in dates], [m.get(d, (None, None))[1] for d in dates])
    out_groups: dict[str, Any] = {}
    for g in groups:
        members = [m for m in g.get("symbols") or [] if m in sym]
        if not members:
            out_groups[g["key"]] = {"label": g.get("label"), "members": [], "index": [], "volume": []}
            continue
        first = {}
        for m in members:
            cl = sym[m][0]
            first[m] = next((i for i, x in enumerate(cl) if x), None)
        start = max((i for i in first.values() if i is not None), default=None)
        idx: list[Optional[float]] = []
        vol: list[Optional[float]] = []
        for i in range(len(dates)):
            if start is None or i < start:
                idx.append(None)
                vol.append(None)
                continue
            vals = [sym[m][0][i] / sym[m][0][start] for m in members if sym[m][0][i] and sym[m][0][start]]
            idx.append(mean(vals) if len(vals) == len(members) else None)
            vs = [sym[m][1][i] for m in members if sym[m][1][i] is not None]
            vol.append(sum(vs) if vs else None)
        out_groups[g["key"]] = {"label": g.get("label"), "members": members, "index": idx, "volume": vol}
    return {"dates": dates, "bench": [cl for _, cl, _ in bench], "sym": sym, "groups": out_groups}


def _sma(xs: list[Optional[float]], n: int, i: int) -> Optional[float]:
    if i - n + 1 < 0:
        return None
    w = xs[i - n + 1 : i + 1]
    if any(x is None for x in w):
        return None
    return sum(w) / n  # type: ignore[arg-type]


def _ret(xs: list[Optional[float]], i: int, n: int) -> Optional[float]:
    if i - n < 0 or xs[i] is None or xs[i - n] in (None, 0):
        return None
    return xs[i] / xs[i - n] - 1.0  # type: ignore[operator]


def _macro_dir(panel: dict[str, Any], i: int, n: int = 60) -> dict[str, Optional[str]]:
    tlt = (panel["sym"].get("TLT") or ([], []))[0]
    uup = (panel["sym"].get("UUP") or ([], []))[0]
    hyg = (panel["sym"].get("HYG") or ([], []))[0]
    r_tlt = _ret(tlt, i, n) if tlt else None
    r_uup = _ret(uup, i, n) if uup else None
    ratio = [h / t if (h and t) else None for h, t in zip(hyg, tlt)] if hyg and tlt else []
    r_cr = _ret(ratio, i, n) if ratio else None
    return {
        "rates": None if r_tlt is None else ("falling" if r_tlt > 0 else "rising"),  # TLT up = yields down
        "dollar": None if r_uup is None else ("rising" if r_uup > 0 else "falling"),
        "credit": None if r_cr is None else ("improving" if r_cr > 0 else "worsening"),
    }


def features_at(panel: dict[str, Any], key: str, i: int, cfg: dict[str, Any]) -> dict[str, Any]:
    g = panel["groups"].get(key) or {}
    idx = g.get("index") or []
    bench = panel["bench"]
    horizons = [int(h) for h in cfg.get("horizons") or [20, 60, 120]]
    if not idx or i >= len(idx) or idx[i] is None:
        return {"available": False}
    rs = [(a / b) if (a is not None and b) else None for a, b in zip(idx, bench)]
    sma_n = int(cfg.get("rs_sma_sessions") or 20)
    rs_ret = {h: _ret(rs, i, h) for h in horizons}
    pers: dict[int, Optional[float]] = {}
    for h in horizons:
        hits, tot = 0, 0
        for j in range(i - h + 1, i + 1):
            if j < 0 or rs[j] is None:
                continue
            s = _sma(rs, sma_n, j)
            if s is None:
                continue
            tot += 1
            hits += rs[j] > s  # type: ignore[operator]
        pers[h] = (hits / tot) if tot >= max(5, h // 2) else None
    s50, s200 = _sma(idx, 50, i), _sma(idx, 200, i)
    uptrend = None if (s50 is None or s200 is None) else bool(idx[i] > s50 and idx[i] > s200)  # type: ignore[operator]
    members = g.get("members") or []
    breadth = new_high = None
    if len(members) > 1:
        above, near, cnt = 0, 0, 0
        for m in members:
            cl = panel["sym"][m][0]
            s = _sma(cl, 50, i)
            if s is None or cl[i] is None:
                continue
            cnt += 1
            above += cl[i] > s
            hi = max((x for x in cl[max(0, i - 251) : i + 1] if x is not None), default=None)
            near += bool(hi and cl[i] >= hi * (1 - float(cfg.get("new_high_pct") or 0.05)))
        if cnt:
            breadth, new_high = above / cnt, near / cnt
    vol = g.get("volume") or []
    vn = int(cfg.get("volume_sessions") or 20)
    up = dn = 0.0
    seen = 0
    for j in range(i - vn + 1, i + 1):
        if j < 1 or vol[j] is None or idx[j] is None or idx[j - 1] is None:
            continue
        seen += 1
        if idx[j] > idx[j - 1]:  # type: ignore[operator]
            up += vol[j]  # type: ignore[operator]
        else:
            dn += vol[j]  # type: ignore[operator]
    volume_ratio = (up / dn) if (seen >= vn // 2 and dn > 0) else None
    return {
        "available": True,
        "rs_ret": rs_ret,
        "persistence": pers,
        "uptrend": uptrend,
        "breadth": breadth,
        "new_high": new_high,
        "volume_ratio": volume_ratio,
        "history": i + 1,
    }


def classify_features(f: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, float, list[str]]:
    """(class, confidence 0..1, reasons). The rule is the policy's stated rule; see the module docstring."""
    if not f.get("available") or f.get("history", 0) < int(cfg.get("min_history_sessions") or 260):
        return "UNKNOWN", 0.0, ["not enough history"]
    h20, h60, h120 = (int(h) for h in (cfg.get("horizons") or [20, 60, 120]))
    r, p = f["rs_ret"], f["persistence"]
    if any(r.get(h) is None for h in (h20, h60, h120)):
        return "UNKNOWN", 0.0, ["relative-strength history incomplete"]
    pmin = float(cfg.get("persistence_min") or 0.6)
    fmax = float(cfg.get("fading_persistence_max") or 0.4)
    bmin = float(cfg.get("breadth_min") or 0.6)
    pos = {h: r[h] > 0 for h in (h20, h60, h120)}
    breadth_ok = f.get("breadth") is None or f["breadth"] >= bmin
    reasons = [
        f"relative to SPY: {r[h20]:+.1%} over {h20}, {r[h60]:+.1%} over {h60}, {r[h120]:+.1%} over {h120} sessions",
    ]
    if p.get(h60) is not None:
        reasons.append(f"above its relative-strength average {p[h60]:.0%} of the last {h60} sessions")
    if f.get("uptrend") is not None:
        reasons.append("in an uptrend (above 50- and 200-day)" if f["uptrend"] else "below its 50- or 200-day average")
    if f.get("breadth") is not None:
        reasons.append(f"{f['breadth']:.0%} of members above their 50-day")
    if f.get("volume_ratio") is not None:
        reasons.append(f"up-day volume {f['volume_ratio']:.2f}x down-day volume")
    support = [
        pos[h20],
        pos[h60],
        pos[h120],
        (p.get(h60) or 0) >= pmin,
        bool(f.get("uptrend")),
        breadth_ok,
        (f.get("volume_ratio") or 0) > 1.0,
    ]
    if pos[h60] and pos[h120] and (p.get(h60) or 0) >= pmin and f.get("uptrend") and breadth_ok:
        return "LEADERSHIP_CONFIRMED", round(sum(support) / len(support), 2), reasons
    if pos[h120] and not pos[h20] and (p.get(h20) if p.get(h20) is not None else 1.0) <= fmax:
        return "LEADERSHIP_FADING", round(1 - sum(support) / len(support), 2), reasons
    if pos[h20] and (p.get(h20) or 0) >= pmin and pos[h60]:
        return "LEADERSHIP_EMERGING", round(sum(support) / len(support), 2), reasons
    if pos[h20] and not pos[h60] and not pos[h120]:
        return "BOUNCE_ONLY", round(1 - sum(support[1:]) / len(support[1:]), 2), reasons
    return "NEUTRAL", 0.0, reasons


def horizon_label(cls: str, macro_aligned: Optional[bool], cfg: dict[str, Any]) -> Optional[str]:
    if cls == "LEADERSHIP_CONFIRMED":
        if macro_aligned or (macro_aligned is None and not cfg.get("strategic_requires_macro", True)):
            return "strategic"
        return "tactical"
    if cls == "LEADERSHIP_EMERGING":
        return "tactical"
    return None


def macro_alignment(key: str, macro: dict[str, Optional[str]], cfg: dict[str, Any]) -> Optional[bool]:
    pref = (cfg.get("macro_preference") or {}).get(key) or {}
    if not pref:
        return None
    seen = [macro.get(k) for k in pref]
    if any(s is None for s in seen):
        return None
    return all(macro.get(k) == v for k, v in pref.items())


def evaluate_panel(panel: dict[str, Any], i: int, policy: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(policy)
    macro = _macro_dir(panel, i)
    out: dict[str, Any] = {}
    for g in _groups(policy):
        key = g["key"]
        f = features_at(panel, key, i, cfg)
        cls, conf, reasons = classify_features(f, cfg)
        aligned = macro_alignment(key, macro, cfg)
        rec = {
            "key": key,
            "label": g.get("label"),
            "kind": g.get("kind"),
            "symbols": list(g.get("symbols") or []),
            "class": cls,
            "confidence": conf,
            "horizon": horizon_label(cls, aligned, cfg),
            "macro_aligned": aligned,
            "evidence": reasons,
            "features": {
                k: f.get(k) for k in ("rs_ret", "persistence", "uptrend", "breadth", "new_high", "volume_ratio")
            }
            if f.get("available")
            else {},
        }
        out[key] = rec
    return {"macro": macro, "groups": out}


# --------------------------------------------------------------------------- production entry point


def _bars_from_reader(reader: Any, symbols: list[str], sessions: int, end: datetime) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in reader.daily_bars(symbols, sessions=sessions, end=end) or []:
        if r.get("close") is None:
            continue
        v = r.get("volume")
        out.setdefault(str(r["symbol"]), []).append(
            (str(r["date"])[:10], float(r["close"]), float(v) if v is not None else None)
        )
    for k in out:
        out[k].sort()
    return out


def measure(ctx: c.EvalContext) -> dict[str, Any]:
    """The ``leadership`` block for the snapshot, the CIO facts and the rotation card."""
    policy = ctx.policy
    cfg = _cfg(policy)
    groups = _groups(policy)
    bench = str(cfg.get("benchmark") or "SPY")
    symbols = sorted({bench, *MACRO_SYMBOLS, *(s for g in groups for s in g.get("symbols") or [])})
    bars = _bars_from_reader(ctx.reader, symbols, int(cfg.get("min_history_sessions") or 260) + 140, ctx.now)
    if not bars.get(bench):
        return {"state": "UNKNOWN", "reason_unknown": f"no daily bars for {bench}", "as_of": ctx.now.isoformat()}
    panel = build_panel(bars, groups, bench)
    i = len(panel["dates"]) - 1
    block = evaluate_panel(panel, i, policy)
    block.update({"state": "evaluated", "as_of": panel["dates"][i], "benchmark": bench})
    c.assert_no_behavior_fields(block)
    return block


def summary(block: Optional[dict[str, Any]]) -> dict[str, list[str]]:
    """{class: [labels]} for the card and Ask-the-CIO."""
    out: dict[str, list[str]] = {}
    for g in ((block or {}).get("groups") or {}).values():
        out.setdefault(g["class"], []).append(str(g.get("label") or g["key"]))
    return out
