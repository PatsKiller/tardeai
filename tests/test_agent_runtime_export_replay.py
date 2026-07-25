"""Deterministic export / replay / tamper-detection tests (manifest-authoritative)."""

from __future__ import annotations

import itertools
import json

import pytest

from scripts.agent_runtime.contracts import (
    Artifact,
    BudgetPolicy,
    Environment,
    Review,
    ReviewVerdict,
    RunEnvelope,
    RunStatus,
    canonical_hash,
)
from scripts.agent_runtime.export_replay import (
    ReplayError,
    export_manifest,
    export_run_jsonl,
    replay_jsonl,
    verify_jsonl,
)
from scripts.agent_runtime.persistence import InMemoryPersistence, derive_id

H = "a" * 64
_c = itertools.count()


def _clock():
    return f"2026-07-25T00:00:{next(_c):02d}.000000+00:00"


def _seed(run_id="run_x"):
    s = InMemoryPersistence(clock=_clock)
    s.create_run(RunEnvelope(run_id=run_id, agent_id="alpha_agent", agent_version="1.0.0", job_type="research",
                             environment=Environment.LAB, objective="assess", input_hash=H, validation_hash=H), BudgetPolicy())
    s.record_artifact(Artifact(artifact_id="art_1", run_id=run_id, producer_agent_id="alpha_agent", artifact_type="analysis",
                               payload={"finding": "x"}, input_hash=H, validation_hash=H, retrieval_refs=("kb:1",),
                               prompt_version="p1", provider_family="local", model="m1"))
    s.record_review(Review(review_id=derive_id("r"), artifact_id="art_1", producer_agent_id="ignored",
                           reviewer_agent_id="beta_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash=canonical_hash({"finding": "x"})))
    s.complete_run(run_id)
    return s


def test_export_is_deterministic_and_stable_order():
    store = _seed()
    a = export_run_jsonl(store, "run_x")
    b = export_run_jsonl(store, "run_x")
    assert a == b
    assert [json.loads(x)["sequence"] for x in a] == sorted(json.loads(x)["sequence"] for x in a)


def test_export_excludes_connection_metadata():
    blob = "\n".join(export_run_jsonl(_seed(), "run_x")).lower()
    for token in ("dsn", "password", "conninfo", "sslmode", "5433", "5432"):
        assert token not in blob


def test_replay_requires_manifest_and_reconstructs_terminal_state():
    store = _seed()
    lines = export_run_jsonl(store, "run_x")
    manifest = export_manifest(store, "run_x")
    state = replay_jsonl(lines, manifest=manifest)
    assert state["run_id"] == "run_x"
    assert state["status"] == RunStatus.COMPLETED.value
    with pytest.raises(TypeError):
        replay_jsonl(lines)  # manifest is required (keyword-only)


def test_verify_intact_matches_manifest():
    store = _seed()
    lines = export_run_jsonl(store, "run_x")
    manifest = export_manifest(store, "run_x")
    result = verify_jsonl(lines, manifest=manifest)
    assert result.ok and not result.issues
    assert result.head_hash == manifest["head_hash"] and result.event_count == manifest["event_count"]


def test_tamper_modified_record_detected():
    lines = export_run_jsonl(_seed(), "run_x")
    victim = json.loads(lines[0])
    victim["payload"]["status"] = "COMPLETED"
    lines[0] = json.dumps(victim, sort_keys=True, separators=(",", ":"))
    assert any("modified record" in i for i in verify_jsonl(lines).issues)


def test_tamper_reordered_dropped_duplicated_detected():
    base = export_run_jsonl(_seed(), "run_x")
    reordered = base[:]
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert not verify_jsonl(reordered).ok
    dropped = base[:1] + base[2:]
    assert not verify_jsonl(dropped).ok
    dup = base[:1] + base
    assert any("duplicated" in i or "out-of-order" in i for i in verify_jsonl(dup).issues)


def test_manifest_truncated_tail_detected():
    store = _seed()
    lines = export_run_jsonl(store, "run_x")
    manifest = export_manifest(store, "run_x")
    result = verify_jsonl(lines[:-1], manifest=manifest)
    assert not result.ok
    assert any("event_count" in i or "head_hash" in i for i in result.issues)


def test_mixed_run_stream_rejected():
    a = export_run_jsonl(_seed("run_a"), "run_a")
    b = export_run_jsonl(_seed("run_b"), "run_b")
    mixed = [a[0], b[0] if len(b) > 0 else a[1]]
    assert any("mixed-run" in i or "chain" in i or "out-of-order" in i for i in verify_jsonl(mixed).issues)


def test_unknown_contract_rejected():
    store = _seed()
    lines = export_run_jsonl(store, "run_x")
    bad_manifest = {**export_manifest(store, "run_x"), "journal_contract": "bogus-v0"}
    assert any("journal_contract" in i for i in verify_jsonl(lines, manifest=bad_manifest).issues)


@pytest.mark.parametrize("hostile", [
    "not json at all",
    "12345",
    "[1, 2, 3]",
    '{"run_id": "x"}',                          # missing keys
    '{"run_id":"x","sequence":"NaN","event_type":"E","payload":{},"created_at":"t","previous_hash":"0","event_hash":"h"}',
    '{"run_id":"x","sequence":1,"event_type":"E","payload":"notobj","created_at":"t","previous_hash":"0","event_hash":"h"}',
])
def test_hostile_json_returns_findings_not_exceptions(hostile):
    result = verify_jsonl([hostile])  # must not raise TypeError/KeyError
    assert not result.ok and result.issues
