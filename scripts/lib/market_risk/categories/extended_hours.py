"""extended_hours category — premarket / after-hours index proxies and index heavyweights (plan §5.1, §5.14).

Worst index-proxy move versus the previous close over the last ``lookback_hours`` of extended-session quotes:
at or below ``warn_pct`` WARN, at or below ``stress_pct`` STRESS. Heavyweights down at least
``heavyweight_stress_pct`` are named as evidence (the 10-29 case: INTC -22%, AMZN -6% after the close while NQ
fell 1.6%). An opening-shock verdict in ``ctx.extras["opening_shock"]`` of ``panic_open`` forces STRESS with
``shock=True`` evidence, which scoring treats as a single-evaluation RED. No extended-session quotes → UNKNOWN.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

try:
    from lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "extended_hours"


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
    if not moves and not shock.get("shock"):
        return unknown(CATEGORY, ctx.now, "no extended-session quotes for the index proxies")
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
    head = f"{worst_sym} {worst:+.1f}% extended" if worst_sym else "opening shock"
    if big:
        head += " · " + ", ".join(big[:3])
    if shock.get("shock"):
        head = "PANIC OPEN · " + head
    observed = max((str(latest[s].get("as_of")) for s in latest), default=ctx.now.isoformat())
    return CategoryObservation(
        category=CATEGORY,
        state=state,
        score=round(score, 1),
        observed_at=observed,
        headline=head,
        evidence=tuple(evidence),
        stale_after_hours=float(cfg.get("stale_after_hours", 2)),
    )
