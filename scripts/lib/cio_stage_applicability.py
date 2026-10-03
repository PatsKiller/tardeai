"""StageApplicability@v1 — which lineage stages a recorded decision origin never has.

A deterministic rank calls no model and delegates to no specialist, so for its
decisions those stages are not missing evidence: they do not exist. Reading them
UNKNOWN overstated the gap. This contract lets the lineage projection say
NOT_APPLICABLE, with the reason, instead.

Rules (reviewed; operator-approved 2026-10-03, join design phase 2):

* Keyed ONLY on the ``decision_origin`` the producer recorded on the decision.
  A missing or unlisted origin applies no contract; the stage stays UNKNOWN.
* A decision that records any model evidence (``model``, ``model_used``,
  ``provider``, ``model_provider``) gets no contract at all, whatever its origin
  says, and neither does an LLM-produced surface (holdings): holdings decisions
  were labelled DETERMINISTIC_RANK while an LLM made them, and a stale label
  must never hide a model stage.
* Research stages are deliberately absent: deterministic surfaces still consume
  prior research state (material_scan records ticker_research_state_version,
  advisory records evidence_refs), so "no research" would be false.
* The projection consults this only after every matched row, after a producer
  stage_status, after UNWIRED and after a store outage (UNAVAILABLE).
"""
from __future__ import annotations

from typing import Any, Mapping

SCHEMA = "StageApplicability@v1"

_MODEL_EVIDENCE = ("model", "model_used", "provider", "model_provider", "model_route")
# Surfaces whose producer is an LLM regardless of the origin label they carry
# (holdings_llm_refresh emits only after parsing a model response).
_LLM_SURFACES = frozenset({"holdings"})

_NO_MODEL = "a deterministic rank calls no model"
_NO_SPECIALIST = "a deterministic rank delegates to no specialist"

_CONTRACT: dict[str, dict[str, str]] = {
    "DETERMINISTIC_RANK": {
        "model_route": _NO_MODEL,
        "counter_thesis": f"{_NO_MODEL}, so no counter-thesis is authored",
        "falsifier": f"{_NO_MODEL}, so no falsifier is authored",
        "specialist_delegation": _NO_SPECIALIST,
        "specialist_disagreement": _NO_SPECIALIST,
    },
}


def not_applicable_reason(decision: Mapping[str, Any] | None, stage: str) -> str | None:
    """The contract's reason this stage does not apply to this decision, else None."""
    if not isinstance(decision, Mapping):
        return None
    origin = str(decision.get("decision_origin") or "").strip().upper()
    reasons = _CONTRACT.get(origin)
    if not reasons or stage not in reasons:
        return None
    if any(str(decision.get(key) or "").strip() for key in _MODEL_EVIDENCE):
        return None
    if str(decision.get("surface") or "").strip().lower() in _LLM_SURFACES:
        return None
    return f"{SCHEMA}: producer recorded decision_origin={origin}; {reasons[stage]}"
