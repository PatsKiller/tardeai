"""Seasonal category: a low-weight prior from scripts/lib/cio_seasonality_engine.py (DSN-20261031 §5.1).

It can never by itself raise the category above WARN: the cap is enforced here, not only by policy numbers.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from scripts.lib.cio_seasonality_engine import build_seasonality_context
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, assert_no_behavior_fields

ET = ZoneInfo("America/New_York")

CATEGORY = "seasonal"
MAX_STATE = "WARN"


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy["seasonal"]
    pts_cfg = cfg["points"]
    # the calendar is New York's: at 20:38 ET on Oct 31 the UTC date is already November (review of #2415 round 2)
    s = build_seasonality_context(ctx.now.astimezone(ET))
    m, cyc, tags = s["month"], s["presidential_cycle"], set(s["calendar_effects"])
    hits: list[tuple[str, float]] = []
    if m["hypothesis_bucket"].startswith("historically_weaker"):
        hits.append(("weak_month", pts_cfg.get("weak_month", 0)))
    if m["worst_six_months_window"]:
        hits.append(("worst_six_months", pts_cfg.get("worst_six_months", 0)))
    if cyc["cycle_label"] == "midterm_year":
        hits.append(("midterm_year", pts_cfg.get("midterm_year", 0)))
    for tag in ("options_expiration_week", "quarter_end_window", "turn_of_month_late"):
        if tag in tags:
            hits.append((tag, pts_cfg.get(tag, 0)))
    score = round(min(float(cfg["max_score"]), sum(float(p) for _, p in hits)), 1)
    state = "WARN" if score >= float(cfg["warn_score"]) else "CALM"
    assert state in ("CALM", MAX_STATE)  # seasonal never reaches STRESS on its own
    obs = CategoryObservation(
        category=CATEGORY,
        state=state,
        score=score,
        observed_at=s["as_of"],
        headline=f"Seasonal prior {round(score)}: {m['month_name']} {cyc['cycle_label'].replace('_', ' ')}"
        + (f" · {', '.join(sorted(tags))}" if tags else ""),
        evidence=tuple(Evidence(k, p, s["as_of"], "cio_seasonality_engine") for k, p in hits),
        stale_after_hours=float(cfg["stale_after_hours"]),
    )
    assert_no_behavior_fields(obs.to_dict())
    return obs
