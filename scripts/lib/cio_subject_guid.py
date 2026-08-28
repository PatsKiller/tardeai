"""Attach subject_guid from the identity registry. Lookup only. No mint.

UNRESOLVED stays UNRESOLVED. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
UNRESOLVED = "UNRESOLVED"


def lookup_subject(symbol: str, *, root=None) -> dict[str, Any]:
    """Read-only registry lookup. Never register()."""
    sym = str(symbol or "").strip().upper()
    empty = {
        "subject_guid": None,
        "entity_type": UNRESOLVED,
        "identity_status": UNRESOLVED,
        "symbol": sym or None,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }
    if not sym or sym in {"CASH", "PORTFOLIO", "MMKT"}:
        return empty
    try:
        from scripts.lib.identity_registry import load_cached, lookup_symbol
        ent = lookup_symbol(load_cached(root), sym)
    except Exception:
        return empty
    if not isinstance(ent, dict) or not ent.get("subject_guid"):
        return empty
    return {
        "subject_guid": ent.get("subject_guid"),
        "entity_type": ent.get("entity_type") or "SECURITY",
        "identity_status": ent.get("identity_status") or "CANDIDATE",
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
    for s in symbols:
        hit = lookup_subject(str(s), root=root)
        if hit.get("subject_guid"):
            guid = hit["subject_guid"]
            identity_status = hit.get("identity_status") or "CANDIDATE"
            entity_type = hit.get("entity_type") or "SECURITY"
            break
    out["subject_guid"] = guid
    out["entity_type"] = entity_type
    out["identity_status"] = identity_status
    if not guid:
        # Explicit: do not mint.
        out["subject_guid"] = None
        out["entity_type"] = UNRESOLVED
        out["identity_status"] = UNRESOLVED
    return out
