"""Volatility category: VIX level and jump, complacency divergence, term structure, VVIX/SKEW, realized vs implied.

A missing term-structure, VVIX or SKEW series is reported as an UNKNOWN sub-signal in the evidence (never zero);
the whole category is UNKNOWN only when VIX itself is missing or stale. RCA: on 10-29 QQQ fell 2.7% while VIX fell
to 16.59 (complacency divergence); VIX had sat at the week's low into two mega-cap earnings nights.
"""

from __future__ import annotations

import math

from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "volatility"
SOURCE = "market_ohlcv_bars"


def _realized_pct(closes: list[float], n: int) -> float | None:
    if len(closes) < n + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy[CATEGORY]
    term = cfg["term_symbols"]
    syms = [cfg["vix_symbol"], cfg["index_symbol"], cfg["realized_symbol"], *term.values()]
    md_rows = list(ctx.reader.daily_bars(syms, sessions=int(cfg["history_sessions"]), end=ctx.now))
    by = md.closes_by_symbol(md_rows)
    vix = by.get(cfg["vix_symbol"]) or []
    if len(vix) < 6:
        return unknown(CATEGORY, ctx.now, "VIX history missing")
    vt, v = vix[-1]
    if md.stale(vt, ctx.now, cfg["stale_after_hours"], ctx.policy.get("decay")):
        return unknown(CATEGORY, ctx.now, f"VIX stale (newest {md.iso(vt)})")
    asof = md.iso(vt)
    fired: list[tuple[str, Evidence]] = []
    vix_rows = [r for r in md_rows if str(r.get("symbol") or "").upper() == str(cfg["vix_symbol"]).upper()]
    vix_source = str((vix_rows[-1] if vix_rows else {}).get("source") or SOURCE)  # honest label (review B6)
    context: list[Evidence] = [Evidence("VIX close", v, asof, vix_source, f"VIX {v:.2f}")]

    if v >= float(cfg["vix_stress"]):
        fired.append(("vix_stress", Evidence("VIX level", v, asof, vix_source, f"VIX {v:.1f} ≥ {cfg['vix_stress']}")))
    elif v >= float(cfg["vix_warn"]):
        fired.append(("vix_warn", Evidence("VIX level", v, asof, vix_source, f"VIX {v:.1f} ≥ {cfg['vix_warn']}")))
    ch5 = md.pct(v, vix[-6][1])
    if ch5 >= float(cfg["vix_5d_change_pct"]):
        fired.append(
            ("vix_jump", Evidence("VIX 5-day change", round(ch5, 1), asof, vix_source, f"VIX +{ch5:.0f}% in 5d"))
        )

    idx = by.get(cfg["index_symbol"]) or []
    if len(idx) >= 2 and len(vix) >= 2 and idx[-1][0].date() == vt.date():
        di, dv = md.pct(idx[-1][1], idx[-2][1]), md.pct(v, vix[-2][1])
        if di <= float(cfg["divergence_index_drop_pct"]) and dv <= float(cfg["divergence_vix_max_change_pct"]):
            fired.append(
                (
                    "divergence",
                    Evidence(
                        "complacency divergence",
                        round(di, 2),
                        asof,
                        SOURCE,
                        f"{cfg['index_symbol']} {di:+.1f}% while VIX {dv:+.1f}%",
                    ),
                )
            )
    else:
        context.append(
            Evidence("complacency divergence", "UNKNOWN", asof, SOURCE, "index close for the VIX day missing")
        )

    def last_same_day(key: str) -> float | None:
        s = by.get(term[key]) or []
        return s[-1][1] if s and s[-1][0].date() == vt.date() else None

    v9, v3, vv, sk = (last_same_day(k) for k in ("vix9d", "vix3m", "vvix", "skew"))
    for name, val in (("VIX9D", v9), ("VIX3M", v3), ("VVIX", vv), ("SKEW", sk)):
        context.append(
            Evidence(
                name,
                val if val is not None else "UNKNOWN",
                asof,
                SOURCE,
                f"{name} {val:.2f}" if val is not None else f"{name} not measured",
            )
        )
    if v9 is not None and v9 > v:
        fired.append(
            (
                "term_inversion_front",
                Evidence("VIX9D above VIX", round(v9 - v, 2), asof, SOURCE, f"VIX9D {v9:.1f} > VIX {v:.1f}"),
            )
        )
    if v3 is not None and v > v3:
        fired.append(
            (
                "term_inversion_back",
                Evidence("VIX above VIX3M", round(v - v3, 2), asof, SOURCE, f"VIX {v:.1f} > VIX3M {v3:.1f} (inverted)"),
            )
        )
    if vv is not None and vv >= float(cfg["vvix_warn"]):
        fired.append(("vvix", Evidence("VVIX level", vv, asof, SOURCE, f"VVIX {vv:.0f}")))
    if sk is not None and sk >= float(cfg["skew_warn"]):
        fired.append(("skew", Evidence("SKEW level", sk, asof, SOURCE, f"SKEW {sk:.0f}")))

    rs = by.get(cfg["realized_symbol"]) or []
    rv = _realized_pct([c for _, c in rs], int(cfg["realized_window"]))
    if rv is None:
        context.append(Evidence("realized volatility", "UNKNOWN", asof, SOURCE, "not enough history"))
    else:
        context.append(
            Evidence("realized volatility", round(rv, 1), asof, SOURCE, f"{cfg['realized_symbol']} RV {rv:.1f}")
        )
        if rv > v * float(cfg["realized_over_implied"]):
            fired.append(
                (
                    "realized_over_implied",
                    Evidence(
                        "realized above implied",
                        round(rv, 1),
                        asof,
                        SOURCE,
                        f"{cfg['realized_symbol']} 10d RV {rv:.1f} > VIX {v:.1f}",
                    ),
                )
            )
    imp = cfg.get("improving") or {}
    improving: list[Evidence] = []
    nb = int(imp.get("change_sessions", 10))
    if imp and len(vix) > max(nb, 20):
        ch = md.pct(v, vix[-nb - 1][1])
        m20 = sum(x for _, x in vix[-20:]) / 20
        if ch <= float(imp["vix_change_pct"]) and v < m20 and v < float(cfg["vix_warn"]):
            improving.append(
                Evidence("VIX falling", round(ch, 1), asof, SOURCE, f"VIX {ch:+.0f}% in {nb} sessions to {v:.1f}")
            )
    return md.observation(CATEGORY, cfg, fired, context, vt, headline_prefix="Volatility", improving=improving)
