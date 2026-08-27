from pathlib import Path

import pytest

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


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin the registry away from production for every test in this module.

    Envelope writes now resolve their subject against the identity registry. With
    the real one on PATH these tests would pass or fail depending on which
    symbols happen to be minted on this machine -- NVDA resolving to a live GUID
    is what first surfaced this.
    """
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
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
    # Unregistered symbol: the envelope says so rather than inventing a GUID.
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
    # A research completion now settles its own notification stage: it produces
    # an observational checkpoint and delivers nothing to the operator, and
    # leaving that undecided is what kept 30 real workflows permanently
    # incomplete. The decision is recorded with a reason, not flipped silently.
    assert notification_is_ambiguous(env) is False
    assert env["stage_status"]["notification"] == STAGE_NOT_REQUIRED
    assert env["suppression_reason"] == "RESEARCH_OBSERVATIONAL_NO_OPERATOR_DELIVERY"
    assert env["complete_to_checkpoint"] is True


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
    """A workflow that never decided about notification, then does.

    The research path now settles its own stage, so the ambiguous case is
    exercised on a request that has not completed yet — which is the state
    finalize actually exists to resolve.
    """
    path = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-n", "research_id": "research-n", "symbol": "MSFT"}
    wf = record_hermes_request(request, path=path)
    env = load_envelope(wf, path)
    assert notification_is_ambiguous(env) is True

    finalize_notification_required(wf, path=path)
    env = load_envelope(wf, path)
    assert env["stage_status"]["notification"] == STAGE_NOT_REQUIRED
    assert notification_is_ambiguous(env) is False

    # Still incomplete: settling notification is not a substitute for a
    # checkpoint. Only the real research completion supplies that.
    assert env["complete_to_checkpoint"] is False

    record_hermes_completion(request, {"research_id": "research-n", "result_id": "result-n"}, path=path)
    env = load_envelope(wf, path)
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


def test_envelope_resolves_a_registered_subject_to_its_durable_guid(tmp_path: Path, monkeypatch):
    """The wiring the registry existed for but nothing used.

    0 of 97 production workflows carried a `subject_guid` and all 97 read
    `entity_type: UNRESOLVED`, because identity was stamped only when a producer
    passed an explicit payload and the CIO arc never did. Resolution now happens
    on the envelope write path, so a registered subject is keyed by its durable
    GUID rather than by a ticker string that can be reassigned after a delisting.
    """
    from scripts.lib.identity_registry import empty_registry, register, save

    registry = tmp_path / "registry.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(registry))
    doc = register(empty_registry(), {"symbol": "NVDA", "identifiers": {"cusip": "67066G104"}})
    save(doc)
    expected = doc["by_symbol"]["NVDA"]

    path = tmp_path / "lineage.jsonl"
    wf = record_hermes_request(
        {"plan_id": "p", "research_id": "r", "symbol": "NVDA"}, path=path)
    env = load_envelope(wf, path)

    assert env["subject_guid"] == expected
    assert env["entity_type"] == "SECURITY"
    assert env["subject_id"] == "NVDA"


def test_stamping_never_overwrites_a_producer_that_knows_better(tmp_path: Path):
    """A GOAL wake is not a security, and must not be re-typed by a guess.

    42 of 49 CIO runs are portfolio goal wakes. Silently retyping one as SECURITY
    would join it to research on an entity it has nothing to do with.
    """
    from scripts.lib.cio_lineage import _stamp_identity

    env = {"workflow_id": "wf_x", "subject_id": "NVDA", "entity_type": "GOAL"}
    _stamp_identity(env)
    assert env["entity_type"] == "GOAL"


def test_stamping_is_best_effort_and_never_fails_the_write(tmp_path: Path, monkeypatch):
    """Lineage is an audit projection: a broken registry must not lose the record."""
    from scripts.lib.cio_lineage import _stamp_identity

    bad = tmp_path / "registry.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(bad))

    env = {"workflow_id": "wf_x", "subject_id": "NVDA"}
    _stamp_identity(env)
    assert env["workflow_id"] == "wf_x"
    assert env.get("subject_guid") is None
