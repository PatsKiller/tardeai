"""Research dossier — unions primary-subject and mentioned-security evidence.

Does not conflate primary with mentioned. Deduplicates by research_id / content
hash. Ranks by authoritative_source_rank then capture time.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Sequence

from scripts.lib.research_object import ResearchObject, SCHEMA as RESEARCH_SCHEMA

SCHEMA = "ResearchDossier@v1"
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DossierRecord:
    dossier_id: str
    subject_guid: str
    primary_symbol: str
    primary_evidence: list[dict[str, Any]] = field(default_factory=list)
    mentioned_evidence: list[dict[str, Any]] = field(default_factory=list)
    research_ids: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA
    built_at: str = ""
    ranking_key: str = "authoritative_source_rank,captured_at"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def all_research_ids(self) -> list[str]:
        return list(self.research_ids)


def _as_dict(obj: ResearchObject | dict[str, Any]) -> dict[str, Any]:
    if isinstance(obj, ResearchObject):
        return obj.to_dict()
    return dict(obj)


def _sort_key(row: dict[str, Any]) -> tuple:
    rank = int(row.get("authoritative_source_rank") or 99)
    captured = str(row.get("captured_at") or "")
    return (rank, captured)


def dedupe_research(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate research evidence.

    Primary rows key on research_id / content_hash.
    Mentioned-security rows key on (research_id, mentioned_symbol) so a
    multi-security article retains every mention rather than collapsing.
    """
    by_key: dict[str, dict[str, Any]] = {}
    by_hash: dict[str, str] = {}
    for raw in rows:
        row = _as_dict(raw)
        rid = row.get("research_id")
        ch = row.get("content_hash")
        if not rid:
            raise ValueError("research row missing research_id")
        if row.get("evidence_role") == "mentioned_security":
            key = f"{rid}|mentioned|{row.get('mentioned_symbol') or ''}"
        else:
            key = f"{rid}|primary"
        if key in by_key:
            if _sort_key(row) < _sort_key(by_key[key]):
                by_key[key] = row
            continue
        # content_hash dedupe only for primary rows
        if row.get("evidence_role") != "mentioned_security" and ch and ch in by_hash:
            existing_key = by_hash[ch]
            if _sort_key(row) < _sort_key(by_key[existing_key]):
                del by_key[existing_key]
                by_key[key] = row
                by_hash[ch] = key
            continue
        by_key[key] = row
        if row.get("evidence_role") != "mentioned_security" and ch:
            by_hash[ch] = key
    return sorted(by_key.values(), key=_sort_key)


def build_dossier(
    *,
    subject_guid: str,
    primary_symbol: str,
    research_objects: Sequence[ResearchObject | dict[str, Any]],
    clock: Optional[Clock] = None,
) -> DossierRecord:
    """Union primary-subject and mentioned-security evidence without conflating."""
    if not subject_guid:
        raise ValueError("subject_guid required")
    if not primary_symbol:
        raise ValueError("primary_symbol required")
    clock = clock or _utc_now
    now = clock()

    primary: list[dict[str, Any]] = []
    mentioned: list[dict[str, Any]] = []
    sym_u = primary_symbol.upper()

    for raw in research_objects:
        row = _as_dict(raw)
        if not row.get("research_id"):
            raise ValueError("not a research object")
        mentions = row.get("mentions") or []
        is_primary_subject = row.get("subject_guid") == subject_guid
        entry = {
            "research_id": row["research_id"],
            "title": row.get("title"),
            "source_url": row.get("source_url_canonical") or row.get("source_url"),
            "content_hash": row.get("content_hash"),
            "authoritative_source_rank": row.get("authoritative_source_rank"),
            "captured_at": row.get("captured_at"),
            "published_at": row.get("published_at"),
            "mentions": mentions,
            "provenance": row.get("provenance"),
        }
        if is_primary_subject:
            primary.append(dict(entry, evidence_role="primary_subject"))
        # Multi-security retention: every non-primary mention stays as its own
        # evidence row. Never collapse mentioned securities into the primary.
        for m in mentions:
            role = m.get("role") or "mentioned"
            msym = str(m.get("symbol") or "").upper()
            if role == "primary":
                continue
            # Retain on this dossier when the article is about our subject OR
            # the mention names our symbol OR we are building a multi-sec union.
            if is_primary_subject or msym == sym_u or m.get("subject_guid") == subject_guid:
                mentioned.append(
                    dict(
                        entry,
                        evidence_role="mentioned_security",
                        mentioned_symbol=msym or m.get("symbol"),
                        mentioned_subject_guid=m.get("subject_guid"),
                    )
                )
        # Article whose primary is another symbol but mentions ours.
        if not is_primary_subject:
            for m in mentions:
                msym = str(m.get("symbol") or "").upper()
                if msym == sym_u or m.get("subject_guid") == subject_guid:
                    mentioned.append(
                        dict(
                            entry,
                            evidence_role="mentioned_security",
                            mentioned_symbol=msym,
                            mentioned_subject_guid=m.get("subject_guid") or subject_guid,
                        )
                    )
                    break

    primary_d = dedupe_research(primary)
    mentioned_d = dedupe_research(mentioned)
    # Ensure multi-security articles are not truncated to single-subject.
    ids = []
    for row in primary_d + mentioned_d:
        rid = row["research_id"]
        if rid not in ids:
            ids.append(rid)

    dossier_id = f"dossier:{subject_guid}:{primary_symbol.upper()}"
    return DossierRecord(
        dossier_id=dossier_id,
        subject_guid=subject_guid,
        primary_symbol=primary_symbol.upper(),
        primary_evidence=primary_d,
        mentioned_evidence=mentioned_d,
        research_ids=ids,
        built_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
