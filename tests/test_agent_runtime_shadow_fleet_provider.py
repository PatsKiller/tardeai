"""Shadow fleet provider fail-closed tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.agents.dispatcher import JobRequest  # noqa: E402
from agent_runtime.providers import shadow_fleet_provider as provider  # noqa: E402
from agent_runtime.trigger_intake import InMemoryTriggerIntakeStore, TriggerCandidate  # noqa: E402


def test_job_source_empty_without_queue_rows(monkeypatch):
    store = InMemoryTriggerIntakeStore()
    monkeypatch.setattr(provider, "_store", store)
    monkeypatch.setattr(provider, "_build_store", lambda: store)
    jobs = provider.job_source("darwin", 3)
    assert jobs == []


def test_job_source_leases_real_rows(monkeypatch):
    store = InMemoryTriggerIntakeStore()
    store.enqueue(
        TriggerCandidate(
            agent_id="darwin",
            trigger_kind="SCHEDULED_SWEEP",
            dedup_key="sweep:1",
            job_type="artifact_scoring",
            payload={"agent_id": "darwin"},
            source_ref="sweep:darwin:1",
            source_hash="b" * 64,
            source_timestamp="2026-07-31T12:00:00+00:00",
        )
    )
    monkeypatch.setattr(provider, "_store", store)
    monkeypatch.setattr(provider, "_build_store", lambda: store)
    jobs = provider.job_source("darwin", 1)
    assert len(jobs) == 1
    assert jobs[0].payload is not None
    assert jobs[0].intake_id is not None


def test_build_providers_rejects_unknown():
    with pytest.raises(ValueError, match="unknown agent"):
        provider.build_providers("missing")


@patch.object(provider, "_ollama_available", return_value=False)
def test_local_model_fail_closed(_mock):
    with pytest.raises(provider.ProviderUnavailable):
        provider._local_model("run_x", {"task": "test"})


def test_payload_from_job_prefers_embedded_payload():
    job = JobRequest(
        agent_id="darwin",
        job_type="artifact_scoring",
        input_hash="c" * 64,
        enqueued_at="2026-07-31T12:00:00+00:00",
        dedup_value="dedup",
        payload={"symbol": "LAB"},
    )
    payload = provider._payload_from_job(job)
    assert payload["symbol"] == "LAB"
