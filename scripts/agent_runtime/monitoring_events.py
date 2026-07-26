from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import Environment, assert_no_secret_material, canonical_hash
from .identifiers import qualified_agent_id, stable_entity_id

MONITORING_EVENT_CONTRACT = "agent-runtime-monitoring-event-v1"
_ALLOWED_EVENT_TYPES = {
    "RUN_STATE_CHANGED",
    "CHECKPOINT_RECORDED",
    "ARTIFACT_PERSISTED",
    "TOOL_CALL_STATE_CHANGED",
    "REVIEW_RECORDED",
    "SCORE_RECORDED",
    "RETRIEVAL_EVIDENCE_RECORDED",
    "DEADLINE_EXCEEDED",
    "BUDGET_EXHAUSTED",
    "AUTHORITY_DENIED",
    "PERSISTENCE_FAILED",
}
_ALLOWED_SEVERITIES = {"INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True)
class MonitoringEvent:
    event_type: str
    run_id: str
    agent_id: str
    environment: Environment
    sequence: int
    status: str
    severity: str = "INFO"
    attributes: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    contract: str = MONITORING_EVENT_CONTRACT

    def validate(self) -> None:
        if self.contract != MONITORING_EVENT_CONTRACT:
            raise ValueError("monitoring contract mismatch")
        if self.event_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError(f"unsupported monitoring event type: {self.event_type}")
        if self.severity not in _ALLOWED_SEVERITIES:
            raise ValueError(f"unsupported monitoring severity: {self.severity}")
        if self.environment not in {Environment.LAB, Environment.SHADOW}:
            raise ValueError("monitoring events are LAB/SHADOW only")
        if self.sequence < 1:
            raise ValueError("monitoring sequence must be positive")
        if not self.run_id or not self.status:
            raise ValueError("run_id and status are required")
        qualified_agent_id(self.agent_id)
        datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        assert_no_secret_material(self.attributes)

    @property
    def qualified_agent_id(self) -> str:
        return qualified_agent_id(self.agent_id)

    @property
    def event_id(self) -> str:
        return stable_entity_id(
            "monitor_event",
            self.qualified_agent_id,
            self.run_id,
            self.sequence,
            self.event_type,
        )

    @property
    def event_hash(self) -> str:
        payload = asdict(self)
        payload["environment"] = self.environment.value
        return canonical_hash(payload)

    def to_record(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["environment"] = self.environment.value
        payload["qualified_agent_id"] = self.qualified_agent_id
        payload["event_id"] = self.event_id
        payload["event_hash"] = self.event_hash
        return payload
