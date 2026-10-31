"""Macro / credit category from FRED (HY OAS, 10-year, 2s10s, WTI, broad dollar).

Reads a 400-observation window per series so changes and z-scores can be computed (P1-T3 widens the ingest; until
then a short history makes the z sub-signal UNKNOWN, not zero). Thresholds: policy key ``macro_credit``. RCA: HY OAS
3.18 -> 3.40 (10-15..10-22), DGS10 5.19% (10-14), WTI 96 -> 110 (10-14..10-19).
"""

from __future__ import annotations

from statistics import mean, pstdev

from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "macro_credit"


def _chg(series: list[tuple], n: int) -> float | None:
    return series[-1][1] - series[-1 - n][1] if len(series) > n else None


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy[CATEGORY]
    ids = cfg["series"]
    by = md.series_by_id(ctx.reader.fred(list(ids.values()), observations=int(cfg["observations"]), end=ctx.now))
    s = {k: by.get(v) or [] for k, v in ids.items()}
    fresh = {k: v for k, v in s.items() if v and not md.stale(v[-1][0], ctx.now, cfg["stale_after_hours"])}
    if "hy_oas" not in fresh and "ust10" not in fresh:
        return unknown(CATEGORY, ctx.now, "HY OAS and 10-year both missing or stale")
    newest = max(v[-1][0] for v in fresh.values())
    fired: list[tuple[str, Evidence]] = []
    ctxev: list[Evidence] = []

    def src(k: str) -> str:
        return f"fred_economic_series:{ids[k]}"

    for k in ids:
        if k not in fresh:
            ctxev.append(
                Evidence(ids[k], "UNKNOWN", md.iso(s[k][-1][0]) if s[k] else None, src(k), f"{ids[k]} missing or stale")
            )
        else:
            ctxev.append(
                Evidence(ids[k], fresh[k][-1][1], md.iso(fresh[k][-1][0]), src(k), f"{ids[k]} {fresh[k][-1][1]:.2f}")
            )

    hy = fresh.get("hy_oas")
    if hy:
        a = md.iso(hy[-1][0])
        c5, c20 = _chg(hy, 5), _chg(hy, 20)
        if c5 is not None and c5 * 100 >= float(cfg["hy_oas_5d_bp"]):
            fired.append(
                (
                    "hy_oas_5d",
                    Evidence(
                        "HY OAS 5-session change",
                        round(c5 * 100),
                        a,
                        src("hy_oas"),
                        f"HY OAS +{c5 * 100:.0f}bp in 5 sessions to {hy[-1][1]:.2f}",
                    ),
                )
            )
        if c20 is not None and c20 * 100 >= float(cfg["hy_oas_20d_bp"]):
            fired.append(
                (
                    "hy_oas_20d",
                    Evidence(
                        "HY OAS 20-session change",
                        round(c20 * 100),
                        a,
                        src("hy_oas"),
                        f"HY OAS +{c20 * 100:.0f}bp in 20 sessions",
                    ),
                )
            )
        hist = [hy[i][1] - hy[i - 20][1] for i in range(20, len(hy))]
        if len(hist) >= 60 and c20 is not None:
            sd = pstdev(hist[-252:])
            z = (c20 - mean(hist[-252:])) / sd if sd else 0.0
            if z >= float(cfg["hy_oas_z"]):
                fired.append(
                    (
                        "hy_oas_z",
                        Evidence(
                            "HY OAS 20-session change z", round(z, 2), a, src("hy_oas"), f"HY OAS widening z {z:.1f}"
                        ),
                    )
                )
        else:
            ctxev.append(Evidence("HY OAS z-score", "UNKNOWN", a, src("hy_oas"), "history under 80 observations"))
    t = fresh.get("ust10")
    if t:
        a = md.iso(t[-1][0])
        if t[-1][1] >= float(cfg["ust10_level"]):
            fired.append(("ust10_level", Evidence("10-year yield", t[-1][1], a, src("ust10"), f"10y {t[-1][1]:.2f}%")))
        c = _chg(t, 20)
        if c is not None and abs(c) * 100 >= float(cfg["ust10_20d_bp"]):
            fired.append(
                (
                    "ust10_move",
                    Evidence(
                        "10-year 20-session move",
                        round(c * 100),
                        a,
                        src("ust10"),
                        f"10y {c * 100:+.0f}bp in 20 sessions",
                    ),
                )
            )
    cv = fresh.get("curve")
    if cv:
        c = _chg(cv, 20)
        if c is not None and abs(c) * 100 >= float(cfg["curve_20d_bp"]):
            fired.append(
                (
                    "curve_move",
                    Evidence(
                        "2s10s 20-session move",
                        round(c * 100),
                        md.iso(cv[-1][0]),
                        src("curve"),
                        f"2s10s {c * 100:+.0f}bp in 20 sessions",
                    ),
                )
            )
    for key, thr, label in (("wti", "wti_20d_pct", "WTI"), ("dxy", "dxy_20d_pct", "Dollar")):
        x = fresh.get(key)
        if x and len(x) > 20:
            p = md.pct(x[-1][1], x[-21][1])
            if p >= float(cfg[thr]):
                fired.append(
                    (
                        key,
                        Evidence(
                            f"{label} 20-session change",
                            round(p, 1),
                            md.iso(x[-1][0]),
                            src(key),
                            f"{label} +{p:.0f}% in 20 sessions",
                        ),
                    )
                )
    return md.observation(
        CATEGORY,
        cfg,
        fired,
        ctxev,
        newest,
        headline_prefix="Macro/credit",
        improving=_credit_improving(ctx, cfg, fresh),
    )


def _credit_improving(ctx: EvalContext, cfg: dict, fresh: dict) -> list[Evidence]:
    """Design §5.2 Green input "improving credit": HY OAS down at least ``hy_oas_20d_bp`` in 20 observations; where the
    spread history is absent (FRED serves it from 2023-10 only), HYG up ``hyg_20d_pct`` in 20 sessions above its 50-day."""
    imp = cfg.get("improving") or {}
    if not imp:
        return []
    hy = fresh.get("hy_oas")
    if hy and len(hy) > 20:
        c20 = _chg(hy, 20)
        if c20 is not None and c20 * 100 <= -float(imp["hy_oas_20d_bp"]):
            return [
                Evidence(
                    "HY OAS tightening",
                    round(c20 * 100),
                    md.iso(hy[-1][0]),
                    f"fred_economic_series:{cfg['series']['hy_oas']}",
                    f"HY OAS {c20 * 100:+.0f}bp in 20 sessions",
                )
            ]
        return []
    bars = md.closes_by_symbol(ctx.reader.daily_bars([imp["proxy_symbol"]], sessions=60, end=ctx.now))
    s = bars.get(imp["proxy_symbol"]) or []
    if len(s) < 51 or md.stale(s[-1][0], ctx.now, cfg["stale_after_hours"]):
        return []
    closes = [c for _, c in s]
    r20 = md.pct(closes[-1], closes[-21])
    if r20 >= float(imp["hyg_20d_pct"]) and closes[-1] > sum(closes[-50:]) / 50:
        return [
            Evidence(
                "high-yield bonds rallying",
                round(r20, 1),
                md.iso(s[-1][0]),
                "daily_bars",
                f"{imp['proxy_symbol']} {r20:+.1f}% in 20 sessions, above its 50-day",
            )
        ]
    return []
