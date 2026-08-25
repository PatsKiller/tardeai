"""R22 — Governed institutional CIO loop contract.

Continuous questions, not autonomous trading. Activation default OFF.
Consumes the same canonical identity/universe/graph/outcome fabric.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class

SCHEMA = "InstitutionalCioLoop@v1"
QUESTIONS = (
    "what_changed",
    "which_entities_affected",
    "what_we_already_know",
    "what_is_contradicted",
    "what_is_stale",
    "what_to_research",
    "what_changed_in_the_thesis",
    "operator_attention",
    "what_happened_after_prior_decisions",
    "what_we_are_learning",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cio_loop_cycle(
    *,
    evidence_class: str,
    answers: dict[str, Any] | None = None,
    impact: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R22", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    filled = dict(answers or {})
    slots = {q: filled.get(q) for q in QUESTIONS}
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "as_of": _now(),
        "questions": QUESTIONS,
        "slots": slots,
        "impact_candidate_set": impact,
        "calibration_ref": (calibration or {}).get("schema"),
        "learning_stage": (learning or {}).get("stage"),
        "autonomous_trading": False,
        "execution_separately_authorized": True,
        "canonical_contract": "TransfersonUniverseManifest@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }
