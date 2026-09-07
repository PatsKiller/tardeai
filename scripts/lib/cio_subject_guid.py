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


def lookup_identity_envelope(symbol: str, *, root=None) -> dict[str, Any]:
    """The full spine for one symbol, not just ``subject_guid``.

    ``lookup_subject`` answers "which subject is this", which is what a product row
    needs. Joining a corpus needs more: the issuer a security belongs to, and the
    identifiers that let a later reader re-resolve the row without guessing.

    Built ON ``lookup_subject`` rather than beside it, so the four outcomes it
    distinguishes are preserved exactly — in particular that a registry which cannot
    be READ is not the same as a symbol that is UNKNOWN. Collapsing those two is how
    a backfill silently marks a third of a corpus unresolvable and reports success.

    Never mints. A miss leaves the guids ``None`` and says why.
    """
    base = lookup_subject(symbol, root=root)
    out = dict(base)
    out["issuer_guid"] = None
    out["security_guid"] = None
    out["listing_guid"] = None
    if not base.get("subject_guid"):
        return out
    try:
        from scripts.lib.identity_registry import load_cached, lookup_symbol

        ent = lookup_symbol(load_cached(root), str(symbol or "").strip().upper())
    except Exception:
        # The subject resolved; only the enrichment failed. Report the subject
        # rather than discarding a good answer because a second read failed.
        return out
    if isinstance(ent, dict):
        for key in ("issuer_guid", "security_guid", "listing_guid"):
            out[key] = ent.get(key) or None
    return out


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


# Carriage counters for writers that stamp product rows (G-ID-01).
METRICS_HIT = "subject_guid_hit"
METRICS_MISS = "subject_guid_miss"


def _is_ticker_as_guid(guid: Any, symbol: str) -> bool:
    """Refuse ticker-as-GUID regression. Real GUIDs are not bare tickers."""
    if guid is None or not symbol:
        return False
    g = str(guid).strip().upper()
    s = str(symbol).strip().upper()
    return bool(g) and g == s


def stamp_subject_guid(
    row: dict[str, Any],
    *,
    symbol: str | None = None,
    root=None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp ``subject_guid`` from the identity registry. Lookup only. No mint.

    G-ID-01 carriage helper for reentry / watch / holdings product writers:

    * **Hit** — registry resolves → set ``subject_guid`` (and identity fields).
    * **Miss** — leave ``subject_guid`` unset (``None``) and increment the miss
      counter on ``metrics`` when provided.
    * **Never** mint, and **never** carriage ticker-as-GUID.

    ``stamp_row`` remains the multi-symbol / situation-detector path; this helper
    is the single-symbol product-row carriage API with an optional miss metric.
    """
    out = dict(row or {})
    sym = str(symbol or out.get("symbol") or "").strip().upper()
    if symbol is not None and not out.get("symbol"):
        out["symbol"] = sym

    if not sym or sym in NON_ENTITY_SYMBOLS:
        out["subject_guid"] = None
        out.setdefault("entity_type", UNRESOLVED)
        out.setdefault("identity_status", UNRESOLVED)
        out.setdefault("identity_lookup", NOT_APPLICABLE)
        out.setdefault("identity_lookup_failed", False)
        if metrics is not None:
            metrics[METRICS_MISS] = int(metrics.get(METRICS_MISS) or 0) + 1
        return out

    hit = lookup_subject(sym, root=root)
    guid = hit.get("subject_guid")
    if guid and _is_ticker_as_guid(guid, sym):
        # Hard rail: never ship ticker-as-security-GUID.
        guid = None

    if guid:
        out["subject_guid"] = guid
        out["entity_type"] = hit.get("entity_type") or "SECURITY"
        out["identity_status"] = hit.get("identity_status") or "CANDIDATE"
        out["identity_lookup"] = RESOLVED
        out["identity_lookup_failed"] = False
        out["identity_lookup_reason"] = None
        out["authority"] = AUTHORITY
        out["memory_behavior_influence"] = MBI
        if metrics is not None:
            metrics[METRICS_HIT] = int(metrics.get(METRICS_HIT) or 0) + 1
        return out

    # Miss: leave unset + counter. Do not invent a GUID.
    out["subject_guid"] = None
    out["entity_type"] = UNRESOLVED
    out["identity_status"] = UNRESOLVED
    out["identity_lookup"] = hit.get("identity_lookup") or UNRESOLVED
    out["identity_lookup_failed"] = bool(hit.get("identity_lookup_failed"))
    out["identity_lookup_reason"] = hit.get("identity_lookup_reason")
    out["authority"] = AUTHORITY
    out["memory_behavior_influence"] = MBI
    if metrics is not None:
        metrics[METRICS_MISS] = int(metrics.get(METRICS_MISS) or 0) + 1
    return out


def empty_carriage_metrics() -> dict[str, int]:
    """Fresh hit/miss counters for a writer pass."""
    return {METRICS_HIT: 0, METRICS_MISS: 0}
