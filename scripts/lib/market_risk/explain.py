"""Explainability (plan §5.10): the top five contributors with point attribution, and the de-escalation sentence.

The composite from ``scoring.compose`` is a weighted mean whose per-category points sum to the score. This module
lists the five largest, folds the rest into one "other" line, and asserts the lines sum to the score. It also
derives "De-escalates if …" from the next-lower tier's thresholds in policy. No model writes any of this.
"""

from __future__ import annotations

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk.scoring import SEVERITY

TOP_N = 5
TOLERANCE = 0.01


def attribute(assessment: c.RiskAssessment, top_n: int = TOP_N) -> list[c.Contributor]:
    points: dict[str, float] = dict((assessment.hysteresis or {}).get("points") or {})
    by_cat = {o.category: o for o in assessment.observations}
    ranked = sorted(((k, v) for k, v in points.items() if abs(v) > 1e-9), key=lambda kv: (-kv[1], kv[0]))
    out = [
        c.Contributor(category=k, points=round(v, 2), headline=by_cat[k].headline, as_of=by_cat[k].observed_at)
        for k, v in ranked[:top_n]
    ]
    rest = ranked[top_n:]
    if rest:
        out.append(
            c.Contributor(
                category="other",
                points=round(sum(v for _, v in rest), 2),
                headline="other: " + ", ".join(k for k, _ in rest),
                as_of=None,
            )
        )
    total = sum(x.points for x in out)
    if assessment.market_score is not None and abs(total - assessment.market_score) > TOLERANCE * max(1, len(out)):
        raise AssertionError(f"contributors sum {total:.2f} != market score {assessment.market_score:.2f}")
    return out


def _lower(tier: str) -> str | None:
    order = ["NONE", "BLUE", "YELLOW", "ORANGE", "RED"]
    return order[order.index(tier) - 1] if tier in order and order.index(tier) > 0 else None


def deescalates_if(assessment: c.RiskAssessment, policy: dict) -> str:
    tier = assessment.market_tier
    if tier not in ("BLUE", "YELLOW", "ORANGE", "RED"):
        return ""
    t = policy["tiers"][tier.lower()]
    lower = _lower(tier)
    score = assessment.market_score
    parts = [
        f"score below {t['min_score']} (now {score:.0f})" if score is not None else f"score below {t['min_score']}"
    ]
    parts.append(f"fewer than {t['min_warn']} categories at WARN or STRESS (now {assessment.confirming})")
    need = t.get("require_stress_any")
    if need:
        parts[-1] += f", or none of {', '.join(need)} at STRESS"
    contributors = assessment.contributors or attribute(assessment)
    top = next((x for x in contributors if x.category != "other"), None)
    lead = f"; the largest driver is {top.category} ({top.headline})" if top else ""
    market = f"{tier} -> {lower} if {' and '.join(parts)}{lead}."
    up = assessment.uplift or {}
    shown = assessment.tier
    if up and shown != tier:
        why = "; ".join(str(r) for r in (up.get("reasons") or [])) or "portfolio exposure"
        return (
            f"{shown} (portfolio uplift from {tier}) -> {tier} when the book falls back under its limits ({why}); "
            f"the market itself: {market}"
        )
    return market


def explain(assessment: c.RiskAssessment, policy: dict) -> c.RiskAssessment:
    """Fill ``contributors`` and ``deescalates_if`` in place; returns the assessment."""
    assessment.contributors = attribute(assessment)
    assessment.deescalates_if = deescalates_if(assessment, policy)
    c.assert_no_behavior_fields(assessment.to_dict())
    return assessment


def card_lines(assessment: c.RiskAssessment) -> list[str]:
    """Phone-length lines for alerts and the UI (plan §5.10 format)."""
    head = (
        f"Risk {assessment.score:.0f}/100 · {assessment.tier}"
        if assessment.score is not None
        else f"Risk n/a · {assessment.tier}"
    )
    if assessment.uplift:
        head += f" (uplift from {assessment.uplift['from']}: {', '.join(assessment.uplift['reasons'])})"
    lines = [head]
    for x in assessment.contributors:
        lines.append(f"{x.category:<16} {x.points:+.0f}  {x.headline}")
    cov = (assessment.hysteresis or {}).get("coverage")
    if cov is not None and cov < 1:
        unk = [o.category for o in assessment.observations if o.state == "UNKNOWN"]
        lines.append(f"Not measured: {', '.join(unk)} (coverage {cov:.0%})")
    if assessment.deescalates_if:
        lines.append(f"De-escalates if: {assessment.deescalates_if}")
    return lines


__all__ = ["attribute", "deescalates_if", "explain", "card_lines", "SEVERITY"]
