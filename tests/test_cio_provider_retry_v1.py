from __future__ import annotations

import json

from scripts.lib.cio_provider_retry_v1 import (
    AMBIGUOUS_PROVIDER_RESULT,
    NON_RETRYABLE_COST,
    NON_RETRYABLE_POLICY,
    NON_RETRYABLE_VALIDATION,
    RETRYABLE_TRANSIENT,
    ProviderRequestJournal,
    classify_failure,
    semantic_request_key,
)


def test_retry_taxonomy_is_bounded_and_hard_failures_do_not_retry() -> None:
    transient = classify_failure("HTTP_503", http_status=503)
    assert transient["disposition"] == RETRYABLE_TRANSIENT
    assert transient["max_attempts"] == 3
    assert transient["maximum_interval_seconds"] == 30
    assert classify_failure("COST_CAP_EXCEEDED")["disposition"] == NON_RETRYABLE_COST
    assert classify_failure("POLICY_NOT_ALLOWED")["disposition"] == NON_RETRYABLE_POLICY
    assert classify_failure("MODEL_MISMATCH")["disposition"] == NON_RETRYABLE_VALIDATION


def test_sent_request_is_ambiguous_even_for_http_500() -> None:
    result = classify_failure("HTTP_500", request_sent=True, http_status=500)
    assert result["disposition"] == AMBIGUOUS_PROVIDER_RESULT
    assert result["retryable"] is False
    assert result["requires_explicit_resolution"] is True


def test_semantic_key_is_stable_and_does_not_expose_request_id() -> None:
    one = semantic_request_key(request_id="operator-visible-id", process_id="alex", model_id="m")
    two = semantic_request_key(request_id="operator-visible-id", process_id="alex", model_id="m")
    assert one == two
    assert "operator-visible-id" not in one


def test_journal_blocks_dispatched_and_completed_requests(tmp_path) -> None:
    journal = ProviderRequestJournal(tmp_path / "requests.jsonl")
    key = semantic_request_key(request_id="req-1", process_id="alex", model_id="model")
    first = journal.reserve(
        semantic_key=key,
        request_id="req-1",
        process_id="alex",
        provider="deepseek",
        model_id="model",
        task="cio_synthesis",
        projected_cost_usd=0.01,
    )
    assert first["allowed"] is True
    journal.record(key, state="DISPATCHED")
    duplicate = journal.reserve(
        semantic_key=key,
        request_id="req-1",
        process_id="alex",
        provider="deepseek",
        model_id="model",
        task="cio_synthesis",
        projected_cost_usd=0.01,
    )
    assert duplicate["allowed"] is False
    journal.record(key, state="COMPLETED", result_hash="abc", actual_cost_usd=0.001)
    assert journal.latest(key)["state"] == "COMPLETED"


def test_retryable_record_allows_next_attempt_but_caps_at_three(tmp_path) -> None:
    journal = ProviderRequestJournal(tmp_path / "requests.jsonl")
    key = "prj_retry"
    for attempt in range(1, 4):
        result = journal.reserve(
            semantic_key=key,
            request_id="req",
            process_id="alex",
            provider="deepseek",
            model_id="model",
            task="cio_synthesis",
            projected_cost_usd=0.01,
        )
        assert result["allowed"] is True
        assert result["current"]["attempt"] == attempt
        journal.record(key, state="RETRYABLE", retry_disposition=RETRYABLE_TRANSIENT)
    blocked = journal.reserve(
        semantic_key=key,
        request_id="req",
        process_id="alex",
        provider="deepseek",
        model_id="model",
        task="cio_synthesis",
        projected_cost_usd=0.01,
    )
    assert blocked["allowed"] is False
    assert blocked["reason"] == "ATTEMPTS_EXHAUSTED"
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert all("prompt" not in row and "response" not in row for row in rows)

