"""Typed R2 mechanics result that can be receipt-bound by R1 producers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.lib.research_governance.models import _stable_hash
from scripts.lib.research_governance.results import finalize  # re-export for producers

from .common import MechanicResult, MechanicStatus


@dataclass(frozen=True)
class MechanicsTypedResult:
    """Frozen typed wrapper so R1 issue_governed_receipt can bind it."""

    result_id: str
    method: str
    status: str
    mechanic_type: str
    instrument_id: str
    payload: dict
    protocol_hash: str = ""
    hypothesis_id: str = ""
    trial_family_id: str = "r2-deterministic"
    family_definition_hash: str = "r2-na"
    dataset_hash: str = ""
    code_sha: str = ""
    generated_at: Optional[str] = None
    result_digest: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "method": self.method,
            "status": self.status,
            "mechanic_type": self.mechanic_type,
            "instrument_id": self.instrument_id,
            "payload": self.payload,
            "protocol_hash": self.protocol_hash,
            "hypothesis_id": self.hypothesis_id,
            "trial_family_id": self.trial_family_id,
            "family_definition_hash": self.family_definition_hash,
            "dataset_hash": self.dataset_hash,
            "code_sha": self.code_sha,
            "generated_at": self.generated_at,
        }

    def compute_digest(self) -> str:
        return _stable_hash(self.to_payload())

    def validate(self) -> Optional[str]:
        if self.status not in {s.value for s in MechanicStatus}:
            return f"invalid status {self.status}"
        return None


def wrap_mechanic(method: str, calc: MechanicResult) -> MechanicsTypedResult:
    return MechanicsTypedResult(
        result_id=calc.calculation_id,
        method=method,
        status=calc.status.value,
        mechanic_type=calc.mechanic_type,
        instrument_id=calc.instrument_id,
        payload=calc.to_payload(),
        generated_at=calc.generated_at,
        code_sha=calc.producer_source_sha256,
        dataset_hash=calc.result_digest,
    )
