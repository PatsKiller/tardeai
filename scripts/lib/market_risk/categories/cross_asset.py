"""Cross-asset category: correlation anomalies (scripts/lib/market_risk/correlations.py), high-yield credit ETF
weakness and flight to safety (equities down while Treasuries rally). Thresholds: policy keys ``cross_asset`` and
``correlations``.
"""

from __future__ import annotations

from scripts.lib.market_risk import correlations
from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "cross_asset"
SOURCE = "market_ohlcv_bars"


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg, ccfg = ctx.policy[CATEGORY], ctx.policy["correlations"]
    syms = sorted({s for pair in ccfg["pairs"] for s in pair} | {"SPY", "TLT", "HYG"})
    by = md.closes_by_symbol(ctx.reader.daily_bars(syms, sessions=int(cfg["history_sessions"]), end=ctx.now))
    spy = by.get("SPY") or []
    if len(spy) < 6:
        return unknown(CATEGORY, ctx.now, "SPY history missing")
    newest = spy[-1][0]
    if md.stale(newest, ctx.now, cfg["stale_after_hours"]):
        return unknown(CATEGORY, ctx.now, f"SPY bars stale (newest {md.iso(newest)})")
    asof = md.iso(newest)
    fired: list[tuple[str, Evidence]] = []
    context: list[Evidence] = []
    rows = correlations.anomalies(by, ccfg)
    anom = [r for r in rows if r["status"] == "ANOMALY"]
    for r in rows:
        if r["status"] == "UNKNOWN":
            context.append(Evidence(f"correlation {r['pair']}", "UNKNOWN", None, SOURCE, f"{r['pair']} {r['reason']}"))
        else:
            context.append(
                Evidence(
                    f"correlation {r['pair']}",
                    r["current"],
                    r["as_of"],
                    SOURCE,
                    f"{r['pair']} {r['current']:+.2f} (mean {r['mean']:+.2f}, z {r['z']:+.1f})",
                )
            )
    if anom:
        worst = max(anom, key=lambda r: abs(r["z"]))
        why = "sign flip" if worst["sign_flip"] else f"z {worst['z']:+.1f}"
        fired.append(
            (
                "anomaly",
                Evidence(
                    "correlation anomaly",
                    len(anom),
                    worst["as_of"],
                    SOURCE,
                    f"{len(anom)} correlation anomal{'y' if len(anom) == 1 else 'ies'}; {worst['pair']} {worst['current']:+.2f} ({why})",
                ),
            )
        )
    hyg = by.get("HYG") or []
    if len(hyg) >= 6:
        p = md.pct(hyg[-1][1], hyg[-6][1])
        if p <= float(cfg["hyg_5d_pct"]):
            fired.append(
                (
                    "hyg_drop",
                    Evidence(
                        "HYG 5-session change", round(p, 2), md.iso(hyg[-1][0]), SOURCE, f"HYG {p:.1f}% in 5 sessions"
                    ),
                )
            )
    tlt = by.get("TLT") or []
    if len(tlt) >= 6:
        ps, pt = md.pct(spy[-1][1], spy[-6][1]), md.pct(tlt[-1][1], tlt[-6][1])
        if ps <= float(cfg["flight_to_safety_spy_5d_pct"]) and pt >= float(cfg["flight_to_safety_tlt_5d_pct"]):
            fired.append(
                (
                    "flight_to_safety",
                    Evidence(
                        "flight to safety",
                        round(pt - ps, 2),
                        asof,
                        SOURCE,
                        f"SPY {ps:.1f}% vs TLT {pt:+.1f}% in 5 sessions",
                    ),
                )
            )
    return md.observation(CATEGORY, cfg, fired, context, newest, headline_prefix="Cross-asset")
