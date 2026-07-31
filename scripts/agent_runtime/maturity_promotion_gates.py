"""Read-only promotion gate board for one agent."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents.definitions import FLEET
from .agents.maturity_gates import evaluate_gates, MATURITY_GATE_CONTRACT
from .maturity_observability import collect_runtime_evidence, maturity_agent_payload


PROMOTION_GATES_CONTRACT = "agent-runtime-promotion-gates-v1"


def promotion_gates_payload(root: Path, agent_id: str, *, reader: Any | None = None) -> dict[str, Any] | None:
    observation = maturity_agent_payload(root, agent_id, reader=reader)
    if observation is None:
        return None
    if agent_id not in FLEET:
        return {
            "contract": PROMOTION_GATES_CONTRACT,
            "maturity_gate_contract": MATURITY_GATE_CONTRACT,
            "agent_id": agent_id,
            "display_name": observation.get("display_name"),
            "maturity_target": observation.get("maturity_framework") or "non-mvl",
            "promotable": False,
            "blockers": ["No governed runtime spec in FLEET — observability row only."],
            "gates": [],
            "promotion_eligibility": observation.get("promotion_eligibility"),
            "next_step_hint": observation.get("next_step_hint"),
            "read_only": True,
        }
    spec = FLEET[agent_id]
    measurements: dict[str, Any] = {}
    sample = observation.get("sample_size")
    required = observation.get("required_sample_size")
    if sample is not None and required:
        measurements["min_artifact_population"] = float(sample)
    if observation.get("source_class") == "RUNTIME_EVIDENCE":
        measurements["independent_review_coverage"] = 1.0 if observation.get("review_health") == "HEALTHY" else 0.0
    if reader is not None:
        runtime_evidence, _ = collect_runtime_evidence(reader)
        rt = runtime_evidence.get(agent_id) or {}
        score_cov = rt.get("independent_score_coverage")
        if score_cov is not None:
            measurements["independent_score_coverage"] = float(score_cov)
    report = evaluate_gates(spec, measurements)
    body = report.as_dict()
    body["read_only"] = True
    body["promotion_eligibility"] = observation.get("promotion_eligibility")
    body["next_step_hint"] = observation.get("next_step_hint")
    body["display_name"] = observation.get("display_name")
    return body
