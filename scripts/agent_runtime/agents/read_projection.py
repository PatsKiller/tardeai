from __future__ import annotations

from typing import Any, Mapping

from ..contracts import canonical_hash
from .base import ShadowAgentSpec
from .definitions import FLEET
from .maturity_gates import evaluate_gates

PROMOTION_READMODEL_CONTRACT = "agent-runtime-promotion-readmodel-v1"


def agent_promotion_readmodel(
    spec: ShadowAgentSpec,
    *,
    measurements: Mapping[str, Any] | None = None,
    run_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-agent read model for the Command Center /v3/agents surface.

    ``run_evidence`` is the OPTIONAL authoritative slice supplied by the Lane A
    read plane (last run, state, checkpoint, artifact, reviewer, score, cost,
    retrieval count, tool calls, deadline, failures, stale/schedule state). When
    it is absent the model is explicitly marked ``NOT_RUN`` so nothing can look
    live that is not; ``measurements`` is likewise absent by default, so every
    gate reports NOT_YET_MEASURED and the agent is not promotable.
    """
    spec.validate()
    report = evaluate_gates(spec, measurements)
    source_kind = "AUTHORITATIVE" if run_evidence else "NONE"
    data_state = "LIVE" if run_evidence else "NOT_RUN"
    body: dict[str, Any] = {
        "contract": PROMOTION_READMODEL_CONTRACT,
        "agent_id": spec.agent_id,
        "display_name": spec.definition.display_name,
        "wave": spec.wave,
        "deployment_state": spec.definition.deployment_state.value,
        "enabled": spec.definition.enabled,
        "operable_now": spec.is_operable_now,
        "reviewer_agent_id": spec.reviewer_agent_id,
        "scorer_agent_id": spec.scorer_agent_id,
        "triggers": [
            {"kind": trigger.kind.value, "description": trigger.description, "owned_by": trigger.owned_by}
            for trigger in spec.triggers
        ],
        "allowed_output_kinds": [kind.value for kind in spec.allowed_output_kinds],
        "budget": {
            "max_model_calls": spec.definition.budget.max_model_calls,
            "max_tool_calls": spec.definition.budget.max_tool_calls,
            "max_cost_usd": spec.definition.budget.max_cost_usd,
            "deadline_seconds": spec.definition.budget.deadline_seconds,
        },
        "circuit_breaker_trips_open_after": spec.circuit_breaker_trips_open_after,
        "stale_input_seconds": spec.stale_input_seconds,
        "authority": "ADVISORY_ONLY",
        "promotable": report.promotable,
        "promotion_blockers": list(report.blockers),
        "gates": [gate.as_dict() for gate in report.gates],
        "evidence_source": source_kind,
        "data_state": data_state,
        "run_evidence": dict(run_evidence) if run_evidence else None,
    }
    return {**body, "readmodel_hash": canonical_hash(body)}


def fleet_promotion_readmodel(
    *,
    measurements: Mapping[str, Mapping[str, Any]] | None = None,
    run_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    measurements = measurements or {}
    run_evidence = run_evidence or {}
    agents = [
        agent_promotion_readmodel(
            spec,
            measurements=measurements.get(agent_id),
            run_evidence=run_evidence.get(agent_id),
        )
        for agent_id, spec in sorted(FLEET.items())
    ]
    return {
        "contract": PROMOTION_READMODEL_CONTRACT,
        "environment": "SHADOW",
        "production_activation_authorized": False,
        "agents": agents,
        "limitations": [
            "authoritative run evidence is supplied only by the Lane A read plane",
            "agents without run_evidence are reported NOT_RUN, never as live",
            "no agent is promotable until every maturity gate is measured and accepted",
        ],
    }
