"""Read-only comparison of one coordination event, its artifact, and its consumer.

A green workflow execution is not a consumer receipt. Missing timestamps,
cost, or a consumer stay NOT_MEASURED. This module does not send, write a
canonical store, or call a provider.
"""
from __future__ import annotations

from typing import Any, Mapping

NO_CONSUMER_REASON = (
    "Read-only compare for blocked n8n pilots. No production job imports it. "
    "A green n8n execution is not a consumer."
)

NOT_MEASURED = "NOT_MEASURED"


def compare_chain(
    *,
    event: Mapping[str, Any] | None,
    artifact: Mapping[str, Any] | None,
    consumer: Mapping[str, Any] | None,
    execution_green: bool = False,
) -> dict[str, Any]:
    event_seen = isinstance(event, Mapping) and bool(event.get("event_id"))
    artifact_seen = isinstance(artifact, Mapping) and bool(artifact.get("artifact_id") or artifact.get("path"))
    consumer_seen = (
        isinstance(consumer, Mapping)
        and bool(consumer.get("consumer"))
        and bool(consumer.get("receipt_id"))
    )
    if execution_green and not artifact_seen:
        state = "UNCONSUMED"
        reason = "n8n_success_without_durable_output"
    elif event_seen and artifact_seen and consumer_seen:
        state = "CONSUMED"
        reason = None
    elif event_seen and artifact_seen:
        state = "ARTIFACT_WRITTEN"
        reason = "no_consumer_receipt"
    elif event_seen and not artifact_seen:
        state = "DROPPED"
        reason = "consumer_missing" if consumer is None else "no_artifact"
    else:
        state = "NOT_MEASURED"
        reason = "no_event"
    content_delta = NOT_MEASURED
    if artifact_seen and consumer_seen:
        left = artifact.get("content_hash")
        right = consumer.get("content_hash")
        if left and right:
            content_delta = "same" if left == right else "different"
    latency = NOT_MEASURED
    if event_seen and artifact_seen and event.get("source_timestamp") and artifact.get("written_at"):
        latency = "timestamps_present_delta_not_computed"
    cost = artifact.get("cost_usd") if artifact_seen else None
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        cost_status = NOT_MEASURED
    else:
        cost_status = cost
    expected_silent = bool(artifact.get("expected_silent")) if artifact_seen else False
    return {
        "schema": "N8nPilotCompare@v1",
        "state": "EXPECTED_SILENT" if expected_silent and state in {"DROPPED", "ARTIFACT_WRITTEN"} else state,
        "reason": "expected_silent" if expected_silent else reason,
        "event_seen": event_seen,
        "artifact_seen": artifact_seen,
        "consumer_seen": consumer_seen,
        "execution_green_is_receipt": False,
        "duplicate": bool(event.get("duplicate")) if event_seen else False,
        "latency": latency,
        "cost": cost_status,
        "content_delta": content_delta,
        "natural_opportunities": NOT_MEASURED,
        "sends": False,
    }
