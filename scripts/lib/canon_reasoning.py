"""Canon as a reasoning framework, not a commandment gate.

Never: "Graham says X, therefore reject."
Always: ask better questions, surface disagreement, label SOURCE_UNAVAILABLE.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI
from scripts.lib.institutional_knowledge_fabric import retrieve
from scripts.lib.reference_brain_audit import audit_reference_brain

SCHEMA = "CanonReasoning@v1"
STANCES = ("CANON_SUPPORTS", "CANON_CHALLENGES", "CANON_NOT_RELEVANT", "SOURCE_UNAVAILABLE")


def reason_with_canon(
    root,
    *,
    question: str,
    symbol: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve doctrine/mechanics and classify stance. No deterministic reject."""
    audit = audit_reference_brain(root)
    retrieved = retrieve(
        root, query=question, symbol=symbol,
        knowledge_classes=["operator_derived_doctrine", "canonical_framework", "primary_research"],
        limit=16,
    )
    by_source: dict[str, list[dict[str, Any]]] = {}
    views: list[dict[str, Any]] = []
    for hit in retrieved.get("hits") or []:
        sid = str(hit.get("source_id") or "unmapped")
        by_source.setdefault(sid, []).append(hit)
        catalog = next((s for s in audit["sources"] if s["source_id"] == sid), None)
        unavailable = True if catalog is None else bool(catalog.get("NOT_AVAILABLE"))
        role = (hit.get("provenance") or {}).get("role") or "question"
        if unavailable:
            stance = "SOURCE_UNAVAILABLE"
        elif role == "challenge":
            stance = "CANON_CHALLENGES"
        elif role == "question":
            stance = "CANON_SUPPORTS"
        else:
            stance = "CANON_NOT_RELEVANT"
        views.append({
            "source_id": sid if sid != "unmapped" else None,
            "knowledge_id": hit.get("knowledge_id"),
            "stance": stance,
            "prompt": hit.get("statement"),
            "not_a_gate": True,
            "full_text_available": bool(catalog and catalog.get("SOURCE_AVAILABLE")),
        })
    role_set = {(h.get("provenance") or {}).get("role") for h in (retrieved.get("hits") or [])}
    disagreement = (
        len({v["stance"] for v in views if v["stance"] in {"CANON_SUPPORTS", "CANON_CHALLENGES"}}) > 1
        or ({"question", "challenge"} <= role_set)
    )
    return {
        "schema": SCHEMA,
        "question": question,
        "symbol": symbol,
        "views": views,
        "disagreement_visible": disagreement,
        "deterministic_reject": False,
        "evidence_inspected": bool(evidence),
        "used_knowledge_ids": retrieved.get("used_knowledge_ids") or [],
        "catalog_available_n": audit.get("SOURCE_AVAILABLE_n"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "stances": STANCES,
    }
