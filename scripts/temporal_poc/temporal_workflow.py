"""Optional Temporal SDK definitions for the isolated NOC POC.

The SDK is intentionally not a project dependency in this architecture branch. The
definitions become importable only in an explicitly provisioned POC environment.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from scripts.temporal_poc.contracts import ACTIVITY_POLICIES, TASK_QUEUE, WORKFLOW_STAGES

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
except ImportError:
    workflow = None
    RetryPolicy = None

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

    @workflow.defn(name="AutonomousResearchToCIOWorkflow")
    class AutonomousResearchToCIOWorkflow:
        """Reference SDK workflow; all side effects are named Activities."""

        @workflow.run
        async def run(self, request: dict[str, Any]) -> dict[str, Any]:
            state: dict[str, Any] = {"request": request}
            for stage in WORKFLOW_STAGES:
                policy = ACTIVITY_POLICIES[stage]
                state[stage] = await workflow.execute_activity(
                    stage,
                    state,
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(seconds=policy.start_to_close_seconds),
                    heartbeat_timeout=(
                        timedelta(seconds=policy.heartbeat_timeout_seconds)
                        if policy.heartbeat_timeout_seconds
                        else None
                    ),
                    retry_policy=_retry_policy(stage),
                )
            return state

else:

    class AutonomousResearchToCIOWorkflow:
        """Unavailable marker used by source-only due-diligence tests."""

        async def run(self, request: dict[str, Any]) -> dict[str, Any]:
            del request
            raise RuntimeError("temporalio is not installed; Temporal runtime POC is BLOCKED")
