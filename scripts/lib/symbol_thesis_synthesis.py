"""Hermes / DeepSeek Flash — synthesis & challenge ONLY (not acquisition).

After evidence has been:
  1) retrieved from existing RAG (supporting + contradictory),
  2) optionally acquired via RI multi-source plane,
  3) cataloged with provenance,
  4) curated (rag_status / research_sources),
  5) embedded into existing content_embeddings,

THEN this module builds a synthesis/challenge packet for Hermes or DeepSeek Flash
and optionally applies the result via reconcile_symbol_thesis.

Never treats Hermes/Flash as a research *source*.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisSynthesisPacket@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_synthesis_packet(
    symbol: str,
    *,
    question: str,
    evidence_catalog: dict[str, Any],
    acquisition_plan: Optional[dict[str, Any]] = None,
    thesis_fields: Optional[dict[str, Any]] = None,
    portfolio_role: str = "",
) -> dict[str, Any]:
    """Packet for Hermes/Flash: synthesize + challenge using cataloged evidence only."""
    supporting = list((evidence_catalog or {}).get("supporting") or [])
    contradictory = list((evidence_catalog or {}).get("contradictory") or [])
    structured = [
        s for s in ((evidence_catalog or {}).get("structured") or [])
        if s.get("source_type") != "research_sources_registry"
    ]
    sufficiency = (evidence_catalog or {}).get("sufficiency") or {}
    plan = acquisition_plan or {}

    if not sufficiency.get("sufficient_for_synthesis") and plan.get("status") == "ACQUISITION_PLANNED":
        gate = "BLOCKED_PENDING_ACQUISITION_AND_CURATION"
    elif not (supporting or contradictory or structured):
        gate = "BLOCKED_NO_EVIDENCE"
    else:
        gate = "READY_FOR_SYNTHESIS"

    def _slim(rows: list[dict[str, Any]], n: int = 8) -> list[dict[str, Any]]:
        out = []
        for r in rows[:n]:
            out.append({
                "evidence_id": r.get("evidence_id"),
                "polarity": r.get("polarity"),
                "source_type": r.get("source_type"),
                "source_id": r.get("source_id"),
                "title": r.get("title"),
                "fact": (r.get("fact") or "")[:240],
                "freshness": r.get("freshness"),
                "quality": r.get("quality"),
                "rag_status": r.get("rag_status"),
                "rag_score": r.get("rag_score"),
            })
        return out

    instructions = {
        "role": "thesis_synthesizer_and_challenger",
        "not_a_source": True,
        "must": [
            "Use ONLY the cataloged evidence_ids provided.",
            "Produce a living symbol thesis draft: summary, stance, why_owned_or_watched,"
            " why_exited (or DATA_UNAVAILABLE), evidence_for, counter_evidence,"
            " invalidation_conditions, research_gaps, what_changes_my_mind.",
            "Explicitly weigh contradictory evidence; do not suppress the bear case.",
            "Cite evidence_ids for every material claim.",
            "If evidence is thin, set stance empty and leave research_gaps specific.",
            "Never invent broker/order/stop authority. READ_ONLY_ADVISORY.",
        ],
        "must_not": [
            "Do not invent facts not present in the catalog.",
            "Do not treat yourself (Hermes/Flash) as primary research acquisition.",
            "Do not grant RE_ENTER / ADD execution authority.",
            "Do not crawl additional web sources in this step.",
        ],
    }

    return {
        "schema": SCHEMA,
        "packet_id": "tsp_" + _digest(symbol, question, gate),
        "as_of": _now(),
        "symbol": symbol.upper(),
        "question": question,
        "portfolio_role": portfolio_role or (thesis_fields or {}).get("portfolio_role"),
        "prior_thesis": {
            "version": (thesis_fields or {}).get("symbol_thesis_version"),
            "state": (thesis_fields or {}).get("thesis_state"),
            "stance": (thesis_fields or {}).get("thesis_stance"),
            "summary": (thesis_fields or {}).get("thesis_summary"),
        },
        "gate": gate,
        "evidence": {
            "supporting": _slim(supporting),
            "contradictory": _slim(contradictory),
            "structured": _slim(structured),
            "sufficiency": sufficiency,
        },
        "acquisition_plan_status": plan.get("status"),
        "acquisition_plan_id": plan.get("plan_id"),
        "llm_lanes": {
            "allowed": ["hermes_local", "deepseek_flash"],
            "role": "synthesis_and_challenge_only",
            "acquisition_source": False,
        },
        "instructions": instructions,
        "output_contract": {
            "summary": "str >= 40 chars",
            "stance": "hold|watch|add|trim|avoid|''",
            "why_owned_or_watched": "str|DATA_UNAVAILABLE",
            "why_exited": "str|DATA_UNAVAILABLE|omit",
            "evidence_for": ["evidence_id or short claim"],
            "counter_evidence": ["evidence_id or short claim"],
            "invalidation_conditions": ["str"],
            "research_gaps": ["specific unanswered question"],
            "what_changes_my_mind": ["str"],
            "cited_evidence_ids": ["ev_..."],
        },
        "authority": AUTHORITY,
        "financial_action": False,
        "call_llm": False,  # dry default — caller must opt in
    }


def apply_synthesis_to_thesis(
    symbol: str,
    synthesis_result: dict[str, Any],
    *,
    packet: dict[str, Any],
    root=None,
    publish: bool = True,
    notify: bool = False,
) -> dict[str, Any]:
    """Map synthesizer output → reconcile_symbol_thesis (material versioning)."""
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    if (packet or {}).get("gate") not in {"READY_FOR_SYNTHESIS"}:
        return {
            "ok": False,
            "error": "synthesis_gate_blocked",
            "gate": (packet or {}).get("gate"),
            "authority": AUTHORITY,
        }

    evidence = {
        "summary": synthesis_result.get("summary"),
        "stance": synthesis_result.get("stance"),
        "why_owned_or_watched": synthesis_result.get("why_owned_or_watched"),
        "why_exited": synthesis_result.get("why_exited"),
        "evidence_for": list(synthesis_result.get("evidence_for") or []),
        "counter_evidence": list(synthesis_result.get("counter_evidence") or []),
        "invalidation_conditions": list(synthesis_result.get("invalidation_conditions") or []),
        "research_gaps": list(synthesis_result.get("research_gaps") or []),
        "what_changes_my_mind": list(synthesis_result.get("what_changes_my_mind") or []),
        "portfolio_role": synthesis_result.get("portfolio_role") or packet.get("portfolio_role"),
        "financial_truth_refs": list(synthesis_result.get("cited_evidence_ids") or []),
        "result_id": synthesis_result.get("result_id") or packet.get("packet_id"),
    }
    review = reconcile_symbol_thesis(
        symbol,
        trigger="ri_synthesis_challenge",
        evidence=evidence,
        root=root,
        publish=publish,
        notify=notify,
        actor_id="symbol_thesis_synthesis",
    )
    return {
        "ok": True,
        "review": review,
        "hermes_used_as": "synthesis_and_challenge_only",
        "acquisition_source": False,
        "authority": AUTHORITY,
    }
