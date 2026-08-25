"""Human-readable CIO advisory messages. No raw JSON. READ_ONLY_ADVISORY."""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOAdvisoryMessage@v1"

FORBIDDEN_JSONISH = ("{", "}", "null", "true", "false")


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "UNVERIFIED"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "UNAVAILABLE"


def _range(value: Any) -> str:
    if isinstance(value, dict) and value.get("min") is not None and value.get("max") is not None:
        return f"{value['min']}%–{value['max']}%"
    return "UNCONFIRMED"


def _clean(text: str) -> str:
    body = (text or "").strip()
    if body.startswith("{") or body.startswith("["):
        raise ValueError("raw_json_forbidden_in_operator_message")
    return body


def render_policy_gap_message(situation: dict[str, Any]) -> str:
    fields = situation.get("policy_references") or situation.get("missing_policy_fields") or []
    listed = ", ".join(str(f) for f in fields) or "unspecified confirmed policy fields"
    cash = (situation.get("cash_situation") or {})
    cash_line = ""
    if cash.get("observed_cash_usd") is not None:
        cash_line = (
            f"Verified observed cash is {_money(cash.get('observed_cash_usd'))}"
            f" ({_pct(cash.get('cash_pct'))} of the book).\n"
        )
    return _clean(
        "Alex · CIO NOW\n\n"
        "HEADLINE\n"
        "I see a material situation but cannot complete the recommendation.\n\n"
        "WHY NOW\n"
        f"{cash_line}"
        "These policy inputs are not confirmed: "
        f"{listed}.\n\n"
        "WHAT TO CONSIDER\n"
        "Confirm the missing policy so I can finish the advisory. "
        "I will not recommend deployment or infer a mandate.\n\n"
        "WHAT WOULD CHANGE THE VIEW\n"
        "Operator confirmation of the listed fields, or a material change in verified portfolio truth.\n\n"
        "No orders or stops from this message. READ_ONLY_ADVISORY."
    )


def render_cash_advisory(situation: dict[str, Any]) -> str:
    cash = situation.get("cash_situation") or {}
    if situation.get("situation_class") == "POLICY_GAP" or cash.get("policy_gap"):
        return render_policy_gap_message(situation)
    conclusion = cash.get("conclusion") or situation.get("cio_conclusion") or "RESEARCH_FIRST"
    if conclusion == "DEPLOY_STAGED":
        env = "deploy gradually"
    elif conclusion == "HOLD_CASH" and cash.get("regime_risk_off"):
        env = "hold"
    elif conclusion == "RESEARCH_FIRST":
        env = "research first"
    else:
        env = "hold"
    destinations = cash.get("underweight_sleeves") or []
    dest_line = (
        "Highest-quality destinations currently supported by evidence: " + ", ".join(str(x) for x in destinations) + "."
        if destinations else
        "No confirmed high-quality destinations until living theses and underweight sleeves are current."
    )
    return _clean(
        "Alex · CIO NOW\n\n"
        "HEADLINE\n"
        f"Cash posture: {conclusion.replace('_', ' ').title()}.\n\n"
        "WHY NOW\n"
        f"You currently have approximately {_money(cash.get('verified_cash_usd') or cash.get('observed_cash_usd'))} of verified cash. "
        f"This is {_pct(cash.get('cash_pct'))} of the portfolio versus your confirmed policy range of {_range(cash.get('policy_range_pct'))}.\n\n"
        "VERIFIED PORTFOLIO SITUATION\n"
        f"Investable (deployable) cash: {_money(cash.get('investable_cash_usd'))}. "
        f"Reserved / non-deployable: {_money(cash.get('reserved_cash_usd'))}. "
        f"Deviation: {cash.get('deviation_state')}.\n\n"
        "CIO VIEW\n"
        f"The current environment suggests {env}. {dest_line}\n\n"
        "WHAT TO CONSIDER\n"
        "This is advisory only. Do not treat it as an order.\n\n"
        "EVIDENCE / COUNTEREVIDENCE\n"
        f"Support: {', '.join(str(x) for x in (situation.get('support') or []) if x) or 'portfolio cash facts'}.\n"
        f"Counter: {cash.get('counter_case') or 'Holding cash can remain rational.'}\n\n"
        "UNCERTAINTY\n"
        f"Market regime: {cash.get('market_regime') or 'UNAVAILABLE'}. "
        f"Seasonality: {cash.get('seasonality_state') or 'UNAVAILABLE'}.\n\n"
        "WHAT WOULD CHANGE THE VIEW\n"
        + "; ".join(str(x) for x in (cash.get("what_changes_the_plan") or ["policy change", "regime change"]))
        + "\n\n"
        "NEXT REVIEW TRIGGER\n"
        "On material portfolio, policy, or regime change.\n\n"
        "No orders or stops from this message. READ_ONLY_ADVISORY."
    )


