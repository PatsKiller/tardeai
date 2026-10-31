"""Breadth category from the data the host already owns (DSN-20261031 §5.1, §5.5).

Today: ``sector_momentum_state`` rows through ``DataReader.sector_states`` — the equal-vs-cap style pair (RSP−SPY),
leadership sector states (XLK, SMH) with their member breadth, and the share of sector ETFs WEAKENING/LAGGING.
Market-wide breadth (new highs/lows, % above 20/50/200-day) arrives from ``market_breadth_daily`` once that store and
writer exist (P1-T5); until then it is passed in ``ctx.extras['market_breadth']`` or reported UNKNOWN, never zero.
"""

from __future__ import annotations

from scripts.lib.market_risk import breadth_proxy
from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.contract import (
    CategoryObservation,
    EvalContext,
    Evidence,
    assert_no_behavior_fields,
    unknown,
)

CATEGORY = "breadth"


def _latest(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        k = str(r.get("etf") or "")
        if k and (k not in out or str(r.get("as_of")) > str(out[k].get("as_of"))):
            out[k] = r
    return out


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy["breadth"]
    try:
        rows = ctx.reader.sector_states(end=ctx.now)
    except Exception as exc:
        return unknown(CATEGORY, ctx.now, f"sector_states read failed: {type(exc).__name__}: {exc}"[:200])
    latest = _latest(rows)
    proxy, proxy_why, proxy_ev, proxy_newest, thrust = _proxy(ctx, cfg)
    if not latest and proxy is None:
        return unknown(CATEGORY, ctx.now, "no sector_momentum_state rows and no sector-ETF daily bars for the proxy")
    pts = 0.0
    ev: list[Evidence] = []
    parts: list[str] = []

    style = latest.get(cfg["style_key"])
    if style:
        st = str(style.get("state") or "")
        pts += float(cfg["style_points"].get(st, 0))
        ev.append(Evidence("RSP−SPY (equal vs cap)", st, str(style.get("as_of")), "sector_momentum_state"))
        if st in cfg["deteriorating_states"]:
            parts.append(f"RSP−SPY {st}")
    else:
        ev.append(Evidence("RSP−SPY (equal vs cap)", "not measured", None, "sector_momentum_state"))

    lead_pts = 0.0
    for etf in cfg["leadership_etfs"]:
        r = latest.get(etf)
        if not r:
            continue
        st = str(r.get("state") or "")
        lead_pts += float(cfg["leadership_points"].get(st, 0))
        b = r.get("breadth_pct")
        if b is not None and float(b) < float(cfg["weak_breadth_pct"]):
            lead_pts += float(cfg["weak_breadth_points"])
        ev.append(
            Evidence(
                f"{etf} sector state",
                st,
                str(r.get("as_of")),
                "sector_momentum_state",
                f"breadth {b}%" if b is not None else "breadth not measured",
            )
        )
        if st in cfg["deteriorating_states"]:
            parts.append(f"{etf} {st}" + (f" {round(float(b))}% breadth" if b is not None else ""))
    pts += min(float(cfg["leadership_max_points"]), lead_pts)

    sectors = [r for k, r in latest.items() if not k.startswith("STYLE:")]
    if sectors:
        weak = sum(1 for r in sectors if str(r.get("state")) in cfg["deteriorating_states"])
        share = weak / len(sectors)
        pts += share * float(cfg["deteriorating_share_points_full"])
        ev.append(
            Evidence(
                "sector ETFs WEAKENING or LAGGING",
                f"{weak}/{len(sectors)}",
                max(str(r.get("as_of")) for r in sectors),
                "sector_momentum_state",
            )
        )

    mb = ctx.extras.get("market_breadth")
    if mb:
        ev.append(Evidence("market breadth", mb.get("summary"), mb.get("as_of"), mb.get("source", "market_breadth")))
        pts += float(mb.get("points", 0))
    elif proxy is None:
        ev.append(
            Evidence(
                "market-wide breadth (new lows, % above DMA)",
                "not measured",
                None,
                "market_breadth_daily",
                "store not built yet (P1-T5)",
            )
        )

    # Sector-state points and the ETF breadth proxy measure overlapping things: take the stronger, never the sum.
    sector_score = round(min(100.0, pts), 1) if latest else None
    score = max(x for x in (sector_score, proxy) if x is not None)
    if proxy is not None and (sector_score is None or proxy >= sector_score):
        parts = proxy_why or parts
    ev.extend(proxy_ev)
    state = "STRESS" if score >= cfg["stress_score"] else "WARN" if score >= cfg["warn_score"] else "CALM"
    if state == "CALM" and thrust:
        state = "IMPROVING"
        parts = [thrust]
    observed = max(
        [str(r.get("as_of")) for r in latest.values()] + ([proxy_newest] if proxy_newest else []),
        default=ctx.now.isoformat(),
    )
    obs = CategoryObservation(
        category=CATEGORY,
        state=state,
        score=score,
        observed_at=observed,
        headline="Breadth: " + (" · ".join(parts) if parts else "no deterioration"),
        evidence=tuple(ev),
        stale_after_hours=float(cfg["stale_after_hours"]),
    )
    assert_no_behavior_fields(obs.to_dict())
    return obs


def _proxy(ctx: EvalContext, cfg: dict) -> tuple[float | None, list[str], list[Evidence], str | None, str | None]:
    """The sector-ETF breadth proxy (breadth_proxy.py) from as-of-correct daily bars; (None, ...) when too few ETFs."""
    pc = cfg.get("proxy") or {}
    if not pc.get("enabled", True):
        return None, [], [], None, None
    universe = list(pc["universe"])
    try:
        rows = ctx.reader.daily_bars(universe + ["RSP", "SPY"], sessions=int(pc["history_sessions"]), end=ctx.now)
    except Exception as exc:  # reported as evidence, the category degrades to sector states / UNKNOWN
        return (
            None,
            [],
            [Evidence("breadth proxy", "UNKNOWN", None, "daily_bars", f"read failed: {exc}"[:160])],
            None,
            None,
        )
    by = md.closes_by_symbol(rows)
    newest = max((s[-1][0] for s in by.values() if s), default=None)
    if newest is None or md.stale(newest, ctx.now, float(pc["stale_after_hours"])):
        return None, [], [], None, None
    closes = {s: [c for _, c in by.get(s, [])] for s in universe if by.get(s)}
    style = {k: [c for _, c in by.get(k, [])] for k in ("RSP", "SPY")}
    m = breadth_proxy.measure(closes, style, pc)
    if m is None:
        return None, [], [], None, None
    sc, why = breadth_proxy.score(m, pc)
    asof = md.iso(newest)
    ev = [
        Evidence(
            "sector-ETF breadth proxy",
            {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()},
            asof,
            "daily_bars:sector_spdrs",
            f"{round(100 * (m['pct_above_50'] or 0))}% above 50-day, "
            f"{round(100 * m['pct_at_low'])}% at 52w lows, McClellan "
            + (f"{m['mcclellan']:+.0f}" if m["mcclellan"] is not None else "n/a"),
        )
    ]
    return sc, why, ev, asof, breadth_proxy.improving(m, pc)
