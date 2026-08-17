"""agent_wake_taxonomy.py — canonical wake triggers + autonomous action policy.

READ_ONLY_ADVISORY. Implements Phase 6 (Autonomous Office Initiative):
a single canonical vocabulary for *why an agent woke* and a hard boundary for
*what an agent may do autonomously* once it is awake.

Invariants:
  * every wake maps to exactly one canonical trigger (aliases/case/underscores
    normalized), or to ``None`` when unrecognized
  * follow-up wakes (FOLLOW_UP_DUE / DEFER_DUE) are distinct from material
    state-change wakes
  * autonomous actions are classified fail-closed: unrecognized -> denied
  * trading / risk-policy / broker-auth / rule-promotion mutations are always
    denied; this is an advisory office, not a trading desk
"""
from __future__ import annotations

import re
from typing import Optional

# ── Canonical wake triggers ────────────────────────────────────────────────
WAKE_TRIGGERS = frozenset({
    "POSITION_OPENED",
    "POSITION_CLOSED",
    "POSITION_SIZE_CHANGED_MATERIAL",
    "CASH_BAND_CHANGED",
    "CASH_USE_BECAME_ELIGIBLE",
    "REENTRY_STATE_CHANGED",
    "REENTRY_ELIGIBILITY_CHANGED",
    "RISK_STATE_CHANGED",
    "RESEARCH_DECISION_USE_CHANGED",
    "FRESHNESS_CHANGED",
    "DEFER_DUE",
    "FOLLOW_UP_DUE",
    "OPERATOR_CHALLENGE_OPENED",
    "OPERATOR_CHALLENGE_REVIEWABLE",
    "OUTCOME_MATURED",
    "LESSON_CANDIDATE_CREATED",
})

_FOLLOWUP_WAKES = frozenset({"FOLLOW_UP_DUE", "DEFER_DUE"})

# Alternate spellings / shorthand that map to a canonical trigger. Keys are
# normalized (see _normalize) before lookup, so case and separator style do not
# matter here.
_WAKE_ALIASES = {
    "POSITION_SIZE_CHANGED": "POSITION_SIZE_CHANGED_MATERIAL",
    "CASH_BAND_CROSSED": "CASH_BAND_CHANGED",
    "CASH_USE_ELIGIBLE": "CASH_USE_BECAME_ELIGIBLE",
    "REENTRY_CHANGED": "REENTRY_STATE_CHANGED",
    "RISK_CHANGED": "RISK_STATE_CHANGED",
    "RESEARCH_USE_CHANGED": "RESEARCH_DECISION_USE_CHANGED",
    "FOLLOWUP_DUE": "FOLLOW_UP_DUE",
    "CHALLENGE_OPENED": "OPERATOR_CHALLENGE_OPENED",
    "CHALLENGE_REVIEWABLE": "OPERATOR_CHALLENGE_REVIEWABLE",
    "LESSON_CANDIDATE": "LESSON_CANDIDATE_CREATED",
}

# ── Autonomous action policy ───────────────────────────────────────────────
AUTONOMOUS_ALLOWED_ACTIONS = frozenset({
    "LOAD_VERIFIED_TRUTH",
    "SEARCH_INTERNAL_RESEARCH",
    "RETRIEVE_MEMORY",
    "USE_READ_ONLY_MCP",
    "DELEGATE_SPECIALIST_QUESTION",
    "CREATE_UPDATE_ADVISORY_CASE",
    "SCHEDULE_REVISIT",
    "PREPARE_NOTIFICATION",
})

AUTONOMOUS_DENIED_ACTIONS = frozenset({
    "TRADE",
    "MODIFY_RISK_POLICY",
    "EDIT_EXTERNAL_DOCS_CALENDAR",
    "SEND_ARBITRARY_EMAIL",
    "MUTATE_BROKER_AUTH",
    "PROMOTE_LEARNED_RULES",
})

