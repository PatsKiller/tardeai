"""Temporal Workflow definition for the isolated NOC runtime POC.

Only bounded IDs, versions, classifications, and hashes cross Workflow history.
Research/RAG bodies and all domain writes remain in the isolated Activity store.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from scripts.temporal_poc.contracts import ACTIVITY_POLICIES, TASK_QUEUE, WORKFLOW_STAGES

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy, VersioningBehavior
except ImportError:
    workflow = None
    RetryPolicy = None
    VersioningBehavior = None

TEMPORAL_SDK_AVAILABLE = workflow is not None


def _retry_policy(stage: str):
    if RetryPolicy is None:
        raise RuntimeError("temporalio is not installed; Temporal runtime POC is BLOCKED")
    policy = ACTIVITY_POLICIES[stage]
    return RetryPolicy(
        initial_interval=timedelta(seconds=policy.initial_interval_seconds),
        backoff_coefficient=policy.backoff_coefficient,
        maximum_interval=timedelta(seconds=policy.maximum_interval_seconds),
        maximum_attempts=policy.maximum_attempts,
        non_retryable_error_types=list(policy.non_retryable_error_types),
    )


if TEMPORAL_SDK_AVAILABLE:

    @workflow.defn(
        name="AutonomousResearchToCIOWorkflow",
        versioning_behavior=VersioningBehavior.PINNED,
    )
    class AutonomousResearchToCIOWorkflow:
        """Durably orchestrate the shadow NOC research-to-CIO lifecycle."""

        def __init__(self) -> None:
            self._current_stage = "CREATED"
            self._lineage: dict[str, Any] = {}
            self._cancelled = False
            self._operator_feedback: dict[str, Any] | None = None

        @workflow.query(name="current_stage")
        def current_stage(self) -> str:
            return self._current_stage

        @workflow.query(name="lineage")
        def lineage(self) -> dict[str, Any]:
            return dict(self._lineage)

        @workflow.signal(name="cancel_research")
        def cancel_research(self) -> None:
            self._cancelled = True

        @workflow.signal(name="operator_feedback")
        def operator_feedback(self, feedback: dict[str, Any]) -> None:
            self._operator_feedback = feedback

        async def _activity(self, stage: str, value: dict[str, Any]) -> dict[str, Any]:
            if self._cancelled:
                raise RuntimeError("POC workflow cancelled by signal")
            self._current_stage = stage
            policy = ACTIVITY_POLICIES[stage]
            result = await workflow.execute_activity(
                stage,
                value,
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(seconds=policy.start_to_close_seconds),
                heartbeat_timeout=(
                    timedelta(seconds=policy.heartbeat_timeout_seconds)
                    if policy.heartbeat_timeout_seconds
                    else None
                ),
                retry_policy=_retry_policy(stage),
            )
            self._lineage[stage] = {
                key: result.get(key)
                for key in (
                    "research_id",
                    "delta_id",
                    "classification",
                    "thesis_version",
                    "decision_id",
                    "notification_identity",
                    "worker_build_id",
                )
                if result.get(key) is not None
            }
            return result

        @workflow.run
        async def run(self, request: dict[str, Any]) -> dict[str, Any]:
            base = {
                "workflow_id": workflow.info().workflow_id,
                "run_id": request["run_id"],
                "symbol": request.get("symbol", "NOC"),
                "root": request["root"],
                "fault": request.get("fault"),
                "stage_delay_seconds": request.get("stage_delay_seconds", 0),
            }
            standing = await self._activity("load_standing_thesis", base)
            supporting = await self._activity("retrieve_supporting_rag", base)
            contradictory = await self._activity("retrieve_contradictory_rag", base)
            research = await self._activity(
                "acquire_research",
                {**base, "supporting_ref": supporting["artifact_ref"], "contradictory_ref": contradictory["artifact_ref"]},
            )
            delta = await self._activity(
                "classify_delta",
                {**base, "standing_thesis_version": standing["thesis_version"], "research_id": research["research_id"]},
            )
            thesis = await self._activity(
                "reconcile_thesis",
                {**base, "delta_id": delta["delta_id"], "classification": delta["classification"]},
            )
            decision = await self._activity(
                "build_decision_payload",
                {**base, "delta_id": delta["delta_id"], "classification": delta["classification"], "thesis_version": thesis["thesis_version"]},
            )
            notification = await self._activity(
                "evaluate_notification",
                {**base, "decision_id": decision.get("decision_id"), "decision_emitted": decision["emitted"]},
            )
            outbox = await self._activity(
                "enqueue_notification",
                {**base, "decision_id": decision.get("decision_id"), "notification_identity": notification.get("notification_identity"), "send": notification["send"]},
            )
            self._current_stage = "COMPLETED"
            return {
                "workflow": "AutonomousResearchToCIOWorkflow",
                "workflow_id": base["workflow_id"],
                "run_id": base["run_id"],
                "symbol": base["symbol"],
                "classification": delta["classification"],
                "thesis_version": thesis["thesis_version"],
                "decision_id": decision.get("decision_id"),
                "decision_emitted": decision["emitted"],
                "notification_identity": notification.get("notification_identity"),
                "notification_enqueued": outbox["enqueued"],
                "operator_feedback": self._operator_feedback,
                "authority": "READ_ONLY_ADVISORY",
                "financial_writes": 0,
                "lineage": self._lineage,
            }

else:

    class AutonomousResearchToCIOWorkflow:
        """Unavailable marker used by source-only due-diligence tests."""

        async def run(self, request: dict[str, Any]) -> dict[str, Any]:
            del request
            raise RuntimeError("temporalio is not installed; Temporal runtime POC is BLOCKED")
