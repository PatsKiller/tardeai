"""Serializable workflow/activity contracts for the Temporal NOC shadow POC."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MEMORY_BEHAVIOR_INFLUENCE = 0
WORKFLOW_NAME = "AutonomousResearchToCIOWorkflow"
TASK_QUEUE = "tradeai-temporal-poc"


@dataclass(frozen=True)
class ActivityPolicy:
    start_to_close_seconds: int
    initial_interval_seconds: int
    backoff_coefficient: float
    maximum_interval_seconds: int
    maximum_attempts: int
    non_retryable_error_types: tuple[str, ...]
    heartbeat_timeout_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


HARD_POLICY_ERRORS = (
    "COST_CONFIGURATION_INVALID",
    "COST_CAP_EXCEEDED",
    "POLICY_NOT_ALLOWED",
)

ACTIVITY_POLICIES: dict[str, ActivityPolicy] = {
    "load_standing_thesis": ActivityPolicy(10, 1, 2.0, 5, 3, HARD_POLICY_ERRORS),
    "retrieve_supporting_rag": ActivityPolicy(30, 2, 2.0, 10, 3, HARD_POLICY_ERRORS, 3),
    "retrieve_contradictory_rag": ActivityPolicy(30, 2, 2.0, 10, 3, HARD_POLICY_ERRORS, 3),
    "acquire_research": ActivityPolicy(120, 5, 2.0, 30, 3, HARD_POLICY_ERRORS, 3),
    "classify_delta": ActivityPolicy(10, 1, 2.0, 5, 2, HARD_POLICY_ERRORS),
    "reconcile_thesis": ActivityPolicy(20, 1, 2.0, 5, 3, HARD_POLICY_ERRORS, 3),
    "build_decision_payload": ActivityPolicy(10, 1, 2.0, 5, 3, HARD_POLICY_ERRORS),
    "evaluate_notification": ActivityPolicy(10, 1, 2.0, 5, 2, HARD_POLICY_ERRORS),
    "enqueue_notification": ActivityPolicy(20, 1, 2.0, 5, 3, HARD_POLICY_ERRORS),
}

WORKFLOW_STAGES = tuple(ACTIVITY_POLICIES)


def workflow_blueprint() -> dict[str, Any]:
    return {
        "workflow": WORKFLOW_NAME,
        "task_queue": TASK_QUEUE,
        "stages": list(WORKFLOW_STAGES),
        "activities": {name: policy.to_dict() for name, policy in ACTIVITY_POLICIES.items()},
        "signals": ["operator_feedback", "cancel_research"],
        "updates": ["supply_research_artifact"],
        "queries": ["current_stage", "lineage"],
        "search_attributes": [
            "symbol",
            "research_gap_id",
            "thesis_id",
            "thesis_version",
            "decision_id",
            "source_sha",
            "authority",
        ],
        "canonical_truth": "Trade AI domain stores",
        "temporal_truth": "orchestration history, timers, retries, causality",
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
    }
