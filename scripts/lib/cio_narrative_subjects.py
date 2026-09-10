#!/usr/bin/env python3
"""NarrativeSubjectLink@v1 — what a narrative is ABOUT, across every subject type.

Fifteen surfaces on this system hold a narrative, thesis, rationale or summary.
On 2026-09-10 exactly one of them — `subject_state_narratives` — carried any
identity. Every defense thesis, every rotation thesis, every sizing rationale and
all 462,902 rows of `agent_recommendation_registry` carried none, so none of it
could be rolled up, cited, or shown against the security, sector or industry it
concerns.

The concrete defect this closes: `material_changes` fires `sector_move` (14 rows,
13 with a subject_guid), but the detector emits it under a representative MEMBER
symbol and buries the sector in the evidence payload. A SECTOR event therefore
carries a SECURITY guid — which AGENTS.md §17A already forbids in words
("Topics are subjects, not securities... never give a theme a SECURITY guid")
and which nothing enforced in code.

WHY THIS IS A LINK AND NOT A COLUMN. A defense thesis is about a theme AND a
sector AND several securities. `two_way_curation.rotation_signal_to_feedback`
returns None without a sector and sets `symbol` only when an ETF proxy exists —
rotation is sector-first BY DESIGN. A single `subject_guid` column cannot hold
that, and forcing one recreates the sector_move defect one table over. This
mirrors `document_mentions`, the only many-to-many subject linkage that already
exists, including its role/relationship distinction.

WHAT THIS MODULE DOES NOT DO. It never mints a security identity. Security guids
come from the registry via `cio_subject_guid.lookup_subject`, which is lookup-only
by design — "memory is not an identity authority". Non-security subjects
(sector/industry/theme/strategy) are deterministic UUIDv5 over their canonical
name, minted by `ticker_knowledge_graph.entity_guid`, which already owns that
namespace. Nothing new is invented here; two dark modules are promoted.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. A subject link may change what the
desk is ABOUT; it can never change what the desk DOES.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable, Mapping

from scripts.lib.research_identity import normalize_sector
from scripts.lib.ticker_knowledge_graph import entity_guid
from scripts.lib.tradeai_record_envelope import ENTITY_TYPES, entity_ref

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "NarrativeSubjectLink@v1"

NO_CONSUMER_REASON = (
    "Phase 1 of the narrative-identity plan builds the spine; Phase 2 gives it its "
    "first production caller in material_change_detector.persist(), which is the "
    "single point where a sector_move stops being stamped with a security guid. "
    "Declared rather than silently inherited: this entry must be DELETED by the "
    "Phase 2 commit, and a reviewer seeing it survive past Phase 2 should treat "
    "that as the defect."
)


#: The six subject types an operator asked every narrative lane to carry, mapped
#: onto the envelope's existing vocabulary. ENTITY_TYPES is a superset; this is
#: the subset a narrative may be ABOUT. Deliberately not widened: CATALYST and
#: CALENDAR_EVENT are events, not subjects, and belong on the event spine.
NARRATIVE_SUBJECT_TYPES = ("SECURITY", "SECTOR", "INDUSTRY", "THEME", "PORTFOLIO", "STRATEGY")

#: entity_guid() kind for each non-security type. SECURITY is absent on purpose:
#: it is resolved from the registry, never minted from a name.
_MINT_KIND = {
    "SECTOR": "sector",
    "INDUSTRY": "industry",
    "THEME": "theme",
    "STRATEGY": "strategy",
    "PORTFOLIO": "portfolio",
}

RELATIONSHIPS = ("subject", "mentioned", "from", "to", "peer")

CONFIDENCE_CONFIRMED = "CONFIRMED"
CONFIDENCE_CANDIDATE = "CANDIDATE"
CONFIDENCE_LEGACY = "UNKNOWN_LEGACY"


class SubjectTypeRejected(ValueError):
    """An entity_type outside NARRATIVE_SUBJECT_TYPES.

    `tradeai_record_envelope.entity_ref` silently downgrades an unknown type to
    "OTHER" — which is not even in ENTITY_TYPES. That is fine for a permissive
    envelope and wrong for a subject link: a typo would produce a row that joins
    to nothing and reports no error. Fail loudly instead.
    """


def _link_guid(row_guid: str, subject_guid: str, relationship: str) -> str:
    """UUIDv5 on the same convention as the rest of the spine.

    `tradeai:` prefix, NAMESPACE_URL, pure function of its inputs — so
    re-ingestion and replay are idempotent and a link never duplicates.
    """
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"tradeai:narrative_link:{row_guid}|{subject_guid}|{relationship}",
    ))


def canonical_name(entity_type: str, value: Any) -> str | None:
    """Canonicalise a subject name BEFORE it is minted.

    Load-bearing. `entity_guid` casefolds but does not canonicalise, so
    "Consumer Cyclical" and "Consumer Discretionary" would mint two different
    GUIDs for one sector, and the rollup this whole effort exists to enable would
    silently split. `normalize_sector` maps 16 feed spellings onto 11 canonical
    GICS names and returns None for a non-sector (a fund mandate is not a sector)
    — None is a result, not a failure.
    """
    et = str(entity_type or "").strip().upper()
    raw = str(value or "").strip()
    if not raw:
        return None
    if et == "SECTOR":
        return normalize_sector(raw)
    return raw


def resolve_subject(
    entity_type: str,
    value: Any,
    *,
    relationship: str = "subject",
    symbol_lookup: Any = None,
    root: Any = None,
) -> dict[str, Any] | None:
    """Resolve ONE subject to an entity_ref carrying a guid, or None.

    Returns None rather than a partial ref when identity cannot be established —
    a link with a null guid joins to nothing and would misreport coverage. The
    caller decides whether that is a miss worth recording.

    SECURITY is resolved through the registry (lookup only). Everything else is
    minted deterministically from its canonical name.
    """
    et = str(entity_type or "").strip().upper()
    if et not in NARRATIVE_SUBJECT_TYPES:
        raise SubjectTypeRejected(
            f"{et!r} is not a narrative subject type; expected one of {NARRATIVE_SUBJECT_TYPES}"
        )
    if relationship not in RELATIONSHIPS:
        raise SubjectTypeRejected(f"unknown relationship {relationship!r}")

    name = canonical_name(et, value)
    if not name:
        return None

    if et == "SECURITY":
        lookup = symbol_lookup
        if lookup is None:
            from scripts.lib.cio_subject_guid import lookup_subject as lookup
        found = lookup(name, root=root) if root is not None else lookup(name)
        guid = (found or {}).get("subject_guid")
        if not guid:
            return None
        ref = entity_ref(entity_type="SECURITY", guid=guid,
                         semantic_subject=name, relationship=relationship)
        ref["confidence"] = (found or {}).get("identity_status") or CONFIDENCE_CANDIDATE
        return ref

    guid = entity_guid(_MINT_KIND[et], name)
    if not guid:
        return None
    ref = entity_ref(entity_type=et, guid=guid,
                     semantic_subject=name, relationship=relationship)
    ref["confidence"] = CONFIDENCE_CONFIRMED
    return ref


def build_links(
    *,
    row_guid: str,
    source_table: str,
    source_id: Any,
    subjects: Iterable[Mapping[str, Any]],
    author_agent_id: str = "cio",
    symbol_lookup: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the link rows for one narrative. Returns (links, misses).

    Misses are returned, never swallowed. `cio_subject_guid` distinguishes
    RESOLVED / UNRESOLVED / LOOKUP_FAILED / NOT_APPLICABLE precisely so an
    unreadable registry is not mistaken for a negative answer, and coverage stays
    measurable rather than optimistic.
    """
    from scripts.lib.comms.agent_contracts import KNOWN_AGENTS

    if author_agent_id not in KNOWN_AGENTS:
        raise SubjectTypeRejected(
            f"unknown author_agent_id {author_agent_id!r}; expected one of {sorted(KNOWN_AGENTS)}"
        )

    links: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    seen: set[str] = set()

    for spec in subjects or []:
        et = spec.get("entity_type")
        value = spec.get("value")
        rel = spec.get("relationship", "subject")
        ref = resolve_subject(et, value, relationship=rel, symbol_lookup=symbol_lookup)
        if ref is None:
            misses.append({"entity_type": et, "value": value, "relationship": rel})
            continue
        lg = _link_guid(row_guid, ref["entity_guid"], rel)
        if lg in seen:
            continue
        seen.add(lg)
        links.append({
            "link_guid": lg,
            "row_guid": row_guid,
            "source_table": source_table,
            "source_id": str(source_id),
            "entity_type": ref["entity_type"],
            "subject_guid": ref["entity_guid"],
            "semantic_subject": ref["semantic_subject"],
            "relationship": rel,
            "confidence": ref.get("confidence") or CONFIDENCE_CANDIDATE,
            "author_agent_id": author_agent_id,
            "schema_version": SCHEMA,
        })
    return links, misses


__all__ = [
    "SCHEMA",
    "AUTHORITY",
    "MBI",
    "NARRATIVE_SUBJECT_TYPES",
    "RELATIONSHIPS",
    "CONFIDENCE_CONFIRMED",
    "CONFIDENCE_CANDIDATE",
    "CONFIDENCE_LEGACY",
    "SubjectTypeRejected",
    "canonical_name",
    "resolve_subject",
    "build_links",
]
