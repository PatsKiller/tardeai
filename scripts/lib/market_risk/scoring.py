"""Composite score, tier, hysteresis, confidence decay and portfolio uplift (plan §5.2, §5.9, §5.11, §5.13).

Deterministic and model-free. Every number comes from ``config/market_risk_policy.yaml`` (keys ``weights``,
``tiers``, ``hysteresis``, ``decay``). The composite is the weighted mean of the KNOWN, decayed category scores, so
each category's point contribution is ``weight * score * decay / sum(known weights)`` and the contributions sum to
the score exactly (``explain.attribute`` relies on this). UNKNOWN categories are excluded and reported as lost
``coverage``; they are never zero. Advisory only: nothing here sizes, orders or stops (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib.market_risk import contract as c

ET = ZoneInfo("America/New_York")
SEVERITY = {t: i for i, t in enumerate(c.TIERS)}  # GREEN 0 < NONE 1 < BLUE 2 < YELLOW 3 < ORANGE 4 < RED 5
CONFIRMING_STATES = ("WARN", "STRESS")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def decay_weight(obs: c.CategoryObservation, now: datetime, policy: dict) -> tuple[float, float | None]:
    """(weight, age_hours). Weight 0 means stale beyond stale_after: the category becomes UNKNOWN."""
    cfg = policy["decay"]
    at = _parse(obs.observed_at)
    if at is None:
        return 0.0, None
    age = max(0.0, (now - at).total_seconds() / 3600.0)
    stale_after = obs.stale_after_hours if obs.stale_after_hours is not None else cfg["default_stale_after_hours"]
    if age > float(stale_after):
        return 0.0, age
    for step in cfg["steps"]:
        if age <= float(step["max_age_hours"]):
            return float(step["weight"]), age
    return float(cfg["steps"][-1]["weight"]), age


def _effective(observations: list[c.CategoryObservation], now: datetime, policy: dict) -> list[dict[str, Any]]:
    out = []
    for o in observations:
        w_decay, age = decay_weight(o, now, policy) if o.state != "UNKNOWN" else (0.0, None)
        if o.state != "UNKNOWN" and w_decay == 0.0:
            o = replace(o, state="UNKNOWN", score=None, reason_unknown=f"stale: {age:.0f}h old" if age else "no time")
        out.append(
            {"obs": o, "decay": w_decay, "age_hours": age, "weight": float(policy["weights"].get(o.category, 0))}
        )
    return out


def _raw_tier(score: float | None, eff: list[dict], policy: dict) -> tuple[str, dict[str, Any]]:
    tiers = policy["tiers"]
    confirm_min = float(policy["decay"]["confirm_min_weight"])
    known = [e for e in eff if e["obs"].state != "UNKNOWN"]
    warn = [e["obs"].category for e in known if e["obs"].state in CONFIRMING_STATES and e["decay"] >= confirm_min]
    stress = {e["obs"].category for e in known if e["obs"].state == "STRESS" and e["decay"] >= confirm_min}
    calm = [e["obs"].category for e in known if e["obs"].state in ("CALM", "IMPROVING")]
    improving = [e["obs"].category for e in known if e["obs"].state == "IMPROVING"]
    why: dict[str, Any] = {"confirming": warn, "stress": sorted(stress), "calm_or_improving": calm}

    def holds(name: str) -> bool:
        t = tiers[name]
        if score is not None and score >= float(t["min_score"]):
            return True
        if len(warn) < int(t["min_warn"]):
            return False
        need = t.get("require_stress_any")
        return not need or bool(stress & set(need))

    for name in ("red", "orange", "yellow", "blue"):
        if holds(name):
            tier = name.upper()
            break
    else:
        g = tiers["green"]
        tier = (
            "GREEN"
            if score is not None
            and score <= float(g["max_score"])
            and len(calm) >= int(g["min_calm_or_improving"])
            and len(improving) >= int(g["min_improving"])
            and len(warn) <= int(g["max_warn"])
            else "NONE"
        )
    shock = tiers.get("red_shock") or {}
    sc = next((e for e in known if e["obs"].category == shock.get("category")), None)
    why["shock"] = bool(
        sc
        and sc["obs"].state == "STRESS"
        and float(sc["obs"].score or 0) >= float(shock["shock_min_score"])
        and SEVERITY[tier] >= SEVERITY[str(shock.get("from_tier", "ORANGE"))]
    )
    if why["shock"]:
        tier = "RED"
    return tier, why


def _session_date(now: datetime) -> str:
    return now.astimezone(ET).date().isoformat()


def _hysteresis(raw: str, why: dict, prior: dict | None, now: datetime, policy: dict) -> tuple[str, dict[str, Any]]:
    cfg = policy["hysteresis"]
    today = _session_date(now)
    if not prior or prior.get("tier") not in SEVERITY:
        if cfg.get("bootstrap_adopts_raw", True):
            return raw, {"bootstrap": True, "raw_tier": raw, "candidate": None, "count": 0, "below_sessions": []}
        return "NONE", {"bootstrap": True, "raw_tier": raw, "candidate": raw, "count": 1, "below_sessions": []}
    cur = prior["tier"]
    h = dict(prior.get("hysteresis") or {})
    state = {
        "bootstrap": False,
        "raw_tier": raw,
        "prior_tier": cur,
        "candidate": None,
        "count": 0,
        "below_sessions": [],
    }
    if raw == cur:
        return cur, state
    green_move = "GREEN" in (raw, cur)
    if SEVERITY[raw] > SEVERITY[cur] or green_move:
        if raw == "RED" and why.get("shock"):
            state["immediate"] = "extended_hours shock"
            return raw, state
        count = int(h.get("count", 0)) + 1 if h.get("candidate") == raw else 1
        need = int(cfg["escalate_consecutive"])
        if count >= need:
            return raw, state
        state.update(candidate=raw, count=count, need=need)
        return cur, state
    below = list(h.get("below_sessions") or [])
    if today not in below:
        below.append(today)
    need = int(cfg["deescalate_sessions"])
    if len(below) >= need:
        return raw, state
    state.update(below_sessions=below, need_sessions=need)
    return cur, state


def compose(
    observations: list[c.CategoryObservation],
    policy: dict,
    *,
    prior: dict | None = None,
    now: datetime | None = None,
) -> c.RiskAssessment:
    """Observations -> RiskAssessment (market-level; ``apply_uplift`` adds the portfolio)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("compose(now=...) must be timezone-aware")
    eff = _effective(observations, now, policy)
    known = [e for e in eff if e["obs"].state != "UNKNOWN"]
    total_w = sum(e["weight"] for e in eff) or 1.0
    known_w = sum(e["weight"] for e in known)
    points: dict[str, float] = {}
    score: float | None
    if known_w > 0:
        for e in known:
            points[e["obs"].category] = e["weight"] * float(e["obs"].score) * e["decay"] / known_w
        score = round(sum(points.values()), 4)
    else:
        score = None
    raw, why = _raw_tier(score, eff, policy)
    tier, hyst = _hysteresis(raw, why, prior, now, policy)
    hyst.update(
        {
            "coverage": round(known_w / total_w, 4),
            "points": {k: round(v, 4) for k, v in points.items()},
            "decay": {e["obs"].category: e["decay"] for e in eff},
            "age_hours": {
                e["obs"].category: (round(e["age_hours"], 2) if e["age_hours"] is not None else None) for e in eff
            },
            "why": why,
        }
    )
    a = c.RiskAssessment(
        as_of=now.isoformat(),
        score=score,
        market_score=score,
        tier=tier,  # type: ignore[arg-type]
        market_tier=tier,  # type: ignore[arg-type]
        confirming=len(why["confirming"]),
        observations=[e["obs"] for e in eff],
        hysteresis=hyst,
    )
    return a


