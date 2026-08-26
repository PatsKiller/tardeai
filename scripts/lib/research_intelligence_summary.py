"""ResearchIntelligenceSummary@v1 — human research, not raw JSON."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "ResearchIntelligenceSummary@v1"


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def from_research_result(row: dict[str, Any] | None) -> dict[str, Any]:
    r = row if isinstance(row, dict) else {}
    entity = _s(r.get("entity") or r.get("symbol") or r.get("name")) or "UNNAMED"
    found = _s(r.get("what_was_found") or r.get("finding") or r.get("summary") or r.get("narrative"))
    material = bool(r.get("material_change") or r.get("material"))
    return {
        "schema": SCHEMA,
        "entity": entity,
        "question": _s(r.get("question") or r.get("why_researched") or r.get("query")),
        "why_researched": _s(r.get("why_researched") or r.get("reason") or r.get("trigger")),
        "what_was_found": found or "No material finding recorded.",
        "material_change": material,
        "thesis_effect": _s(r.get("thesis_effect") or r.get("thesis_impact") or "NONE"),
        "decision_effect": _s(r.get("decision_effect") or r.get("decision_impact") or "NONE"),
        "confidence": r.get("confidence"),
        "sources": list(r.get("sources") or r.get("evidence_refs") or []),
        "unresolved_gaps": list(r.get("unresolved_gaps") or r.get("gaps") or []),
        "next_review": r.get("next_review") or r.get("next_review_at"),
        "as_of": r.get("as_of") or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def render_human(summary: dict[str, Any]) -> str:
    lines = [
        f"[RESEARCH] {summary.get('entity')}",
        f"Question: {summary.get('question') or '—'}",
        f"Why researched: {summary.get('why_researched') or '—'}",
        f"What was found: {summary.get('what_was_found')}",
        f"Material change: {'yes' if summary.get('material_change') else 'no'}",
        f"Thesis effect: {summary.get('thesis_effect')}",
        f"Decision effect: {summary.get('decision_effect')}",
    ]
    if summary.get("confidence") is not None:
        lines.append(f"Confidence: {summary.get('confidence')}")
    gaps = summary.get("unresolved_gaps") or []
    if gaps:
        lines.append("Unresolved gaps: " + "; ".join(str(g) for g in gaps[:6]))
    if summary.get("next_review"):
        lines.append(f"Next review: {summary.get('next_review')}")
    lines.append("READ_ONLY_ADVISORY — not an order.")
    return "\n".join(lines)