def render_advisory_message(situation: dict[str, Any], *, synthesis_text: str | None = None) -> str:
    klass = str(situation.get("situation_class") or "")
    if klass in {"EXCESS_CASH", "POLICY_GAP"} or situation.get("cash_situation"):
        body = render_cash_advisory(situation)
        if synthesis_text and klass != "POLICY_GAP":
            body = body.replace(
                "CIO VIEW\n",
                "CIO VIEW\n" + synthesis_text.strip()[:800] + "\n",
                1,
            )
        return body
    headline = {
        "CONCENTRATION": "A holding is above concentration policy.",
        "THESIS_DETERIORATION": "A held thesis deteriorated.",
        "THESIS_IMPROVEMENT": "A held thesis improved.",
        "ALLOCATION_DRIFT": "Allocation drifted outside confirmed ranges.",
        "MARKET_REGIME_CHANGE": "Market regime changed.",
        "SEASONAL_SETUP": "A seasonal setup is now material.",
        "CATALYST_APPROACHING": "A known catalyst is approaching.",
        "REENTRY_READY": "A high-priority re-entry is research-complete.",
        "RESEARCH_GAP_RESOLVED": "A research gap resolved.",
        "CONTRADICTION": "Evidence is conflicted — do not act.",
        "OUTCOME_MATURITY": "An outcome sample matured into a lesson candidate.",
        "NO_MATERIAL_CHANGE": "Nothing material changed.",
    }.get(klass, klass.replace("_", " ").title())
    why = situation.get("what_changed") or headline
    conclusion = situation.get("cio_conclusion") or "REVIEW"
    support = situation.get("support") or []
    counter = situation.get("counterevidence") or []
    synth = (synthesis_text or "").strip()
    view = synth[:800] if synth else str(conclusion)
    return _clean(
        "Alex · CIO NOW\n\n"
        "HEADLINE\n"
        f"{headline}\n\n"
        "WHY NOW\n"
        f"{why}\n\n"
        "VERIFIED PORTFOLIO SITUATION\n"
        f"Class: {klass}. Affected: {', '.join(situation.get('affected_guids') or ['book'])}.\n\n"
        "CIO VIEW\n"
        f"{view}\n\n"
        "WHAT TO CONSIDER\n"
        "Advisory only. Confirm before any operator action.\n\n"
        "EVIDENCE / COUNTEREVIDENCE\n"
        f"Support: {support[:4]}.\n"
        f"Counter: {counter[:4]}.\n\n"
        "UNCERTAINTY\n"
        f"Confidence {situation.get('confidence')}; freshness {situation.get('freshness')}.\n\n"
        "WHAT WOULD CHANGE THE VIEW\n"
        "New verified facts, operator policy confirmation, or a later material delta.\n\n"
        "NEXT REVIEW TRIGGER\n"
        "Next material WHAT_CHANGED cycle.\n\n"
        "No orders or stops from this message. READ_ONLY_ADVISORY."
    )


def assert_not_json_dump(text: str) -> None:
    if text.lstrip().startswith("{") or text.lstrip().startswith("["):
        raise ValueError("raw_json_forbidden_in_operator_message")
    if '"schema"' in text and '"situation_id"' in text:
        raise ValueError("schema_dump_forbidden_in_operator_message")
