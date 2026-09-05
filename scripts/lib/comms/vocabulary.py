"""Canonical message-class vocabulary + synonym normalization (Wave A F3).

Producers split one concept across `ops` / `operator_alert` / `ops_alert` /
`health` / `health_digest` / `health_debug`. The gateway must not store
synonyms as distinct classes, or `owned_classes` matching silently misses
events that are conceptually the same class.

This module is the single canonical map. Normalization is alias-canonicalization
only: a documented synonym maps to its canonical name; an UNKNOWN class passes
through unchanged (never coerced), so an emitter's genuine bug stays visible
rather than being laundered into `ops` (AGENTS.md §7 — validate against a known
set, never normalize input to make it valid).

Protected-fact classes are canonical in their own right and are never aliased
away: collapsing `approval` or `protection_incident` into `ops` would silently
drop the fail-closed protected-facts gate in `event.required_missing`.
"""
from __future__ import annotations

# Classes that must carry non-empty protected_facts + authoritative_sources
# (fail closed). Mirrors scripts/lib/comms/event.PROTECTED_FACT_REQUIRED_CLASSES.
PROTECTED_FACT_CLASSES = frozenset(
    {
        "approval",
        "protection_incident",
        "broker_fact",
        "order_state",
        "risk_limit",
        "account_fact",
    }
)

# Canonical operational classes — the closed set `owned_classes` matches against.
CANONICAL_MESSAGE_CLASSES = frozenset(
    {
        "ops",
        "report",
        "proposal",
        "research",
        "digest",
        "operator_command",
    }
) | PROTECTED_FACT_CLASSES

# Documented producer synonyms → canonical. Every operational alert collapses to
# `ops`; `operator_command` is inbound and stays distinct.
MESSAGE_CLASS_ALIASES: dict[str, str] = {
    "operator_alert": "ops",
    "ops_alert": "ops",
    "alert": "ops",
    "health": "ops",
    "health_digest": "ops",
    "health_debug": "ops",
}


def _key(raw: str | None) -> str:
    return (raw or "").strip().lower().replace(" ", "_").replace("-", "_")


def normalize_message_class(raw: str | None) -> str:
    """Return the canonical class for a producer-supplied class.

    - blank → "" (left for `required_missing` to reject; never coerced to a
      valid class, so a missing field stays a missing field).
    - known alias → canonical name.
    - unknown → unchanged (visible, not silently fixed).
    """
    k = _key(raw)
    if not k:
        return ""
    return MESSAGE_CLASS_ALIASES.get(k, k)


def is_canonical(raw: str | None) -> bool:
    """True when the class is already a canonical name (no alias applied)."""
    k = _key(raw)
    return k in CANONICAL_MESSAGE_CLASSES
