"""Attach subject_guid from the identity registry. Lookup only. No mint.

UNRESOLVED stays UNRESOLVED. READ_ONLY_ADVISORY.

Wave 2 slice 17: ``identity_status`` alone conflated four different situations
into one word. A registry that could not be *read* reported exactly what a
registry that answered "no such entity" reported, so an outage looked like a
clean negative. ``identity_lookup`` now separates them while
``identity_status`` keeps its old contract (UNRESOLVED stays UNRESOLVED):

* ``RESOLVED``        — the registry returned an entity.
* ``UNRESOLVED``      — the registry answered, and has no entity for this symbol.
* ``LOOKUP_FAILED``   — the registry could not be read. **Not** a negative answer.
* ``NOT_APPLICABLE``  — CASH/PORTFOLIO/MMKT or an empty symbol; nothing to resolve.

Only ``UNRESOLVED`` is evidence about the symbol. The other two negatives are
evidence about the lookup.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
UNRESOLVED = "UNRESOLVED"

RESOLVED = "RESOLVED"
LOOKUP_FAILED = "LOOKUP_FAILED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NON_ENTITY_SYMBOLS = frozenset({"CASH", "PORTFOLIO", "MMKT"})


def _empty(sym: str, lookup: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "subject_guid": None,
        "entity_type": UNRESOLVED,
        "identity_status": UNRESOLVED,
        "identity_lookup": lookup,
        "identity_lookup_failed": lookup == LOOKUP_FAILED,
        "identity_lookup_reason": reason,
        "symbol": sym or None,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def lookup_subject(symbol: str, *, root=None) -> dict[str, Any]:
    """Read-only registry lookup. Never register()."""
    sym = str(symbol or "").strip().upper()
    if not sym or sym in NON_ENTITY_SYMBOLS:
        return _empty(sym, NOT_APPLICABLE, "cash_or_non_entity_symbol" if sym else "empty_symbol")
    try:
        from scripts.lib.identity_registry import load_cached, lookup_symbol
        ent = lookup_symbol(load_cached(root), sym)
    except Exception as exc:
        # The registry could not be read. That is not "this symbol is unknown".
        return _empty(sym, LOOKUP_FAILED, type(exc).__name__)
    if not isinstance(ent, dict) or not ent.get("subject_guid"):
        return _empty(sym, UNRESOLVED, "registry_answered_no_entity")
    return {
        "subject_guid": ent.get("subject_guid"),
        "entity_type": ent.get("entity_type") or "SECURITY",
        "identity_status": ent.get("identity_status") or "CANDIDATE",
        "identity_lookup": RESOLVED,
        "identity_lookup_failed": False,
        "identity_lookup_reason": None,
        "symbol": sym,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def stamp_row(row: dict[str, Any], *, root=None) -> dict[str, Any]:
    out = dict(row or {})
    symbols = list(out.get("symbols") or [])
    if not symbols and out.get("symbol"):
        symbols = [out.get("symbol")]
    guid = None
    identity_status = UNRESOLVED
    entity_type = UNRESOLVED
    lookup = NOT_APPLICABLE if not symbols else None
    reason = "no_symbols_on_row" if not symbols else None
    for s in symbols:
        hit = lookup_subject(str(s), root=root)
        if hit.get("subject_guid"):
            guid = hit["subject_guid"]
            identity_status = hit.get("identity_status") or "CANDIDATE"
            entity_type = hit.get("entity_type") or "SECURITY"
            lookup = RESOLVED
            reason = None
            break
        # Keep the strongest explanation seen: a read failure outranks a clean
        # negative, which outranks "there was nothing to look up".
        cand, cand_reason = hit.get("identity_lookup"), hit.get("identity_lookup_reason")
        if lookup != LOOKUP_FAILED and (cand == LOOKUP_FAILED or lookup in (None, NOT_APPLICABLE)):
            lookup, reason = cand, cand_reason
    out["subject_guid"] = guid
    out["entity_type"] = entity_type
    out["identity_status"] = identity_status
    out["identity_lookup"] = lookup or UNRESOLVED
    out["identity_lookup_failed"] = (lookup == LOOKUP_FAILED)
    out["identity_lookup_reason"] = reason
    if not guid:
        # Explicit: do not mint.
        out["subject_guid"] = None
        out["entity_type"] = UNRESOLVED
        out["identity_status"] = UNRESOLVED
    return out
