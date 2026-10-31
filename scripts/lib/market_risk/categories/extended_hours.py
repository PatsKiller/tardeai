"""extended_hours category — premarket / after-hours index proxies and index heavyweights (plan §5.1, §5.14).

Worst index-proxy move versus the previous close over the last ``lookback_hours`` of extended-session quotes:
at or below ``warn_pct`` WARN, at or below ``stress_pct`` STRESS. Heavyweights down at least
``heavyweight_stress_pct`` are named as evidence (the 10-29 case: INTC -22%, AMZN -6% after the close while NQ
fell 1.6%). An opening-shock verdict in ``ctx.extras["opening_shock"]`` of ``panic_open`` forces STRESS with
``shock=True`` evidence, which scoring treats as a single-evaluation RED. No extended-session quotes → UNKNOWN.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "extended_hours"
ET = ZoneInfo("America/New_York")


def _gap_moves(ctx: EvalContext, cfg: dict[str, Any], proxies: list[str]) -> dict[str, dict[str, Any]]:
    """Overnight gap of each index proxy: today's 09:30 open vs the previous session's close, in % and in ATR units.
    Known from the open only (``session_opens`` never returns an open before 09:30 ET of its session)."""
    gc = cfg.get("gap_proxy") or {}
    if not gc.get("enabled", True) or not hasattr(ctx.reader, "session_opens"):
        return {}
    today = ctx.now.astimezone(ET).date()
    n_atr = int(gc.get("atr_sessions", 14))
    opens = {r["symbol"]: r for r in ctx.reader.session_opens(proxies, sessions=1, end=ctx.now)}
    bars: dict[str, list[dict[str, Any]]] = {}
    for r in ctx.reader.daily_bars(proxies, sessions=n_atr + 2, end=ctx.now):
        bars.setdefault(str(r["symbol"]), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for s in proxies:
        o = opens.get(s)
        if not o or date.fromisoformat(str(o["date"])) != today:
            continue
        prior = [b for b in bars.get(s, []) if date.fromisoformat(str(b["date"])) < today]
        if len(prior) < n_atr + 1:
            continue
        prev = float(prior[-1]["close"])
        trs = []
        for a, b in zip(prior[-n_atr - 1 : -1], prior[-n_atr:]):
            hi, lo, pc = float(b["high"]), float(b["low"]), float(a["close"])
            trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        atr_pct = 100.0 * (sum(trs) / len(trs)) / prev if prev else None
        gap = 100.0 * (float(o["open"]) - prev) / prev if prev else None
        if gap is None or not atr_pct:
            continue
        out[s] = {"gap_pct": gap, "gap_atr": gap / atr_pct, "as_of": o["as_of"], "prev_close": prev}
    return out


def _move(row: dict[str, Any]) -> float | None:
    try:
        price, prev = float(row["price"]), float(row["prev_close"])
    except (KeyError, TypeError, ValueError):
        return None
    return 100.0 * (price - prev) / prev if prev else None


def _latest(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if str(r.get("session") or "").lower() not in ("premarket", "afterhours", "extended", "pre", "post"):
            continue
        s = str(r.get("symbol") or "").upper()
        if s and (s not in out or str(r.get("as_of")) > str(out[s].get("as_of"))):
            out[s] = r
    return out


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy.get("extended_hours") or {}
    proxies = [str(s).upper() for s in cfg.get("index_proxies") or ["QQQ", "SPY"]]
    heavy = [str(s).upper() for s in cfg.get("heavyweights") or []]
    start = ctx.now - timedelta(hours=float(cfg.get("lookback_hours", 18)))
    latest = _latest(ctx.reader.quotes(proxies + heavy, start=start, end=ctx.now))
    shock = (ctx.extras or {}).get("opening_shock") or {}
    moves = {s: _move(latest[s]) for s in proxies if s in latest and _move(latest[s]) is not None}
    gaps = _gap_moves(ctx, cfg, proxies)
    if not moves and not shock.get("shock") and not gaps:
        return unknown(CATEGORY, ctx.now, "no extended-session quotes and no opening print for the index proxies")
    warn, stress = float(cfg.get("warn_pct", -0.75)), float(cfg.get("stress_pct", -1.5))
    worst_sym = min(moves, key=moves.get) if moves else None
    worst = moves[worst_sym] if worst_sym else 0.0
    evidence = [
        Evidence(
            label=f"{s} extended-session move vs previous close",
            value=round(m, 2),
            as_of=latest[s].get("as_of"),
            source="market_quotes",
            detail=f"{m:+.1f}%",
        )
        for s, m in sorted(moves.items(), key=lambda kv: kv[1])
    ]
    hw_cut = float(cfg.get("heavyweight_stress_pct", -8))
    big = []
    for s in heavy:
        m = _move(latest[s]) if s in latest else None
        if m is not None and m <= hw_cut:
            big.append(f"{s} {m:+.0f}%")
            evidence.append(
                Evidence(
                    label=f"{s} extended-session move",
                    value=round(m, 2),
                    as_of=latest[s].get("as_of"),
                    source="market_quotes",
                    detail=f"{m:+.1f}%",
                )
            )
    if shock.get("shock"):
        evidence.append(
            Evidence(
                label="opening_shock",
                value={"class": shock.get("class"), "shock": True},
                as_of=ctx.now.isoformat(),
                source="opening_shock",
                detail="panic open",
            )
        )
        state, score = "STRESS", 100.0
    elif worst <= stress:
        state, score = "STRESS", min(100.0, 75.0 + 25.0 * (worst - stress) / stress)
    elif worst <= warn:
        state, score = "WARN", 40.0 + 35.0 * (worst - warn) / (stress - warn)
    else:
        state, score = "CALM", max(0.0, 40.0 * worst / warn) if worst < 0 else 0.0
    gap_state = None
    if gaps:
        gc = cfg.get("gap_proxy") or {}
        gsym = min(gaps, key=lambda k: gaps[k]["gap_pct"])
        g = gaps[gsym]
        for s2, gv in sorted(gaps.items(), key=lambda kv: kv[1]["gap_pct"]):
            evidence.append(
                Evidence(
                    label=f"{s2} opening gap vs previous close",
                    value={"gap_pct": round(gv["gap_pct"], 2), "gap_atr": round(gv["gap_atr"], 2)},
                    as_of=gv["as_of"],
                    source="session_opens",
                    detail=f"{gv['gap_pct']:+.1f}% ({gv['gap_atr']:+.1f} ATR)",
                )
            )
        if g["gap_pct"] <= stress or g["gap_atr"] <= -float(gc.get("stress_atr", 1.5)):
            depth = max(g["gap_pct"] / stress, g["gap_atr"] / -float(gc.get("stress_atr", 1.5)))
            gap_state, gap_score = "STRESS", min(100.0, 75.0 + 25.0 * (depth - 1.0))
        elif g["gap_pct"] <= warn or g["gap_atr"] <= -float(gc.get("warn_atr", 0.75)):
            gap_state, gap_score = "WARN", 50.0
        else:
            gap_state, gap_score = "CALM", 0.0
        if not moves and not shock.get("shock") or (gap_score > score):
            state, score = gap_state, gap_score
            worst_sym, worst = gsym, g["gap_pct"]
    head = f"{worst_sym} {worst:+.1f}% extended" if worst_sym else "opening shock"
    if gap_state is not None and worst_sym in gaps and worst == gaps[worst_sym]["gap_pct"]:
        head = f"{worst_sym} opened {worst:+.1f}% ({gaps[worst_sym]['gap_atr']:+.1f} ATR) vs previous close"
    if big:
        head += " · " + ", ".join(big[:3])
    if shock.get("shock"):
        head = "PANIC OPEN · " + head
    observed = max(
        [str(latest[s].get("as_of")) for s in latest] + [str(g["as_of"]) for g in gaps.values()],
        default=ctx.now.isoformat(),
    )
    stale_h = float(cfg.get("stale_after_hours", 2))
    if gaps and not latest:
        stale_h = float((cfg.get("gap_proxy") or {}).get("stale_after_hours", 7))
    return CategoryObservation(
        category=CATEGORY,
        state=state,
        score=round(score, 1),
        observed_at=observed,
        headline=head,
        evidence=tuple(evidence),
        stale_after_hours=stale_h,
    )
