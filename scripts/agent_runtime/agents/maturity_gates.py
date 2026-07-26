from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from ..contracts import canonical_hash
from .base import ShadowAgentSpec

MATURITY_GATE_CONTRACT = "agent-runtime-maturity-gates-v1"


class GateStatus(str, Enum):
    NOT_YET_MEASURED = "NOT_YET_MEASURED"
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    description: str
    # Direction of the comparison against ``threshold``:
    #   "min"  -> measured value must be >= threshold
    #   "max"  -> measured value must be <= threshold
    #   "bool" -> measured value must be truthy
    comparator: str
    threshold: float = 0.0


# The measurable promotion gates every agent must clear before it may leave
# SHADOW.  Until each is measured *and accepted*, the agent is not promotable.
GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec("min_artifact_population", "Minimum reviewed artifact population", "min", 100),
    GateSpec("retrieval_provenance_completeness", "Fraction of artifacts with complete retrieval provenance", "min", 1.0),
    GateSpec("independent_review_coverage", "Fraction of artifacts with an independent review", "min", 1.0),
    GateSpec("independent_score_coverage", "Fraction of artifacts with an independent score", "min", 1.0),
    GateSpec("contradiction_rate", "Rate of internal contradictions in artifacts", "max", 0.02),
    GateSpec("unsupported_claim_rate", "Rate of claims lacking retrieval support", "max", 0.0),
    GateSpec("stale_input_refusal_accuracy", "Accuracy of refusing stale inputs", "min", 1.0),
    GateSpec("deadline_budget_adherence", "Fraction of runs within deadline and budget", "min", 1.0),
    GateSpec("duplicate_run_rate", "Rate of duplicate (non-idempotent) runs", "max", 0.0),
    GateSpec("operator_usefulness", "Operator-rated usefulness score", "min", 0.7),
    GateSpec("rollback_test_passed", "Definition rollback + replay verified", "bool"),
    GateSpec("authority_violations", "Count of authority violations observed", "max", 0),
)

GATE_IDS: tuple[str, ...] = tuple(gate.gate_id for gate in GATE_SPECS)


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    description: str
    status: GateStatus
    measured_value: float | bool | None
    threshold: float
    comparator: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "description": self.description,
            "status": self.status.value,
            "measured_value": self.measured_value,
            "threshold": self.threshold,
            "comparator": self.comparator,
        }


@dataclass(frozen=True)
class MaturityReport:
    agent_id: str
    maturity_target: str
    gates: tuple[GateResult, ...]
    promotable: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        body = {
            "contract": MATURITY_GATE_CONTRACT,
            "agent_id": self.agent_id,
            "maturity_target": self.maturity_target,
            "promotable": self.promotable,
            "blockers": list(self.blockers),
            "gates": [gate.as_dict() for gate in self.gates],
            "gate_summary": {
                status.value: sum(1 for gate in self.gates if gate.status is status)
                for status in GateStatus
            },
        }
        return {**body, "report_hash": canonical_hash(body)}


def _evaluate_one(gate: GateSpec, measured: Any) -> GateStatus:
    if measured is None:
        return GateStatus.NOT_YET_MEASURED
    if gate.comparator == "bool":
        return GateStatus.PASS if bool(measured) else GateStatus.FAIL
    value = float(measured)
    if gate.comparator == "min":
        return GateStatus.PASS if value >= gate.threshold else GateStatus.FAIL
    if gate.comparator == "max":
        return GateStatus.PASS if value <= gate.threshold else GateStatus.FAIL
    raise ValueError(f"unknown comparator: {gate.comparator}")


def evaluate_gates(
    spec: ShadowAgentSpec,
    measurements: Mapping[str, Any] | None = None,
) -> MaturityReport:
    """Evaluate promotion gates for one agent.

    With ``measurements=None`` (the honest default before any acceptance run),
    every gate reports ``NOT_YET_MEASURED`` and the agent is NOT promotable.  An
    agent is promotable only when *every* gate is explicitly measured and PASS.
    """
    spec.validate()
    measurements = measurements or {}
    results: list[GateResult] = []
    blockers: list[str] = []
    for gate in GATE_SPECS:
        measured = measurements.get(gate.gate_id)
        status = _evaluate_one(gate, measured)
        results.append(
            GateResult(
                gate_id=gate.gate_id,
                description=gate.description,
                status=status,
                measured_value=measured,
                threshold=gate.threshold,
                comparator=gate.comparator,
            )
        )
        if status is GateStatus.NOT_YET_MEASURED:
            blockers.append(f"{gate.gate_id}: not yet measured")
        elif status is GateStatus.FAIL:
            blockers.append(f"{gate.gate_id}: measured value fails threshold")
    promotable = all(result.status is GateStatus.PASS for result in results)
    return MaturityReport(
        agent_id=spec.agent_id,
        maturity_target=spec.maturity_target,
        gates=tuple(results),
        promotable=promotable,
        blockers=tuple(blockers),
    )


def assert_not_operational(spec: ShadowAgentSpec, report: MaturityReport) -> None:
    """Fail closed if anything tries to treat an agent as OPERATIONAL before its
    gates are measured and accepted."""
    if report.promotable:
        return
    if spec.definition.deployment_state.value == "OPERATIONAL":
        raise PermissionError(
            f"{spec.agent_id}: cannot be OPERATIONAL while gates are unmet: {report.blockers}"
        )
