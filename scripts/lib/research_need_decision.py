"""ResearchNeedDecision@v1 — deterministic, no invented symbols."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
DECISIONS = (
    "NO_RESEARCH_NEEDED",
    "REFRESH_RESEARCH",
    "TARGETED_RESEARCH",
    "DEEP_RESEARCH",
)


def decide(inp: dict[str, Any]) -> dict[str, Any]:
    """Decide research intensity from explicit facts only."""
    symbol = str(inp.get("symbol") or "").upper()
    if not symbol or not symbol.replace(".", "").isalnum():
        return {
            "schema": "ResearchNeedDecision@v1",
            "decision": "NO_RESEARCH_NEEDED",
            "reason": "invalid_or_missing_symbol",
            "authority": AUTHORITY,
            "financial_action": False,
        }
    held = bool(inp.get("is_holding") or inp.get("held"))
    material = bool(inp.get("material") or inp.get("catalyst_material"))
    contradictions = bool(inp.get("contradictions"))
    research_age_h = inp.get("research_age_hours")
    complete = bool(inp.get("research_complete"))
    memory_cover = bool(inp.get("memory_coverage"))
    questions = list(inp.get("questions") or [])
    if not questions:
        questions = [
            {"dim": "structural_drivers", "q": f"What are the structural drivers for {symbol}?"},
            {"dim": "bear_case", "q": f"What is the bear case / falsifier for {symbol}?"},
            {"dim": "what_is_priced_in", "q": f"What is already priced in for {symbol}?"},
        ]
    # Stable ids from `dim`, so a question means the same thing to the producer,
    # the answerer and the critique. Without this the downstream enqueue
    # assigned positional q1/q2/q3 and the carry-forward pointed at ordinals.
    try:
        from scripts.lib.cio_question_ids import assign_ids

        questions = assign_ids(questions)
    except Exception:                                           # pragma: no cover
        pass
    if contradictions or (material and held and not complete):
        decision = "DEEP_RESEARCH"
        pri = "high"
        reason = "material_held_incomplete_or_contradiction"
    elif held and (research_age_h is None or float(research_age_h) > 24):
        decision = "REFRESH_RESEARCH"
        pri = "normal"
        reason = "held_research_stale_or_missing"
    elif material and not complete:
        decision = "TARGETED_RESEARCH"
        pri = "normal"
        reason = "material_gap"
    elif complete and memory_cover and not material:
        decision = "NO_RESEARCH_NEEDED"
        pri = "low"
        reason = "fresh_complete_covered"
    else:
        decision = "TARGETED_RESEARCH"
        pri = "low"
        reason = "default_gap"
    return {
        "schema": "ResearchNeedDecision@v1",
        "decision": decision,
        "symbol": symbol,
        "priority": pri,
        "reason": reason,
        "questions": questions,
        "freshness_requirement_hours": 24 if held else 72,
        "max_provider_class": "local_only",
        "authority": AUTHORITY,
        "financial_action": False,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
