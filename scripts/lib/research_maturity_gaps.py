"""Lane F maturity-gap helpers — does NOT replace scripts/lib/research_source_index.py.

Preserves canonical brave_router. Refuses obsolete dual-router. Evidence bar for
retention/curation stays DOCUMENTATION_ONLY until all legs proven.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchSourceIndexGap@v1"
EVIDENCE_BAR_SCHEMA = "RetentionCurationEvidenceBar@v1"
FORBIDDEN_ROUTER = "brave_research_router.py"
CANONICAL_ROUTER = "scripts/lib/brave_router.py"


def refuse_obsolete_research_router(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[2]
    obsolete = root / "scripts" / "lib" / FORBIDDEN_ROUTER
    canonical = root / "scripts" / "lib" / "brave_router.py"
    return {
        "obsolete_present": obsolete.is_file(),
        "canonical_present": canonical.is_file(),
        "canonical_path": CANONICAL_ROUTER,
        "verdict": "REFUSE_OBSOLETE" if obsolete.is_file() else "CANONICAL_ONLY",
    }


@dataclass
class SourceRecord:
    source_id: str
    url: str
    title: str = ""
    free_first_rank: int = 0
    cost_class: str = "free"
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "free_first_rank": self.free_first_rank,
            "cost_class": self.cost_class,
            "provenance": dict(self.provenance),
        }


def stable_source_id(url: str, *, title: str = "") -> str:
    digest = hashlib.sha256(f"{url.strip().lower()}|{title.strip().lower()}".encode()).hexdigest()
    return f"src_{digest[:24]}"


def build_source_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records: list[SourceRecord] = []
    for i, row in enumerate(rows):
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        title = str(row.get("title") or "")
        cost = str(row.get("cost_class") or "free").lower()
        sid = str(row.get("source_id") or stable_source_id(url, title=title))
        records.append(
            SourceRecord(
                source_id=sid,
                url=url,
                title=title,
                free_first_rank=0 if cost == "free" else 100 + i,
                cost_class=cost,
                provenance={"producer": "lane_f.gap_helper", "input_rank": i},
            )
        )
    records.sort(key=lambda r: (0 if r.cost_class == "free" else 1, r.free_first_rank, r.source_id))
    for i, r in enumerate(records):
        r.free_first_rank = i
    return {
        "schema_version": SCHEMA,
        "authority": AUTHORITY,
        "produced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": [r.to_dict() for r in records],
        "count": len(records),
    }


def retention_curation_evidence_bar(
    *,
    producer: bool,
    consumer: bool,
    schedule: bool,
    authoritative_mutation: bool,
    organic_evidence: bool,
) -> dict[str, Any]:
    legs = {
        "producer": producer,
        "consumer": consumer,
        "schedule": schedule,
        "authoritative_mutation": authoritative_mutation,
        "organic_evidence": organic_evidence,
    }
    return {
        "schema_version": EVIDENCE_BAR_SCHEMA,
        "legs": legs,
        "level": "PROVEN" if all(legs.values()) else "DOCUMENTATION_ONLY",
        "note": "Building toward the bar is in-scope; claiming above DOCUMENTATION_ONLY requires all legs.",
    }
