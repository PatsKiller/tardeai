"""Advisory Desk: proactive operator briefing, not a dashboard formatter."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI

SCHEMA = "AdvisoryBrief@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compose_brief(
    cycle: dict[str, Any],
    *,
    prior_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    syn = cycle.get("synthesis") or {}
    rec = syn.get("recommendation")
    prior_rec = (prior_brief or {}).get("recommendation")
    unchanged = prior_rec == rec and (prior_brief or {}).get("symbol") == cycle.get("symbol")
    theories = cycle.get("theories") or {}
    canon = cycle.get("canon") or {}
    impact = cycle.get("impact") or {}
    retrieval = cycle.get("retrieval") or {}
    return {
        "schema": SCHEMA,
        "as_of": _now(),
        "symbol": cycle.get("symbol"),
        "what_changed": (cycle.get("steps") or [{}])[0],
        "why_it_matters": syn.get("reasons"),
        "where_the_system_disagrees": {
            "canon_disagreement": canon.get("disagreement_visible"),
            "competing_theories": list((theories.get("theories") or {}).keys()),
            "disagree_scanner": rec == "DISAGREE_DETERMINISTIC_SETUP",
        },
        "new_opportunities": [c.get("symbol") for c in (impact.get("candidates") or [])],
        "thesis_state": rec,
        "research_discoveries": (cycle.get("sector") or {}).get("discovered_related_tickers") or [],
        "theory_changes": {k: (v or {}).get("status") for k, v in (theories.get("theories") or {}).items()},
        "upcoming_catalysts": None,
        "lessons_from_outcomes": [h.get("knowledge_id") for h in (retrieval.get("hits") or []) if h.get("knowledge_class") == "measured_outcome"],
        "operator_memory_used": [h.get("knowledge_id") for h in (retrieval.get("hits") or []) if h.get("knowledge_class") == "operator_feedback"],
        "deserves_attention_now": rec in {"RESEARCH_MORE", "DISAGREE_DETERMINISTIC_SETUP", "THESIS_CHANGED", "TRIM", "EXIT_CANDIDATE"},
        "recommendation": rec,
        "unchanged_advice_suppressed": bool(unchanged),
        "advisory_only": True,
        "autonomous_trading": False,
        "influence_trace": cycle.get("influence_trace"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
