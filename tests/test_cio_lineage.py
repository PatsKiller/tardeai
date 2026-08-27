from pathlib import Path

from scripts.lib.cio_lineage import (
    LineageStore,
    default_lineage_path,
    finalize_notification_required,
    load_envelope,
    persist_canonical_checkpoint,
    record_hermes_completion,
    record_hermes_request,
    record_notification,
    record_specialist_dispatch,
)
from scripts.lib.cio_workflow_envelope import (
    ENVELOPE_REQUIRED_KEYS,
    SCHEMA as ENVELOPE_SCHEMA,
    STAGE_COMPLETED,
    STAGE_NOT_REQUIRED,
    STAGE_NOT_YET_CREATED,
    notification_is_ambiguous,
)


def test_hermes_lineage_is_idempotent_and_checkpoints(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-1", "research_id": "research-1", "symbol": "SCHD", "reason": "operator requested"}
    workflow = record_hermes_request(request, path=path)
    assert workflow.startswith("wf_")
    record_hermes_request(request, path=path)
    result = record_hermes_completion(request, {"research_id": "research-1", "result_id": "result-1", "summary": "fresh evidence"}, path=path)
    assert result["workflow_id"] == workflow
    assert result["checkpoint_id"]
    before = path.read_text()
    record_hermes_completion(request, {"research_id": "research-1", "result_id": "result-1", "summary": "fresh evidence"}, path=path)
    assert path.read_text() == before


def test_lineage_never_grants_execution_authority(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "p", "research_id": "r", "symbol": "SCHG"}
    record_hermes_completion(request, {"research_id": "r", "result_id": "rr"}, path=path)
    text = path.read_text()
    assert '"authority": "READ_ONLY_ADVISORY"' in text
    for line in text.splitlines():
        if line.strip():
            assert "READ_ONLY_ADVISORY" in line


def test_envelope_on_hermes_request_and_completion(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {
        "plan_id": "plan-env",
        "research_id": "research-env",
        "symbol": "NVDA",
        "event_id": "event-env",
        "context_id": "context-env",
        "source_sha": "sha-env",
    }
    wf = record_hermes_request(request, path=path)
    env = load_envelope(wf, path)
    assert env is not None
    for key in ENVELOPE_REQUIRED_KEYS:
        assert key in env
    assert env["schema"] == ENVELOPE_SCHEMA
    assert env["authority"] == "READ_ONLY_ADVISORY"
    assert env["memory_behavior_influence"] == 0
    assert env["research_request_id"] == "research-env"
    assert env["stage_status"]["research"] == STAGE_NOT_YET_CREATED
    assert env["stage_status"]["specialist"] == STAGE_NOT_YET_CREATED
    assert env["subject_guid"] is None
    assert env["subject_id"] == "NVDA"
    assert env["entity_type"] == "UNRESOLVED"
    assert notification_is_ambiguous(env) is True
    assert env["complete_to_checkpoint"] is False

    record_hermes_completion(
        request,
        {"research_id": "research-env", "result_id": "result-env", "summary": "done"},
        path=path,
    )
    env = load_envelope(wf, path)
    assert env["research_artifact_id"] == "result-env"
    assert env["specialist_artifact_id"] == "result-env"
    assert env["stage_status"]["research"] == STAGE_COMPLETED
    assert env["stage_status"]["specialist"] == STAGE_COMPLETED
    assert env["checkpoint_id"]
    assert env["stage_status"]["checkpoint"] == STAGE_COMPLETED
    assert env["subject_guid"] is None
    assert notification_is_ambiguous(env) is True
    assert env["complete_to_checkpoint"] is False


def test_specialist_not_completed_without_result_id(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-x", "research_id": "research-x", "symbol": "AAPL"}
    wf = record_hermes_request(request, path=path)
    record_hermes_completion(request, {"research_id": "research-x", "summary": "no artifact"}, path=path)
    env = load_envelope(wf, path)
    assert env["specialist_artifact_id"] is None
    assert env["stage_status"]["specialist"] == STAGE_NOT_YET_CREATED
    assert env["stage_status"]["research"] == STAGE_COMPLETED


def test_notification_finalize_clears_ambiguity(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-n", "research_id": "research-n", "symbol": "MSFT"}
    wf = record_hermes_request(request, path=path)
    record_hermes_completion(request, {"research_id": "research-n", "result_id": "result-n"}, path=path)
    env = load_envelope(wf, path)
    assert notification_is_ambiguous(env) is True
    finalize_notification_required(wf, path=path)
    env = load_envelope(wf, path)
    assert env["stage_status"]["notification"] == STAGE_NOT_REQUIRED
    assert notification_is_ambiguous(env) is False
    assert env["complete_to_checkpoint"] is True


def test_suppressed_notification_is_not_ambiguous(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-s", "research_id": "research-s", "symbol": "AMD"}
    wf = record_hermes_request(request, path=path)
    record_notification(wf, "ntf-s", "SUPPRESSED", "UNCHANGED_REPLAY", path=path)
    env = load_envelope(wf, path)
    assert env["notification_id"] == "ntf-s"
    assert env["notification_classification"] == "SUPPRESSED"
    assert env["stage_status"]["notification"] == "SUPPRESSED"
    assert notification_is_ambiguous(env) is False


def test_lineage_store_default_path_uses_production_state_root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    monkeypatch.delenv("TRADEAI_PERSISTENT_STATE_ROOT", raising=False)
    store = LineageStore()
    expected = tmp_path / "data" / "cio" / "cio_workflow_lineage.jsonl"
    assert store.path == expected
    assert default_lineage_path() == expected


def test_upsert_envelope_latest_wins(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    from scripts.lib.cio_lineage import upsert_envelope

    upsert_envelope("wf_latest", {"event_id": "e1"}, path=path)
    upsert_envelope("wf_latest", {"event_id": "e2"}, path=path)
    env = load_envelope("wf_latest", path)
    assert env["event_id"] == "e2"
    envelopes = [r for r in LineageStore(path)._rows() if r.get("record_type") == "envelope"]
    assert len(envelopes) == 2
    upsert_envelope("wf_latest", {"event_id": "e2"}, path=path)
    envelopes_after = [r for r in LineageStore(path)._rows() if r.get("record_type") == "envelope"]
    assert len(envelopes_after) == 2


def test_specialist_dispatch_is_explicit_stage(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    wf = record_hermes_request({"plan_id": "p", "research_id": "r", "symbol": "SCHD"}, path=path)
    env = record_specialist_dispatch(wf, "dispatch-1", agent_id="maria", artifact_id="artifact-1", path=path)
    assert env["specialist_dispatch_id"] == "dispatch-1"
    assert env["specialist_artifact_id"] == "artifact-1"
    assert env["stage_status"]["specialist"] == STAGE_COMPLETED
    rows = LineageStore(path)._rows()
    assert any(r.get("node_id") == "dispatch-1" for r in rows)
    assert any(r.get("from") == "dispatch-1" and r.get("to") == "artifact-1" for r in rows)
