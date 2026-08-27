"""IdentityRegistry@v1 — the durable entity spine, persisted.

Phase A of `docs/architecture/cio/IDENTITY_AND_MEMORY_ADVISORY_2026-08-27.md`.

`security_identity.resolve_identity_spine()` already computes a correct
issuer → security → listing → ticker-alias identity and refuses to invent a CIK,
CUSIP, ISIN or FIGI it was not given. What never existed was a place to *keep*
the answer: the `identity.registry` store is declared in `CanonicalStoreRegistry@v1`
and was absent from disk, so every lineage envelope in production carried
`subject_guid: None` and `entity_type: UNRESOLVED` — 0 of 315.

This module is that place. It computes nothing an entity does not already have;
it makes the answer durable and re-readable, which is the precondition for any
lifecycle traversal at all — you cannot walk a graph whose nodes have no stable id.

## Identity upgrade, without breaking history

The hard requirement is that a GUID be immutable for the entity's entire
existence. The tension: a symbol first seen with only a name resolves to a
name-derived issuer GUID, and if a CUSIP arrives next week the spine computes a
*different, better* GUID. Silently switching would strand every record written
under the old one — history stops being traversable exactly where it matters.

So an upgrade never rewrites and never deletes. The prior GUID is retained as a
superseded alias pointing forward:

    entities[old_guid] = {..., "superseded_by": new_guid, "active": False}
    entities[new_guid] = {..., "supersedes": [old_guid], "active": True}

`resolve_guid()` follows the chain, so a reference written months ago still
resolves to the current entity. Both directions stay walkable: forward from any
historical id, backward through `supersedes`.

An entity is only ever upgraded to a *stronger* identity — the rank order is
CONFIRMED (durable instrument id) > CANDIDATE (issuer-derived) > UNRESOLVED
(ticker alias only). A weaker observation never displaces a stronger one, so a
feed that stops sending CUSIPs cannot silently downgrade an entity.

AUTHORITY: READ_ONLY_ADVISORY. Identity only. No prices, no positions, no
decisions, no financial action.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.lib.security_identity import normalize_symbol, resolve_identity_spine

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "IdentityRegistry@v1"
ENTITY_SCHEMA = "RegisteredEntity@v1"

REGISTRY_RELATIVE = Path("data") / "runtime" / "identity_registry.json"

# Strength order. An entity is never rewritten to a weaker identity.
STATUS_RANK = {
    "CONFIRMED": 3,
    "CANDIDATE": 2,
    "UNRESOLVED_WITH_REASON": 1,
}
# How many supersede hops to follow before declaring the chain broken. A cycle
# would otherwise hang a reader; the registry is append-only so this is a
# corruption guard, not an expected path.
MAX_CHAIN = 16


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def registry_path(root: Path | str | None = None) -> Path:
    env = os.environ.get("TRADEAI_IDENTITY_REGISTRY")
    if env:
        return Path(env)
    if root:
        return Path(root) / REGISTRY_RELATIVE
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root()) / REGISTRY_RELATIVE
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state" / REGISTRY_RELATIVE


def empty_registry() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "entities": {},
        "by_symbol": {},
        "events": {},
        "updated_at": None,
    }


def load(root: Path | str | None = None) -> dict[str, Any]:
    """Read the registry. A missing or unreadable file is an empty one."""
    path = registry_path(root)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_registry()
    if not isinstance(doc, dict):
        return empty_registry()
    base = empty_registry()
    base.update(doc)
    for key in ("entities", "by_symbol", "events"):
        if not isinstance(base.get(key), dict):
            base[key] = {}
    return base


def save(doc: Mapping[str, Any], root: Path | str | None = None) -> Path:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(doc)
    payload["schema"] = SCHEMA
    payload["authority"] = AUTHORITY
    payload["updated_at"] = _now()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)  # atomic: a reader never sees a half-written registry
    return path


def ticker_alias_guid(symbol: Any) -> str | None:
    """UUIDv5 alias for a bare ticker, defined in exactly one place.

    `resolve_identity_spine` deliberately returns no alias GUID: it will not
    derive a *security* identity from ticker text, which is correct. But an
    entity still needs a durable key before its CIK or CUSIP is known, and
    `memory_fact.subject_from_security` already defines that alias. Delegating to
    it means the registry and the memory substrate cannot drift onto two
    different GUIDs for the same ticker -- which matters because Phase B promotes
    memory_fact to authoritative and would otherwise inherit a split spine.
    """
    sym = normalize_symbol(symbol)
    if not sym:
        return None
    from scripts.lib.memory_fact import subject_from_security
    return subject_from_security(symbol=sym).get("ticker_alias_guid")


def subject_guid_of(spine: Mapping[str, Any], symbol: Any = None) -> str | None:
    """The durable key: security > issuer > ticker alias, matching memory_fact."""
    return (
        spine.get("security_guid")
        or spine.get("issuer_guid")
        or ticker_alias_guid(symbol if symbol is not None else spine.get("ticker_alias"))
    )


def resolve_guid(doc: Mapping[str, Any], guid: str | None) -> str | None:
    """Follow supersede links to the currently-active guid for a historical one."""
    if not guid:
        return None
    entities = doc.get("entities") or {}
    seen: set[str] = set()
    cur = str(guid)
    for _ in range(MAX_CHAIN):
        if cur in seen:
            return cur  # cycle: return where we are rather than loop
        seen.add(cur)
        nxt = (entities.get(cur) or {}).get("superseded_by")
        if not nxt:
            return cur
        cur = str(nxt)
    return cur


def lookup_symbol(doc: Mapping[str, Any], symbol: str) -> dict[str, Any] | None:
    """Current entity for a ticker, following any upgrade chain."""
    sym = normalize_symbol(symbol)
    guid = (doc.get("by_symbol") or {}).get(sym)
    if not guid:
        return None
    active = resolve_guid(doc, guid)
    return (doc.get("entities") or {}).get(active)


def register(doc: dict[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """Register or upgrade one entity. Mutates and returns `doc`.

    `row` is anything `resolve_identity_spine` accepts: symbol, and optionally
    company, cik, exchange, identifiers{cusip,isin,figi}.
    """
    spine = resolve_identity_spine(dict(row))
    sym = normalize_symbol(row.get("symbol"))
    guid = subject_guid_of(spine, sym)
    if not guid:
        return doc  # nothing durable to key on; refuse rather than invent one

    entities: dict[str, Any] = doc.setdefault("entities", {})
    by_symbol: dict[str, Any] = doc.setdefault("by_symbol", {})
    now = _now()

    status = str(spine.get("identity_status") or "UNRESOLVED_WITH_REASON")
    new_rank = STATUS_RANK.get(status, 0)

    prior_guid = resolve_guid(doc, by_symbol.get(sym)) if sym else None
    prior = entities.get(prior_guid) if prior_guid else None

    if prior and prior_guid != guid:
        if new_rank <= STATUS_RANK.get(str(prior.get("identity_status")), 0):
            # A weaker or equal observation never displaces the established one.
            prior["last_seen"] = now
            return doc
        # Upgrade: keep the old id resolvable, point it forward.
        prior["superseded_by"] = guid
        prior["active"] = False
        prior["superseded_at"] = now

    existing = entities.get(guid)
    if existing:
        existing["last_seen"] = now
        if new_rank > STATUS_RANK.get(str(existing.get("identity_status")), 0):
            existing.update({k: v for k, v in spine.items() if v is not None})
            existing["identity_status"] = status
        if sym and sym not in (existing.get("aliases") or []):
            existing.setdefault("aliases", []).append(sym)
    else:
        entities[guid] = {
            "schema": ENTITY_SCHEMA,
            **{k: v for k, v in spine.items() if k != "schema"},
            "subject_guid": guid,
            "aliases": [sym] if sym else [],
            "first_seen": now,
            "last_seen": now,
            "active": True,
            "supersedes": [prior_guid] if (prior and prior_guid != guid) else [],
        }

    if sym:
        by_symbol[sym] = guid
    return doc


def register_all(rows: Iterable[Mapping[str, Any]], root: Path | str | None = None,
                 *, apply: bool = False) -> dict[str, Any]:
    """Register many rows. Returns a summary; writes only when `apply`."""
    doc = load(root)
    before = len(doc.get("entities") or {})
    seen = 0
    for row in rows:
        if not row or not normalize_symbol(row.get("symbol")):
            continue
        seen += 1
        register(doc, row)
    after = len(doc.get("entities") or {})

    by_status: dict[str, int] = {}
    for ent in (doc.get("entities") or {}).values():
        key = str(ent.get("identity_status") or "UNKNOWN")
        by_status[key] = by_status.get(key, 0) + 1

    if apply:
        save(doc, root)

    return {
        "schema": SCHEMA,
        "rows_seen": seen,
        "entities_before": before,
        "entities_after": after,
        "entities_added": after - before,
        "by_identity_status": by_status,
        "symbols_indexed": len(doc.get("by_symbol") or {}),
        "applied": bool(apply),
        "path": str(registry_path(root)),
        "authority": AUTHORITY,
    }
