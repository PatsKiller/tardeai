"""Audit institutional reference sources. Catalog membership is not knowledge.

Never claim copyrighted full text because a title is in the canon registry.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI
from scripts.lib.research_governance.source_catalog import load_sources
from scripts.lib.research_governance.mechanics.references import REFERENCES

SCHEMA = "ReferenceBrainAudit@v1"
DOCTRINE = Path(__file__).resolve().parents[2] / "config" / "operator_derived_doctrine.json"
CLAIMS = "data/cio/canon_claims.jsonl"
LIBRARY_HINTS = (
    "data/cio/file_library",
    "data/library",
    "file_library",
    "canon_sources",
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _doctrine() -> list[dict[str, Any]]:
    if not DOCTRINE.is_file():
        return []
    doc = json.loads(DOCTRINE.read_text(encoding="utf-8"))
    return list(doc.get("items") or [])


def _library_hits(root: Path, source_id: str, title: str) -> list[str]:
    hits = []
    needle = (source_id or "").replace("_", " ").lower()
    title_l = (title or "").lower()
    for rel in LIBRARY_HINTS:
        folder = root / rel
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if needle and needle[:12] in name:
                hits.append(str(path))
            elif title_l and title_l[:18] in name:
                hits.append(str(path))
    return hits


def audit_source(
    src: dict[str, Any],
    *,
    root: Path,
    doctrine_ids: set[str],
    mechanic_ids: set[str],
    claim_ids: set[str],
    drive_titles: set[str] | None,
    used_by_office: bool,
) -> dict[str, Any]:
    sid = str(src.get("source_id") or "")
    title = str(src.get("title") or "")
    full = str(src.get("full_text_status") or "NOT_FOUND_IN_FILE_LIBRARY")
    available = full not in {"", "NOT_FOUND_IN_FILE_LIBRARY"} and src.get("claim_status") != "SOURCE_CLAIM_INCOMPLETE"
    lib = _library_hits(root, sid, title)
    drive_hit = bool(drive_titles and title.lower() in drive_titles)
    derived = sid in doctrine_ids or sid in mechanic_ids
    claims = sid in claim_ids
    identified = bool(sid and title)
    source_available = bool(available or lib)  # lawful file present
    # Catalog + Drive docs about the catalog are not the book.
    return {
        "source_id": sid,
        "title": title,
        "authors": src.get("authors") or [],
        "source_type": src.get("source_type"),
        "canon_class": src.get("canon_class"),
        "license_class": src.get("license_class"),
        "catalog_full_text_status": full,
        "catalog_claim_status": src.get("claim_status"),
        "SOURCE_IDENTIFIED": identified,
        "SOURCE_AVAILABLE": source_available,
        "DERIVED_KNOWLEDGE_AVAILABLE": derived,
        "EMBEDDED": False,
        "RETRIEVABLE": derived or source_available or claims,
        "CITABLE": identified,
        "USED_BY_AGENT": bool(used_by_office and derived),
        "NOT_AVAILABLE": not source_available,
        "library_file_hits": lib,
        "drive_title_hit": drive_hit,
        "derived_doctrine": sid in doctrine_ids,
        "derived_mechanics": sid in mechanic_ids,
        "extracted_claims": claims,
        "note": (
            "catalog identity only; lawful full text not present"
            if not source_available else "lawful source file present"
        ),
    }


def audit_reference_brain(
    root: Path | str,
    *,
    drive_titles: list[str] | None = None,
    embeddings_probed: bool = False,
    embeddings_canon_hits: int | None = None,
) -> dict[str, Any]:
    """Ground truth for every catalogued source plus separately registered derived doctrine."""
    root_p = Path(root)
    sources = load_sources()
    doctrine = _doctrine()
    doctrine_ids = {str(i.get("source_id")) for i in doctrine}
    mechanic_ids = {sid for row in REFERENCES for sid in (row.get("source_ids") or [])}
    claims = _jsonl(root_p / CLAIMS)
    claim_ids = {str(r.get("source_id")) for r in claims if r.get("source_id")}
    drive_set = {t.lower() for t in (drive_titles or [])}
    rows = [
        audit_source(
            s, root=root_p, doctrine_ids=doctrine_ids, mechanic_ids=mechanic_ids,
            claim_ids=claim_ids, drive_titles=drive_set, used_by_office=True,
        )
        for s in sources
    ]
    derived_register = [
        {
            "knowledge_id": item.get("doctrine_id"),
            "knowledge_class": "operator_derived_doctrine",
            "source_id": item.get("source_id"),
            "provenance": "config/operator_derived_doctrine.json",
            "not_full_text": True,
            "SOURCE_IDENTIFIED": True,
            "SOURCE_AVAILABLE": False,
            "DERIVED_KNOWLEDGE_AVAILABLE": True,
            "RETRIEVABLE": True,
            "CITABLE": True,
            "USED_BY_AGENT": True,
        }
        for item in doctrine
    ]
    for row in REFERENCES:
        derived_register.append({
            "knowledge_id": row.get("mechanic"),
            "knowledge_class": "implemented_mechanic",
            "source_id": (row.get("source_ids") or [None])[0],
            "provenance": row.get("implementation_file"),
            "source_status": row.get("source_status"),
            "not_full_text": True,
            "SOURCE_IDENTIFIED": True,
            "SOURCE_AVAILABLE": False,
            "DERIVED_KNOWLEDGE_AVAILABLE": True,
            "RETRIEVABLE": True,
            "CITABLE": True,
            "USED_BY_AGENT": True,
        })
    n_ident = sum(1 for r in rows if r["SOURCE_IDENTIFIED"])
    n_avail = sum(1 for r in rows if r["SOURCE_AVAILABLE"])
    n_derived = sum(1 for r in rows if r["DERIVED_KNOWLEDGE_AVAILABLE"])
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "catalog_n": len(rows),
        "SOURCE_IDENTIFIED_n": n_ident,
        "SOURCE_AVAILABLE_n": n_avail,
        "DERIVED_KNOWLEDGE_AVAILABLE_n": n_derived,
        "NOT_AVAILABLE_n": sum(1 for r in rows if r["NOT_AVAILABLE"]),
        "extracted_claims_n": len(claims),
        "embeddings_probed": embeddings_probed,
        "embeddings_canon_hits": embeddings_canon_hits,
        "embeddings_note": (
            "production SQL not queried; acquisition queue states no catalog source is indexed"
            if not embeddings_probed else None
        ),
        "drive_titles_searched": sorted(drive_set),
        "catalog_is_not_a_corpus": True,
        "sources": rows,
        "derived_register": derived_register,
    }