def _lift(tier: str) -> str:
    order = list(c.TIERS)
    return order[min(SEVERITY[tier] + 1, len(order) - 1)]


def apply_uplift(assessment: c.RiskAssessment, portfolio: c.PortfolioContext | None, policy: dict) -> c.RiskAssessment:
    """Exposure-aware severity: lift the tier at most ``max_tiers`` (one) for vulnerability or budget breach."""
    assessment.portfolio = portfolio
    if portfolio is None:
        return assessment
    cfg = policy["tiers"]["uplift"]
    base = assessment.market_tier
    target = base
    reasons: list[str] = []
    v = portfolio.vulnerability
    if v is not None:
        for rule in cfg["vulnerability_rules"]:
            if base == rule["from"] and float(v) >= float(rule["min_vulnerability"]):
                target = rule["to"]
                reasons.append(f"portfolio vulnerability {v:.0f} >= {rule['min_vulnerability']}")
                break
    ratio_floor = float(cfg["budget_ratio_uplift"])
    hard = [b for b in portfolio.budget_breaches if float(b.get("ratio") or 0) >= ratio_floor]
    if hard and base in cfg["budget_uplift_from"]:
        lifted = _lift(base)
        if SEVERITY[lifted] > SEVERITY[target]:
            target = lifted
        reasons.append("; ".join(f"{b.get('budget')} at {float(b['ratio']):.2f}x its limit" for b in hard))
    cap = SEVERITY[base] + int(cfg["max_tiers"])
    if SEVERITY[target] > cap:
        target = c.TIERS[cap]
    if target != base:
        assessment.tier = target  # type: ignore[assignment]
        assessment.uplift = {
            "from": base,
            "to": target,
            "market_score": assessment.market_score,
            "vulnerability": v,
            "reasons": reasons,
            "note": f"Market {base} {_fmt(assessment.market_score)} -> {target} after " + "; ".join(reasons),
        }
    c.assert_no_behavior_fields(assessment.to_dict())
    return assessment


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0f}"
