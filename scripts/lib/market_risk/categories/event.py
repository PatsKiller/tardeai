"""Event category: event concentration + AI-basket earnings sensitivity (DSN-20261031 §5.1, §5.7; P1-T6, P2-T6)."""

from __future__ import annotations

from datetime import timedelta

from scripts.lib.market_risk import ai_concentration, event_calendar
from scripts.lib.market_risk.contract import (
    CategoryObservation,
    EvalContext,
    Evidence,
    assert_no_behavior_fields,
    unknown,
)

CATEGORY = "event"


def _weights(ctx: EvalContext) -> tuple[dict[str, float] | None, str | None]:
    w = ctx.extras.get("index_weights") or {}
    return (w.get("weights") or None), w.get("as_of")


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy["event"]
    try:
        earn = ctx.reader.earnings_calendar(start=ctx.now - timedelta(days=1), end=ctx.now + timedelta(days=10))
        macro = ctx.reader.macro_calendar(start=ctx.now - timedelta(days=1), end=ctx.now + timedelta(days=10))
    except Exception as exc:  # reader outage -> UNKNOWN with the reason, never a silent zero
        return unknown(CATEGORY, ctx.now, f"calendar read failed: {type(exc).__name__}: {exc}"[:200])
    weights, w_as_of = _weights(ctx)
    conc = event_calendar.evaluate_concentration(ctx.now, earn, macro, weights, cfg)
    sens = ai_concentration.earnings_sensitivity(
        ctx.now, earn, weights, ctx.policy["ai_concentration"], cfg, ctx.extras.get("implied_moves")
    )
    score = float(conc["event_concentration_score"])
    state = "STRESS" if score >= cfg["stress_score"] else "WARN" if score >= cfg["warn_score"] else "CALM"
    if sens.get("state") == "STRESS":
        state = "STRESS"
        score = max(score, float(cfg["ai_sensitivity_stress_score"]))

    parts = []
    e3 = (conc.get("earnings") or {}).get(str(cfg["earnings_window_sessions"]))
    if e3 and e3["reporters"]:
        parts.append(f"{' + '.join(list(e3['reporters'])[:4])} report ≈ {round(100 * e3['share'])}% of index cap")
    elif conc.get("earnings_unknown"):
        parts.append("earnings weights unavailable")
    for m in conc["macro"][:2]:
        parts.append(f"{m['name']} {m['date'][5:]}{' ' + m['time_et'] if m.get('time_et') else ''}")
    for t in conc["calendar"][:2]:
        parts.append(f"{t['tag'].replace('_', ' ')} {t['date'][5:]}")
    headline = (
        f"Event concentration {round(score)}: " + "; ".join(parts) if parts else f"Event concentration {round(score)}"
    )

    ev = [
        Evidence(
            "event_concentration_score",
            conc["event_concentration_score"],
            conc["as_of"],
            "event_calendar",
            str(conc["points"]),
        )
    ]
    if e3:
        ev.append(
            Evidence(
                f"index-cap share reporting in {cfg['earnings_window_sessions']} sessions",
                e3["share"],
                w_as_of,
                "earnings_calendar+index_weights",
                ", ".join(e3["reporters"]),
            )
        )
    else:
        ev.append(
            Evidence(
                "index-cap share reporting", "not measured", None, "index_weights", conc.get("earnings_unknown") or ""
            )
        )
    ev.append(
        Evidence(
            f"AI-basket cap share reporting in {cfg['ai_sensitivity_window_sessions']} sessions",
            sens.get("share", "not measured"),
            w_as_of,
            "earnings_calendar+index_weights",
            sens.get("state", ""),
        )
    )
    for m in conc["macro"]:
        ev.append(Evidence("scheduled macro release", m["event"], m["date"], "macro_calendar", m.get("time_et") or ""))
    obs = CategoryObservation(
        category=CATEGORY,
        state=state,
        score=round(score, 1),
        observed_at=ctx.now.isoformat(),
        headline=headline,
        evidence=tuple(ev),
        stale_after_hours=float(cfg["stale_after_hours"]),
    )
    assert_no_behavior_fields(obs.to_dict())
    return obs
