"""OpenBB provider due diligence — evaluation, not an implementation.

OpenBB is evaluated strictly as optional normalized provider plumbing. It is
NOT adopted as an uncontrolled agent dependency, and it must remain behind the
Trade AI Data Broker / governance layer. The decision below is a data record;
no OpenBB dependency is installed by this branch.
"""
from __future__ import annotations

# Decision values: ADOPT / DEFER / REJECT.
OPENBB_DECISION = "DEFER"

OPENBB_EVALUATION: dict = {
    "decision": OPENBB_DECISION,
    "reason": (
        "OpenBB would duplicate the existing Trade AI Data Broker and its "
        "provider-normalization layer without reducing provider-specific "
        "plumbing. It brings a large dependency footprint and a mix of paid "
        "provider keys, and its source-identity guarantees are weaker than the "
        "explicit provenance model already required here. Adopt later only if "
        "it demonstrably reduces plumbing while staying behind governance."
    ),
    "criteria": {
        "reduces_provider_plumbing": "UNCLEAR",
        "exposes_source_identity": "PARTIAL",
        "stays_behind_governance": "POSSIBLE",
        "duplicates_data_broker": "YES",
        "paid_keys_required": "PARTIAL",
        "dependency_footprint": "LARGE",
        "license": "community/enterprise split (needs legal review)",
    },
    "forbidden": "agent -> uncontrolled OpenBB toolbox",
    "preferred_if_used": (
        "TradeAI FinancialSenseProvider -> optional OpenBBProviderAdapter -> specific provider"
    ),
}


def openbb_decision() -> dict:
    return dict(OPENBB_EVALUATION)