_ALLOWED_ACTION_ALIASES = {
    "LOAD_TRUTH": "LOAD_VERIFIED_TRUTH",
    "LOAD_VERIFIED_TRUTH": "LOAD_VERIFIED_TRUTH",
    "SEARCH_RESEARCH": "SEARCH_INTERNAL_RESEARCH",
    "RETRIEVE_MEMORY": "RETRIEVE_MEMORY",
    "READ_ONLY_MCP": "USE_READ_ONLY_MCP",
    "USE_READ_ONLY_MCP": "USE_READ_ONLY_MCP",
    "DELEGATE": "DELEGATE_SPECIALIST_QUESTION",
    "DELEGATE_SPECIALIST": "DELEGATE_SPECIALIST_QUESTION",
    "DELEGATE_BOUNDED_SPECIALIST_QUESTION": "DELEGATE_SPECIALIST_QUESTION",
    "DELEGATE_SPECIALIST_QUESTION": "DELEGATE_SPECIALIST_QUESTION",
    "CREATE_ADVISORY_CASE": "CREATE_UPDATE_ADVISORY_CASE",
    "CREATE_UPDATE_ADVISORY_CASE": "CREATE_UPDATE_ADVISORY_CASE",
    "SCHEDULE_REVISIT": "SCHEDULE_REVISIT",
    "PREPARE_NOTIFICATION": "PREPARE_NOTIFICATION",
}

_DENIED_ACTION_ALIASES = {
    "TRADE": "TRADE",
    "RISK_POLICY": "MODIFY_RISK_POLICY",
    "MODIFY_RISK_POLICY": "MODIFY_RISK_POLICY",
    "EDIT_EXTERNAL_DOCS": "EDIT_EXTERNAL_DOCS_CALENDAR",
    "EDIT_EXTERNAL_DOCS_CALENDAR": "EDIT_EXTERNAL_DOCS_CALENDAR",
    "SEND_EMAIL": "SEND_ARBITRARY_EMAIL",
    "SEND_ARBITRARY_EMAIL": "SEND_ARBITRARY_EMAIL",
    "BROKER_AUTH": "MUTATE_BROKER_AUTH",
    "MUTATE_BROKER_AUTH": "MUTATE_BROKER_AUTH",
    "PROMOTE_RULES": "PROMOTE_LEARNED_RULES",
    "PROMOTE_LEARNED_RULES": "PROMOTE_LEARNED_RULES",
}


def _normalize(text: str) -> str:
    """Collapse a token to uppercase alphanumerics for alias-insensitive lookup."""
    return re.sub(r"[^A-Z0-9]+", "", str(text).upper())


_WAKE_LOOKUP = {_normalize(t): t for t in WAKE_TRIGGERS}
for _alias, _target in _WAKE_ALIASES.items():
    _WAKE_LOOKUP.setdefault(_normalize(_alias), _target)

_ACTION_LOOKUP: dict[str, tuple[bool, str]] = {}
for _a in AUTONOMOUS_ALLOWED_ACTIONS:
    _ACTION_LOOKUP[_normalize(_a)] = (True, _a)
for _a in AUTONOMOUS_DENIED_ACTIONS:
    _ACTION_LOOKUP[_normalize(_a)] = (False, _a)
for _alias, _target in _ALLOWED_ACTION_ALIASES.items():
    _ACTION_LOOKUP.setdefault(_normalize(_alias), (True, _target))
for _alias, _target in _DENIED_ACTION_ALIASES.items():
    _ACTION_LOOKUP.setdefault(_normalize(_alias), (False, _target))


def canonicalize_wake_trigger(trigger: str) -> Optional[str]:
    """Return the canonical trigger for ``trigger``, or ``None`` if unrecognized.

    Normalizes case, whitespace, underscores, and hyphens so that
    ``"position_opened"``, ``"Position Opened"``, and ``"position-opened"`` all
    resolve to ``POSITION_OPENED``.
    """
    if trigger is None:
        return None
    return _WAKE_LOOKUP.get(_normalize(str(trigger)))


def is_followup_wake(trigger: str) -> bool:
    """True when the trigger is a scheduling follow-up (FOLLOW_UP_DUE / DEFER_DUE)."""
    return canonicalize_wake_trigger(trigger) in _FOLLOWUP_WAKES


def is_material_wake(trigger: str) -> bool:
    """True when the trigger is a recognized material state-change (not follow-up)."""
    c = canonicalize_wake_trigger(trigger)
    return c is not None and c not in _FOLLOWUP_WAKES


def allowed_autonomous_action(action: str) -> tuple[bool, str]:
    """Classify an autonomous action as (allowed, reason). Fail-closed.

    Returns ``(True, reason)`` for a recognized allowed action and
    ``(False, reason)`` for a denied or unrecognized action. Unrecognized
    actions are denied — this office never defaults to permit.
    """
    if action is None:
        return False, "denied: unrecognized action (fail-closed)"
    hit = _ACTION_LOOKUP.get(_normalize(str(action)))
    if hit is None:
        return False, "denied: unrecognized action (fail-closed)"
    ok, target = hit
    return (True, f"allowed: {target}") if ok else (False, f"denied: {target}")
