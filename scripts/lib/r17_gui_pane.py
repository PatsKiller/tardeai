"""Single-pane GUI projection for one ticker. Projection only, never ingestion."""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.r17_checkpoint_binding import learning_cockpit_from_store
from scripts.lib.r17_producer_links import envelope_extras
from scripts.lib.ticker_knowledge_graph import upgrade_record_guids
from scripts.lib.transferson_universe import get_identity_lineage, get_symbol

SCHEMA = "TickerIntelligencePane@v1"


def ticker_pane(
    root,
    manifest: dict[str, Any],
    symbol: str,
    *,
    profile: dict[str, Any] | None = None,
    thesis: dict[str, Any] | None = None,
    prior_thesis: dict[str, Any] | None = None,
    research_state: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    specialists: dict[str, Any] | None = None,
    feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {"symbol": symbol}
    ident = get_identity_lineage(manifest, symbol)
    profile = upgrade_record_guids(profile or {"symbol": symbol})
    cockpit = learning_cockpit_from_store(root)
    extras = envelope_extras()
    return {
        "schema": SCHEMA,
        "symbol": rec.get("symbol"),
        "gui_is_projection": True,
        "authoritative_portfolio_state": {
            "currently_held": rec.get("currently_held"),
            "tier": rec.get("current_research_tier"),
            "membership_reasons": rec.get("membership_reasons") or [],
        },
        "identity": ident,
        "issuer": profile.get("issuer_guid") or rec.get("issuer_guid"),
        "sector": rec.get("sector") or profile.get("sector"),
        "industry": rec.get("industry") or profile.get("industry"),
        "themes": profile.get("themes") or [],
        "peers": profile.get("peers") or [],
        "catalysts": rec.get("catalyst_guids") or profile.get("catalyst_guids") or [],
        "calendar": profile.get("calendar_events") or [],
        "macro_context": extras.get("RISK"),
        "seasonality": None,
        "current_thesis": thesis,
        "prior_thesis": prior_thesis,
        "research_state": research_state,
        "free_first_state": research_state.get("free_first") if isinstance(research_state, dict) else None,
        "llm_curation_history": research_state.get("curation") if isinstance(research_state, dict) else None,
        "contradictions": research_state.get("contradictions") if isinstance(research_state, dict) else [],
        "specialist_views": specialists or extras.get("SPECIALISTS"),
        "operator_feedback": feedback or [],
        "decision": decision,
        "checkpoint": {"counts": cockpit.get("checkpoint_counts")},
        "outcome": {"observations_n": cockpit.get("observations_n")},
        "lesson_hypothesis_state": {
            "lessons_n": cockpit.get("lessons_n"),
            "hypotheses_n": cockpit.get("hypotheses_n"),
            "max_unattended_stage": "REVIEW_READY",
        },
        "subject_guid": identity_safe_subject(rec),
        "ticker_guid_is_not_security": True,
        "ingestion_forbidden": True,
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "financial_action": False,
    }
