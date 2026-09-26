"""OptionsDecisionPacket@v1 — one advisory object per proposal.

Adapts recommendation_comparison. A computed preference is not a CIO
approval. MEMORY_BEHAVIOR_INFLUENCE is not read or set here.
"""
from __future__ import annotations

from typing import Any, Optional

try:
    from scripts.lib.recommendation_comparison import build_recommendation_comparison
except ImportError:  # api_v2 puts scripts/ on sys.path
    from lib.recommendation_comparison import build_recommendation_comparison  # type: ignore

SCHEMA = "OptionsDecisionPacket@v1"


def _blocks(proposal: dict[str, Any]) -> list[str]:
    raw = (proposal.get("enterprise") or {}).get("blocks") or []
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append(str(item.get("reason") or item.get("code") or ""))
        else:
            out.append(str(item))
    return [x for x in out if x]


def sovereign_state(proposal: dict[str, Any], comparison: dict[str, Any]) -> str:
    notes = (comparison.get("stock_play") or {}).get("risk_notes") or []
    preferred = (comparison.get("comparison") or {}).get("preferred_structure")
    if _blocks(proposal) or "NEED_100_SHARES" in notes:
        return "BLOCKED"
    if preferred == "neither":
        return "REVIEW_REQUIRED"
    pin = (comparison.get("thesis") or {}).get("thesis_version")
    live = (proposal.get("enterprise") or {}).get("live_eligible") is True
    if preferred in {"stock", "options"} and pin and live:
        return "ELIGIBLE_FOR_OPERATOR_REVIEW"
    return "REVIEW_REQUIRED"


def build_options_decision_packet(
    proposal: dict[str, Any],
    *,
    comparison: Optional[dict[str, Any]] = None,
    equity: Optional[dict[str, Any]] = None,
    thesis: Optional[dict[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    cmp = comparison or build_recommendation_comparison(
        proposal, equity=equity, thesis=thesis, generated_at=generated_at,
    )
    state = sovereign_state(proposal, cmp)
    opt = cmp.get("options_play") or {}
    comp = cmp.get("comparison") or {}
    overs = cmp.get("oversight") or {}
    acct = str(proposal.get("account") or "")
    cta = "operator_review" if state == "ELIGIBLE_FOR_OPERATOR_REVIEW" else "none"
    return {
        "schema": SCHEMA,
        "state": state,
        "cio_approved": False,
        "facts": {
            "symbol": (cmp.get("underlying") or {}).get("symbol"),
            "security_guid": (cmp.get("underlying") or {}).get("security_guid"),
            "strategy": proposal.get("strategy"),
            "account": acct or None,
            "data_source": proposal.get("data_source"),
            "legs": list(opt.get("legs") or []),
        },
        "estimates": {
            "max_profit": opt.get("max_profit"),
            "maximum_risk": opt.get("maximum_risk"),
            "expected_return": opt.get("expected_return"),
            "reward_to_risk": comp.get("reward_to_risk"),
            "risk_to_capital": comp.get("risk_to_capital"),
            "probability_of_success": opt.get("probability_of_success"),
            "probability_basis": opt.get("probability_basis"),
        },
        "model": {
            "ensemble_present": bool(proposal.get("ensemble_verdict") or proposal.get("aegis_verdict")),
            "note": "A model score is not a CIO disposition.",
        },
        "operator": {
            "review_status": overs.get("review_status") or "unreviewed",
            "cio_review_id": overs.get("cio_review_id"),
        },
        "readiness": {
            "preferred_structure": comp.get("preferred_structure"),
            "live_submit": False,
            "cta": cta,
        },
        "broker": {
            "route": "schwab" if acct.lower().startswith("schwab") else "unknown",
            "armed": None,
        },
        "comparison": cmp,
    }
