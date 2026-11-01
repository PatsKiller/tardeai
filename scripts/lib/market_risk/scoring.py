"""Composite score, tier, hysteresis, confidence decay and portfolio uplift (plan §5.2, §5.9, §5.11, §5.13).

Deterministic and model-free. Every number comes from ``config/market_risk_policy.yaml`` (keys ``weights``,
``tiers``, ``hysteresis``, ``decay``, ``composite``). The shipped composite is ``composite.method`` (noisy-OR since the
2026-10-31 integration: only WARN/STRESS categories add risk and confirmations stack; see ``compose``); the old
weighted mean is kept as ``method: mean`` for comparison runs. Either way the per-category point contributions sum to
the score exactly (``explain.attribute`` relies on this). UNKNOWN categories are reported as lost ``coverage``, never
as zero. Sessions for hysteresis are closed NYSE trading days (``sessions.py``). Advisory only (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import sessions

ET = ZoneInfo("America/New_York")
SEVERITY = {t: i for i, t in enumerate(c.TIERS)}  # GREEN 0 < NONE 1 < BLUE 2 < YELLOW 3 < ORANGE 4 < RED 5
CONFIRMING_STATES = ("WARN", "STRESS")
SESSION_CLOSE_ET = time(16, 0)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _age_hours(at: datetime, now: datetime, cfg: dict) -> float:
    """Age of an observation for decay and staleness. ``decay.clock: market`` counts only hours in which the market
    could have produced newer information (``sessions.market_hours_between``): a weekend or holiday does not age
    Friday's close, and from ``decay.reopen_et`` on the evening before a trading day (index futures and Asia open
    Sunday 18:00 ET) the clock runs again. Any other value (or none) is wall-clock hours."""
    if str(cfg.get("clock") or "wall").lower() == "market":
        reopen = None
        if cfg.get("reopen_et"):
            hh, mm = str(cfg["reopen_et"]).split(":")
            reopen = time(int(hh), int(mm))
        return max(0.0, sessions.market_hours_between(at, now, reopen=reopen))
    return max(0.0, (now - at).total_seconds() / 3600.0)


def decay_weight(obs: c.CategoryObservation, now: datetime, policy: dict) -> tuple[float, float | None]:
    """(weight, age_hours). Weight 0 means stale beyond stale_after: the category becomes UNKNOWN."""
    cfg = policy["decay"]
    at = _parse(obs.observed_at)
    if at is None:
        return 0.0, None
    age = _age_hours(at, now, cfg)
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
        # require_stress_any binds BOTH paths (review of #2362, B2): a high score built from WARNs alone never reaches
        # a tier that names required STRESS categories.
        t = tiers[name]
        need = t.get("require_stress_any")
        if need and not (stress & set(need)):
            return False
        if score is not None and score >= float(t["min_score"]):
            return True
        return len(warn) >= int(t["min_warn"])

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


def _green_guard(
    raw: str, why: dict, eff: list[dict], coverage: float, prior: dict | None, now: datetime, policy: dict
) -> tuple[str, str | None]:
    """GREEN needs enough measured evidence and a clean recent past (review of #2383, N2): at least
    ``green.min_coverage`` of the category weight measured, and no STRESS observation in the last
    ``green.no_stress_hours`` (carried forward between evaluations as ``hysteresis.last_stress_at``)."""
    g = policy["tiers"]["green"]
    hours = float(g.get("no_stress_hours", 24))
    recent = [e for e in eff if e["obs"].state == "STRESS" and e["age_hours"] is not None and e["age_hours"] < hours]
    prev = ((prior or {}).get("hysteresis") or {}).get("last_stress_at")
    last_stress = now.isoformat() if recent else prev
    if raw != "GREEN":
        return raw, last_stress
    blockers = []
    if coverage < float(g.get("min_coverage", 0.7)):
        blockers.append(f"coverage {coverage:.2f} below {float(g.get('min_coverage', 0.7)):.2f}")
    # the categories that see a selloff coming must be measured, unless almost everything is (review round 3, M-B)
    must = [str(k) for k in g.get("must_measure") or []]
    measured = {e["obs"].category for e in eff if e["obs"].state != "UNKNOWN"}
    missing = [k for k in must if k not in measured]
    if missing and coverage < float(g.get("min_coverage_if_missing_must", 0.85)):
        blockers.append("not measured: " + ", ".join(missing))
    if not prior or prior.get("tier") not in SEVERITY:
        blockers.append("bootstrap evaluation (no prior)")  # GREEN is never the first word (M-B)
    ls = _parse(last_stress) if last_stress else None
    if ls is not None and (now - ls).total_seconds() < hours * 3600:
        blockers.append(f"STRESS within {hours:g}h")
    if blockers:
        why["green_blocked"] = blockers
        return "NONE", last_stress
    return raw, last_stress


def _session_date(now: datetime) -> str:
    return now.astimezone(ET).date().isoformat()


def _hysteresis(raw: str, why: dict, prior: dict | None, now: datetime, policy: dict) -> tuple[str, dict[str, Any]]:
    cfg = policy["hysteresis"]
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
    # Only NONE <-> GREEN moves take the two-evaluation path. BLUE-or-above falling to GREEN is a de-escalation and
    # goes through the closed-session count below (review of #2383, N2: RED reached GREEN in two evaluations).
    green_move = "GREEN" in (raw, cur) and cur in ("GREEN", "NONE")
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
    # A session counts toward de-escalation only once it has closed, and only on an NYSE trading day (sessions.py):
    # a calm morning print must not complete the count on the day hedging demand surges (10-29 10:15), and a weekend
    # or holiday is never a session (review of #2362, B4).
    closed = sessions.completed_session(now)
    if closed and closed not in below:
        below.append(closed)
    need = int(cfg["deescalate_sessions"])
    if len(below) >= need:
        return raw, state
    state.update(below_sessions=below, need_sessions=need)
    return cur, state


def _prior_dict(prior: Any) -> dict | None:
    """Accept the previous assessment as a dict (stored JSON) or a RiskAssessment (in-process replay).

    Hysteresis runs on the MARKET tier: the portfolio uplift is re-applied every evaluation and must never feed back
    into the market state machine (else an uplifted RED would need three sessions to fall even when the book changed).
    """
    if prior is None:
        return None
    if not isinstance(prior, dict):
        prior = {
            "tier": getattr(prior, "tier", None),
            "market_tier": getattr(prior, "market_tier", None),
            "hysteresis": dict(getattr(prior, "hysteresis", None) or {}),
        }
    d = dict(prior)
    if d.get("market_tier") in SEVERITY:
        d["tier"] = d["market_tier"]
    return d


def _composite(known: list[dict], known_w: float, policy: dict) -> tuple[dict[str, float], float | None]:
    """Composite 0-100 and per-category points that sum to it.

    ``noisy_or`` (default): only confirming categories (WARN/STRESS) add risk, and independent confirmations
    accumulate: score = 100 * (1 - prod(1 - x_i)), x_i = min(cap, unit_weight * f * weight_i * score_i/100 * decay_i),
    f = 1 for STRESS and warn_factor for WARN (a WARN is evidence, a STRESS is confirmation).
    A calm or improving category adds nothing instead of diluting the others; this is the design's "escalate only on
    multi-category confirmation" (one fully stressed category alone stays Blue/Yellow; Orange needs several).
    The 2026-10-31 integration replaced the weighted mean, under which calm low-weight priors (seasonal, event)
    pulled the March 2020 crash down to Yellow.
    Points are attributed by each category's share of -log(1 - x_i), so the contributors sum exactly to the score.
    ``mean``: the original weighted average over known categories (kept for comparison runs).
    """
    if known_w <= 0:
        return {}, None
    cfg = policy.get("composite") or {}
    method = str(cfg.get("method") or "noisy_or")
    points: dict[str, float] = {}
    if method == "mean":
        for e in known:
            points[e["obs"].category] = e["weight"] * float(e["obs"].score) * e["decay"] / known_w
        return points, round(sum(points.values()), 4)
    unit, cap = float(cfg.get("unit_weight", 0.40)), float(cfg.get("max_per_category", 0.95))
    warn_factor = float(cfg.get("warn_factor", 0.6))
    xs: dict[str, float] = {}
    for e in known:
        if e["obs"].state not in CONFIRMING_STATES:
            continue
        f = 1.0 if e["obs"].state == "STRESS" else warn_factor
        x = min(cap, unit * f * e["weight"] * float(e["obs"].score or 0) / 100.0 * e["decay"])
        if x > 0:
            xs[e["obs"].category] = x
    survive = 1.0
    for x in xs.values():
        survive *= 1.0 - x
    # An unmeasured category never raises the score or the tier (review of #2362, B2): no coverage extrapolation.
    # Lost coverage is reported on the card (hysteresis["coverage"]) instead of being converted into risk.
    score = round(100.0 * (1.0 - survive), 4)
    logs = {k: -math.log(1.0 - x) for k, x in xs.items()}
    tot = sum(logs.values())
    for e in known:
        cat = e["obs"].category
        points[cat] = (score * logs[cat] / tot) if (cat in logs and tot > 0) else 0.0
    return points, score


def compose(
    observations: list[c.CategoryObservation],
    policy: dict,
    *,
    prior: Any = None,
    now: datetime | None = None,
) -> c.RiskAssessment:
    """Observations -> RiskAssessment (market-level; ``apply_uplift`` adds the portfolio)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("compose(now=...) must be timezone-aware")
    prior = _prior_dict(prior)
    eff = _effective(observations, now, policy)
    known = [e for e in eff if e["obs"].state != "UNKNOWN"]
    total_w = sum(e["weight"] for e in eff) or 1.0
    known_w = sum(e["weight"] for e in known)
    points, score = _composite(known, known_w, policy)
    raw, why = _raw_tier(score, eff, policy)
    coverage = known_w / total_w
    raw, last_stress = _green_guard(raw, why, eff, coverage, prior, now, policy)
    tier, hyst = _hysteresis(raw, why, prior, now, policy)
    hyst.update(
        {
            "last_stress_at": last_stress,
            "coverage": round(coverage, 4),
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


def budget_uplift_breaches(portfolio: c.PortfolioContext, cfg: dict) -> list[dict]:
    """Breaches that may lift the tier (review of #2383, N1). A whole-book breach counts at its ratio. An account
    breach counts at ``1 + (ratio - 1) * book_share``, so a small single-name account over its sector or style limit
    (ratio 3.2 on 5% of the book -> 1.11) never lifts the tier on its own."""
    floor = float(cfg["budget_ratio_uplift"])
    book_level = {b.get("budget") for b in portfolio.budget_breaches if b.get("scope", "book") == "book"}
    out = []
    for b in portfolio.budget_breaches:
        ratio = float(b.get("ratio") or 0)
        if b.get("scope", "book") != "book":
            share = b.get("book_share")
            if share is None:
                continue  # an account breach with no known weight never lifts the tier
            if b.get("budget") not in book_level:
                continue  # an account breach counts only when the book breaches the same budget (round 3, L1)
            ratio = 1.0 + (ratio - 1.0) * float(share)
        if ratio >= floor:
            out.append(b)
    return out


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
                reasons.append("portfolio vulnerability high")
                break
    hard = budget_uplift_breaches(portfolio, cfg)
    min_v = float(cfg.get("budget_uplift_min_vulnerability") or 0)
    if hard and base in cfg["budget_uplift_from"] and v is not None and float(v) >= min_v:
        lifted = _lift(base)
        if SEVERITY[lifted] > SEVERITY[target]:
            target = lifted
        # names only — no book percentages or ratios on a card (review of #2383, M3)
        reasons.append("budget breach: " + ", ".join(sorted({str(b.get("budget")) for b in hard})))
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
            "note": f"Market {base} -> {target} after " + "; ".join(reasons),
        }
    c.assert_no_behavior_fields(assessment.to_dict())
    return assessment


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0f}"
