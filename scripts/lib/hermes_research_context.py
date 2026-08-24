"""HermesResearchContext@v2 — next iteration starts from persisted state."""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HermesResearchContext@v2"


def build_context(
    *,
    identity: dict[str, Any],
    curation: dict[str, Any] | None,
    state: dict[str, Any] | None,
    thesis: dict[str, Any] | None = None,
    gaps: list[dict[str, Any]] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    operator_feedback: list[dict[str, Any]] | None = None,
    evidence_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Never default to 'research XYZ'. Question is WHAT CHANGED?"""
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "question": "WHAT_CHANGED",
        "forbidden_default": "tell_me_about_symbol",
        "security_identity": identity,
        "last_curation_summary": curation,
        "ticker_research_state": state,
        "current_symbol_thesis": thesis,
        "open_gaps": gaps or [],
        "unresolved_contradictions": contradictions or [],
        "current_event_catalyst_state": events or [],
        "sector_industry_theme": {
            "sector_guid": (identity or {}).get("sector_guid") or (state or {}).get("sector_guid"),
            "industry_guid": (identity or {}).get("industry_guid") or (state or {}).get("industry_guid"),
            "theme_guids": (identity or {}).get("theme_guids") or (state or {}).get("theme_guids") or [],
        },
        "lateral_vertical_relationships": (state or {}).get("relationships") or (identity or {}).get("relationships") or [],
        "operator_feedback": operator_feedback or [],
        "new_evidence_delta_only": evidence_delta or {"changed": False},
        "llm_eligible": False,
    }
