"""OptionsDecisionPacket@v1 — one advisory object per proposal.

Adapts recommendation_comparison. A computed preference is not a CIO
approval. MEMORY_BEHAVIOR_INFLUENCE is not read or set here.
"""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime, timezone

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


def review_workflow(proposal: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Investment review is separate from submission gates; neither grants authority."""
    thesis = proposal.get("options_thesis") or {}
    dec = proposal.get("cio_decision") or {}
    outcome = str(dec.get("outcome") or "").upper() if dec.get("decision_guid") else ""
    stage = str((proposal.get("lifecycle") or {}).get("stage") or "").upper()
    ent = proposal.get("enterprise") or {}
    missing = thesis.get("missing_required") or []
    blocks = list(ent.get("blocks") or []) + list(proposal.get("thesis_blocks") or [])
    texts = [str(b.get("code", "")) + " " + str(b.get("reason", "")) if isinstance(b, dict) else str(b)
             for b in blocks]
    def result(state: str, reason: str, action: str, owner: str) -> dict[str, Any]:
        return {"state": state, "reason": reason, "next_action": action, "owner": owner,
                "live_submit": False, "decision_guid": dec.get("decision_guid"),
                "proposal_id": proposal.get("id"), "option_strategy_guid": proposal.get("option_strategy_guid"),
                "options_thesis_pin": thesis.get("pin"),
                "decision_scope": "this strategy and account; ticker decisions are context only"}
    expiration = str(proposal.get("expiration") or "")[:10]
    expired = False
    if expiration:
        try:
            expired = datetime.fromisoformat(expiration).date() < (now or datetime.now(timezone.utc)).date()
        except ValueError:
            pass  # Missing/bad dates cannot grant execution eligibility.
    if proposal.get("thesis_abandoned") or stage.startswith("ARCHIVED") or outcome in {"REJECT", "EXPIRED"} or expired:
        return result("REJECTED_OR_EXPIRED", outcome or ("contract expired" if expired else stage) or "archived", "Reconsider only with new evidence", "CIO / operator")
    if missing or not thesis.get("pin") or outcome in {"MORE_RESEARCH", "RESEARCH_MORE"}:
        reason = "Missing: " + ", ".join(missing) if missing else (outcome or "Options thesis is not recorded")
        return result("NEEDS_RESEARCH", reason, "Complete the existing thesis and research gaps", "Research / CIO")
    # A pending decision is the purpose of this queue. Quote and policy failures remain visible.
    other = [t for t in texts if not ("awaiting_cio_decision" in t.lower() or "cio decision pending" in t.lower())]
    liquidity = ent.get("liquidity") or {}
    if liquidity.get("pass") is False:
        return result("NEEDS_DATA", "; ".join(map(str, liquidity.get("issues") or ["Quote/liquidity failed"])),
                      "Validate quotes during the regular session", "Quote validation")
    quote_words = ("awaiting live quotes", "quote", "liquidity", "spread_too_wide", "market closed", "market_closed")
    hard = [t for t in other if not any(w in t.lower() for w in quote_words)]
    if hard:
        return result("BLOCKED", "; ".join(hard), "Resolve the recorded policy or evidence block", "CIO / operator")
    if outcome == "APPROVE":
        if proposal.get("approvable") is True and ent.get("live_eligible") is True and not other:
            return result("READY_FOR_PREFLIGHT", "CIO approval recorded for this idea", "Fresh preflight and per-order 2FA", "Operator")
        return result("APPROVED_AWAITING_QUOTES", "; ".join(other) or "Execution checks remain outstanding",
                      "Validate quotes and recheck all existing gates", "Quote validation / operator")
    if liquidity.get("pass") is not True:
        return result("NEEDS_DATA", "Quote/liquidity assessment is missing", "Validate the captured contract quotes", "Quote validation")
    if proposal.get("max_loss") is None or proposal.get("premium") is None:
        return result("NEEDS_DATA", "Economics are unavailable", "Repair quote or contract inputs", "Options research")
    return result("READY_FOR_REVIEW", "Thesis and estimated economics available; approval is pending",
                  "Review the exact strategy, account, thesis and quote assumptions", "CIO / operator")


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
        "review_workflow": review_workflow(proposal),
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
