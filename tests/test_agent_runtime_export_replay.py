"""Deterministic export / replay / tamper-detection tests."""

from __future__ import annotations

import itertools
import json

import pytest

from scripts.agent_runtime.contracts import (
    Artifact,
    BudgetPolicy,
    Environment,
    RunEnvelope,
    RunStatus,
)
from scripts.agent_runtime.export_replay import (
    export_manifest,
    export_run_jsonl,
    replay_jsonl,
    verify_jsonl,
)
from scripts.agent_runtime.persistence import InMemoryPersistence

H = "a" * 64
_c = itertools.count()


def _clock():
    return f"2026-07-25T00:00:{next(_c):02d}.000000+00:00"


def _seed():
    store = InMemoryPersistence(clock=_clock)
    env = RunEnvelope(run_id="run_x", agent_id="alpha_agent", agent_version="1.0.0", job_type="research",
                      environment=Environment.LAB, objective="assess", input_hash=H, validation_hash=H)
    store.create_run(env, BudgetPolicy())
    store.record_artifact(Artifact(artifact_id="art_1", run_id="run_x", producer_agent_id="alpha_agent",
                                   artifact_type="analysis", payload={"finding": "x"}, input_hash=H,
                                   validation_hash=H, retrieval_refs=("kb:1",), prompt_version="p1",
                                   provider_family="local", model="m1"))
    store.complete_run("run_x")
    return store


def test_export_is_deterministic_and_stable_order():
    store = _seed()
    lines_a = export_run_jsonl(store, "run_x")
    lines_b = export_run_jsonl(store, "run_x")  # same persisted run -> identical bytes
    assert lines_a == lines_b
    seqs = [json.loads(line)["sequence"] for line in lines_a]
    assert seqs == sorted(seqs)


def test_export_excludes_connection_metadata():
    lines = export_run_jsonl(_seed(), "run_x")
    blob = "\n".join(lines).lower()
    for token in ("dsn", "password", "conninfo", "sslmode", "5433", "5432"):
        assert token not in blob


def test_replay_reconstructs_terminal_state_without_models():
    store = _seed()
    state = replay_jsonl(export_run_jsonl(store, "run_x"))
    assert state["run_id"] == "run_x"
    assert state["status"] == RunStatus.COMPLETED.value
    assert state["sequence"] == len(export_run_jsonl(store, "run_x"))


def test_verify_passes_on_intact_stream_and_matches_manifest():
    store = _seed()
    lines = export_run_jsonl(store, "run_x")
    manifest = export_manifest(store, "run_x")
    result = verify_jsonl(lines, manifest=manifest)
    assert result.ok and not result.issues
    assert result.head_hash == manifest["head_hash"]
    assert result.event_count == manifest["event_count"]


def test_tamper_modified_record_detected():
    lines = export_run_jsonl(_seed(), "run_x")
    victim = json.loads(lines[0])
    victim["payload"]["status"] = "COMPLETED"  # change a value, keep the old hash
    lines[0] = json.dumps(victim, sort_keys=True, separators=(",", ":"))
    result = verify_jsonl(lines)
    assert not result.ok
    assert any("modified record" in issue for issue in result.issues)
    with pytest.raises(ValueError):
        replay_jsonl(lines)


def test_tamper_reordered_records_detected():
    lines = export_run_jsonl(_seed(), "run_x")
    assert len(lines) >= 2
    lines[0], lines[1] = lines[1], lines[0]
    result = verify_jsonl(lines)
    assert not result.ok
    assert any("out-of-order" in issue or "chain link" in issue for issue in result.issues)


def test_tamper_dropped_record_detected():
    lines = export_run_jsonl(_seed(), "run_x")
    del lines[1]  # drop a middle event
    result = verify_jsonl(lines)
    assert not result.ok
    assert any("missing" in issue or "chain link" in issue or "out-of-order" in issue for issue in result.issues)


def test_tamper_duplicated_record_detected():
    lines = export_run_jsonl(_seed(), "run_x")
    lines.insert(1, lines[0])  # duplicate the first event
    result = verify_jsonl(lines)
    assert not result.ok
    assert any("duplicated" in issue or "out-of-order" in issue for issue in result.issues)


def test_manifest_head_mismatch_detects_truncated_tail():
    store = _seed()
    lines = export_run_jsonl(store, "run_x")
    manifest = export_manifest(store, "run_x")
    truncated = lines[:-1]
    result = verify_jsonl(truncated, manifest=manifest)
    assert not result.ok
    assert any("event_count" in issue or "head_hash" in issue for issue in result.issues)
