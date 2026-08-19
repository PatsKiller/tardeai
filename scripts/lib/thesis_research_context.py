"""ThesisResearchContext@v1 — full linkage to Cursor supply-plane IDs + #397 pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
from scripts.lib.symbol_thesis_materiality import classify_materiality
from scripts.lib.symbol_thesis_research import run_ri_pipeline_for_gap
from scripts.lib.symbol_thesis_supply_plane import (
    materiality_from_supply,
    resolve_candidate_to_evidence_refs,
)
from scripts.lib.symbol_universe import reconcile_universe

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ThesisResearchContext@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def build_thesis_research_context(
    symbol: str,
    *,
    root: Path | str | None = None,
    run_rag_pipeline: bool = True,
    question: str | None = None,
) -> dict[str, Any]:
    """Assemble operator/CIOcontext linking supply plane → RAG → thesis."""
    root = _root(root)
    sym = str(symbol).upper()
    fields = thesis_fields_for_symbol(sym, root=root)
    try:
        uni = reconcile_universe(root)
        urec = (uni.get("symbols") or {}).get(sym) or {}
    except Exception:
        urec = {"memberships": fields.get("memberships") or []}

    supply = resolve_candidate_to_evidence_refs(sym)
    mat = materiality_from_supply(sym, universe_rec=urec)

    pipeline = None
    if run_rag_pipeline and mat.get("expensive_thesis_work_allowed"):
        pipeline = run_ri_pipeline_for_gap(
            sym,
            question=question,
            root=root,
            retrieve=True,
            apply_acquire=False,
            apply_embed=False,
            call_llm=False,
        )
    elif run_rag_pipeline:
        pipeline = {
            "skipped": True,
            "reason": "materiality_tier_blocks_expensive_work",
            "tier": mat.get("materiality_tier"),
        }

    ec = (pipeline or {}).get("evidence_catalog") or {}
    plan = (pipeline or {}).get("acquisition_plan") or {}
    synth = (pipeline or {}).get("synthesis_packet") or {}

    # Example thesis-driven questions (form only — not forced conclusions)
    example_questions = {
        "SCHG": "Is large-cap growth leadership still supported under current rates/breadth?",
        "CSCO": "Has current fundamental/catalyst evidence improved enough to justify re-entry?",
        "ANET": "Does current growth/network demand evidence offset valuation/extension risk?",
    }

    return {
        "schema": SCHEMA,
        "as_of": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "symbol": sym,
        "thesis_id": fields.get("symbol_thesis_id") or symbol_thesis_id(sym),
        "thesis_version": fields.get("symbol_thesis_version"),
        "thesis_state": fields.get("thesis_state"),
        "portfolio_role": fields.get("portfolio_role"),
        "universe_memberships": fields.get("memberships") or urec.get("memberships") or [],
        "universe_membership_ids": [
            r for r in (supply.get("evidence_refs") or []) if r.get("kind") == "watchlist_membership"
        ],
        "research_discovery_ids": [
            r for r in (supply.get("evidence_refs") or [])
            if r.get("kind") == "watchlist_membership"
        ],
        "candidate_discovery_event_ids": [
            r.get("id") for r in (supply.get("evidence_refs") or [])
            if r.get("kind") == "candidate_discovery_event"
        ],
        "social_evidence_ids": [
            r.get("id") for r in (supply.get("evidence_refs") or [])
            if r.get("kind") == "social_sentiment_history"
        ],
        "watchlist_origin_system": (supply.get("watchlist_supply") or {}).get("origin_system"),
        "watchlist_origin_detail": (supply.get("watchlist_supply") or {}).get("origin_detail"),
        "thesis_evidence_state": supply.get("thesis_evidence_state"),
        "materiality": mat,
        "research_gap": (fields.get("research_gaps") or [None])[0],
        "specific_question": question or example_questions.get(sym) or (
            (pipeline or {}).get("specific_question")
        ),
        "rag_refs": {
            "supporting_n": ec.get("supporting_n"),
            "contradictory_n": ec.get("contradictory_n"),
            "support_query": ec.get("support_query"),
            "counter_query": ec.get("counter_query"),
            "sufficiency": ec.get("sufficiency"),
        },
        "structured_data_refs": {"structured_n": ec.get("structured_n")},
        "new_acquisition_refs": {
            "plan_status": plan.get("status"),
            "plan_id": plan.get("plan_id"),
            "steps": [
                {"family": s.get("family"), "targets": s.get("targets")}
                for s in (plan.get("steps") or [])
            ],
        },
        "source_registry_refs": {"uses": ["research_sources", "rag_status"]},
        "support_evidence": (ec.get("supporting_sample") or [])[:5],
        "contradictory_evidence": (ec.get("contradictory_sample") or [])[:5],
        "hermes_result": {
            "role": "synthesis_and_challenge_only",
            "is_acquisition_source": False,
            "gate": synth.get("gate"),
            "called": False,
        },
        "critic_result": None,
        "thesis_impact": None,
        "new_thesis_version": None,
        "cio_reassessment": None,
        "notification_outcome": None,
        "distinctions": {
            "watchlist_answers": "WHAT_DESERVES_ATTENTION",
            "thesis_answers": "WHAT_DO_WE_BELIEVE_AND_WHY",
            "cio_answers": "WHAT_SHOULD_WE_DO",
            "membership_is_not_evidence": True,
            "social_score_is_derived_only": True,
            "auto_apply_is_not_research_confidence": True,
            "bootstrap_floor_0_65_is_not_measured_alpha": True,
        },
        "cursor_dependency_sha": None,  # filled by caller/audit
    }
