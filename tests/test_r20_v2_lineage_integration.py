"""Persisted full-chain lineage: reload after new process context."""
from __future__ import annotations

from pathlib import Path

import scripts.control_plane_api as api
from scripts.lib.cio_institutional_learning import CHECKPOINT_PATH, _jsonl
from scripts.lib.cio_lineage import (
    REQUIRED_CHECKPOINT_FIELDS,
    complete_to_checkpoint,
    load_envelope,
    persist_canonical_checkpoint,
    record_cio_generation,
    record_hermes_completion,
    record_hermes_request,
    record_notification,
)
from scripts.lib.cio_workflow_envelope import NOTIFICATION_SUPPRESSED, is_complete_to_checkpoint


def test_full_chain_persists_and_reloads(tmp_path: Path, monkeypatch) -> None:
    lineage = tmp_path / "data" / "cio" / "cio_workflow_lineage.jsonl"
    lineage.parent.mkdir(parents=True)
    request = {
        "plan_id": "plan_schd",
        "research_id": "res_schd",
        "symbol": "SCHD",
        "event_id": "evt_schd_1",
        "reason": "operator requested",
    }
    wf = record_hermes_request(request, path=lineage)
    completed = record_hermes_completion(
        request,
        {"research_id": "res_schd", "result_id": "sart_schd", "summary": "research done", "source_sha": "cafe"},
        path=lineage,
        root=tmp_path,
        source_sha="cafe",
    )
    record_cio_generation(wf, generation_id="gen_schd_1", path=lineage)
    record_notification(
        wf,
        notification_id="ntf_schd_1",
        classification=NOTIFICATION_SUPPRESSED,
        suppression_reason="unchanged_replay",
        path=lineage,
    )
    persist_canonical_checkpoint(
        tmp_path,
        wf,
        {
            "decision_id": "dec_schd",
            "symbol": "SCHD",
            "recommendation": "HOLD",
            "material_generation": "gen_schd_1",
            "plan_id": "plan_schd",
            "research_id": "res_schd",
        },
        source_sha="cafe",
        path=lineage,
    )

    # Destroy in-memory context: new loader, same files.
    env = load_envelope(wf, path=lineage)
    assert env is not None
    assert env["workflow_id"] == wf
    assert env["research_request_id"] == "res_schd"
    assert env["research_artifact_id"] == "sart_schd"
    assert env["specialist_artifact_id"] == "sart_schd"
    assert env["cio_generation_id"] == "gen_schd_1"
    assert env["notification_id"] == "ntf_schd_1"
    assert env["notification_classification"] == NOTIFICATION_SUPPRESSED
    assert env["suppression_reason"] == "unchanged_replay"
    assert env["checkpoint_id"]
    assert env["event_id"] == "evt_schd_1"
    assert env["subject_guid"] is None
    assert is_complete_to_checkpoint(env)
    assert complete_to_checkpoint(wf, path=lineage)

    ck = next(r for r in _jsonl(tmp_path / CHECKPOINT_PATH) if r.get("checkpoint_id") == env["checkpoint_id"])
    for field in REQUIRED_CHECKPOINT_FIELDS:
        assert field in ck
    assert ck["workflow_id"] == wf

    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle(f"/api/v3/control-plane/workflows/{wf}")
    assert status == 200
    assert body["data"]["workflow_id"] == wf
    ids = body["data"]["identifiers"]
    assert ids.get("research_request_id") == "res_schd"
    assert ids.get("specialist_artifact_id") == "sart_schd"
    assert ids.get("cio_generation_id") == "gen_schd_1"
    assert ids.get("notification_id") == "ntf_schd_1"
    assert ids.get("checkpoint_id") == env["checkpoint_id"]
    projected = body["data"].get("checkpoint") or {}
    assert projected.get("checkpoint_id") == ck["checkpoint_id"]
    assert projected.get("workflow_id") == wf
    assert projected.get("schema") == "OutcomeCheckpoint@v1"


def test_skip_path_no_fake_cio_or_notification_spam(tmp_path: Path) -> None:
    lineage = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan_skip", "research_id": "res_skip", "symbol": "ABUS"}
    wf = record_hermes_request(request, path=lineage)
    record_hermes_completion(
        request,
        {"research_id": "res_skip", "result_id": "art_skip"},
        path=lineage,
        root=tmp_path,
        source_sha="skip",
    )
    record_cio_generation(wf, skip_reason="NO_CIO_REQUIRED", path=lineage)
    record_notification(
        wf,
        classification="NOT_REQUIRED",
        suppression_reason="NOT_REQUIRED",
        path=lineage,
    )
    env = load_envelope(wf, path=lineage)
    assert env["cio_generation_id"] is None
    assert env["cio_skip_reason"] == "NO_CIO_REQUIRED"
    assert env["notification_classification"] == "NOT_REQUIRED"
    assert env["stage_status"]["cio"] == "NOT_REQUIRED"
    assert env["stage_status"]["notification"] == "NOT_REQUIRED"
    before = (tmp_path / CHECKPOINT_PATH).read_text() if (tmp_path / CHECKPOINT_PATH).is_file() else ""
    for _ in range(20):
        record_hermes_completion(
            request,
            {"research_id": "res_skip", "result_id": "art_skip"},
            path=lineage,
            root=tmp_path,
            source_sha="skip",
        )
        record_cio_generation(wf, skip_reason="NO_CIO_REQUIRED", path=lineage)
        record_notification(wf, classification="NOT_REQUIRED", suppression_reason="NOT_REQUIRED", path=lineage)
    after = (tmp_path / CHECKPOINT_PATH).read_text() if (tmp_path / CHECKPOINT_PATH).is_file() else ""
    assert after == before
