"""IntelligenceCoverageMatrix@v2 — SUPPORTED / MISSING / NOT_APPLICABLE.

Does not optimize for FULL. Portfolio-level producers do not need a security GUID.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_intelligence_fabric import AUTHORITY, COVERAGE_FLAGS, MBI, _PRODUCERS

SCHEMA = "IntelligenceCoverageMatrix@v2"
DIMS = (
    "SOURCE",
    "IDENTITY",
    "MATERIALITY",
    "PERSISTENCE",
    "CONTEXT_ENVELOPE",
    "GUI",
    "RESEARCH_TRIGGER",
    "OUTCOME_LINKAGE",
)
FLAG_TO_DIM = {
    "SOURCE_EXISTS": "SOURCE",
    "IDENTITY_RESOLVED": "IDENTITY",
    "MATERIALITY_SUPPORTED": "MATERIALITY",
    "PERSISTENT_STATE_SUPPORTED": "PERSISTENCE",
    "CONTEXT_ENVELOPE_SUPPORTED": "CONTEXT_ENVELOPE",
    "GUI_VISIBLE": "GUI",
    "RESEARCH_TRIGGER_SUPPORTED": "RESEARCH_TRIGGER",
    "OUTCOME_LINKAGE": "OUTCOME_LINKAGE",
    "OUTCOME_LINKED": "OUTCOME_LINKAGE",
}
NA_IDENTITY_SCOPES = {"portfolio", "macro", "calendar", "decision"}
# R17 closures: capability exists in code paths added this tranche.
R17_SUPPORTED = {
    "holdings": {"OUTCOME_LINKAGE"},
    "positions": {"OUTCOME_LINKAGE"},
    "cash": {"OUTCOME_LINKAGE"},
    "portfolio_allocation": {"OUTCOME_LINKAGE"},
    "risk": {"CONTEXT_ENVELOPE", "OUTCOME_LINKAGE"},
    "stop_advisory": {"CONTEXT_ENVELOPE", "GUI", "OUTCOME_LINKAGE"},
    "watch_reentry": {"CONTEXT_ENVELOPE", "GUI", "OUTCOME_LINKAGE"},
    "sector_rotation": {"PERSISTENCE", "CONTEXT_ENVELOPE", "GUI", "RESEARCH_TRIGGER", "OUTCOME_LINKAGE"},
    "industry": {"PERSISTENCE", "CONTEXT_ENVELOPE", "GUI", "RESEARCH_TRIGGER", "OUTCOME_LINKAGE"},
    "macro_regime": {"RESEARCH_TRIGGER"},
    "catalysts": {"GUI", "OUTCOME_LINKAGE"},
    "earnings": {"GUI", "OUTCOME_LINKAGE"},
    "sec_primary": {"CONTEXT_ENVELOPE", "GUI", "OUTCOME_LINKAGE"},
    "news": {"CONTEXT_ENVELOPE", "GUI", "OUTCOME_LINKAGE"},
    "rag": {"GUI", "OUTCOME_LINKAGE"},
    "specialist_artifacts": {"CONTEXT_ENVELOPE", "GUI", "MATERIALITY"},
    "research_challenges": {"CONTEXT_ENVELOPE", "GUI", "OUTCOME_LINKAGE"},
    "notifications": {"CONTEXT_ENVELOPE"},
    "action_ledger": {"CONTEXT_ENVELOPE"},
    "plans": {"CONTEXT_ENVELOPE"},
}


def _na(producer: dict[str, Any], dim: str) -> bool:
    scope = str(producer.get("entity_scope") or "")
    if dim == "IDENTITY" and scope in NA_IDENTITY_SCOPES:
        return True
    if dim == "RESEARCH_TRIGGER" and producer.get("research_trigger_eligible") is False:
        return True
    if dim == "OUTCOME_LINKAGE" and producer.get("producer_id") == "operator_policy":
        return True
    if dim == "OUTCOME_LINKAGE" and scope in {"macro", "calendar"}:
        return True
    if dim == "MATERIALITY" and producer.get("producer_id") in {"outcomes", "lessons"}:
        return True
    return False


def coverage_matrix_v2() -> dict[str, Any]:
    rows = []
    unexplained = []
    for raw in _PRODUCERS:
        dims: dict[str, str] = {}
        for flag in COVERAGE_FLAGS:
            dim = FLAG_TO_DIM[flag]
            if _na(raw, dim):
                dims[dim] = "NOT_APPLICABLE"
                continue
            closed = dim in (R17_SUPPORTED.get(raw["producer_id"]) or set())
            present = bool(raw["coverage"].get(flag)) or closed
            dims[dim] = "SUPPORTED" if present else "MISSING"
        missing = [d for d, s in dims.items() if s == "MISSING"]
        if missing:
            unexplained.append({"producer_id": raw["producer_id"], "missing": missing})
        rows.append({
            "producer_id": raw["producer_id"],
            "entity_scope": raw["entity_scope"],
            "dimensions": dims,
            "missing": missing,
            "supported_n": sum(1 for s in dims.values() if s == "SUPPORTED"),
            "na_n": sum(1 for s in dims.values() if s == "NOT_APPLICABLE"),
        })
    return {
        "schema": SCHEMA,
        "dimensions": list(DIMS),
        "states": ["SUPPORTED", "MISSING", "NOT_APPLICABLE"],
        "rows": rows,
        "producer_n": len(rows),
        "unexplained_missing": unexplained,
        "unexplained_missing_n": len(unexplained),
        "not_optimized_for_full": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
