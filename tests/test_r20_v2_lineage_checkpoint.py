"""R20 V2 checkpoint contract + CIO/notification linkage + replay idempotency."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_institutional_learning import CHECKPOINT_PATH, _jsonl
from scripts.lib.cio_lineage import (
    REQUIRED_CHECKPOINT_FIELDS,
    complete_to_checkpoint,
    finalize_notification_required,
    load_envelope,
    persist_canonical_checkpoint,
    record_cio_generation,
    record_hermes_completion,
    record_hermes_request,
    record_notification,
)
from scripts.lib.cio_workflow_envelope import (
    NOTIFICATION_NOT_REQUIRED,
    NOTIFICATION_SUPPRESSED,
    STAGE_COMPLETED,
    STAGE_NOT_REQUIRED,
    STAGE_SUPPRESSED,
)


def _ck_rows(root: Path) -> list[dict]:
    return _jsonl(root / CHECKPOINT_PATH)


def test_canonical_checkpoint_has_required_fields(tmp_path: Path) -> None:
    lineage = tmp_path / "data" / "cio" / "cio_workflow_lineage.jsonl"
    request = {"plan_id": "plan-ck", "research_id": "res-ck", "symbol": "SCHD"}
    wf = record_hermes_request(request, path=lineage)
    result = record_hermes_completion(
        request,
        {"research_id": "res-ck", "result_id": "art-ck", "summary": "ok"},
        path=lineage,
        root=tmp_path,
        source_sha="deadbeef",
    )
    rows = _ck_rows(tmp_path)
    assert len(rows) == 1
    ck = rows[0]
    for field in REQUIRED_CHECKPOINT_FIELDS:
        assert field in ck, field
    assert ck["schema"] == "OutcomeCheckpoint@v1"
    assert ck["checkpoint_id"] == result["checkpoint_id"]
    assert ck["workflow_id"] == wf
    assert ck["authority"] == "READ_ONLY_ADVISORY"
    assert ck["observational_only"] is True
    assert ck["trading"] is False
    assert ck["runtime_source_sha"] == "deadbeef"
    assert ck["subject_guid"] is None  # never minted from ticker


def test_checkpoint_idempotent_same_generation(tmp_path: Path) -> None:
    lineage = tmp_path / "lineage.jsonl"
    request = {"plan_id": "p1", "research_id": "r1", "symbol": "SCHD"}
    record_hermes_request(request, path=lineage)
    a = record_hermes_completion(
        request, {"research_id": "r1", "result_id": "a1"}, path=lineage, root=tmp_path, source_sha="s"
    )
    b = record_hermes_completion(
        request, {"research_id": "r1", "result_id": "a1"}, path=lineage, root=tmp_path, source_sha="s"
    )
    assert a["checkpoint_id"] == b["checkpoint_id"]
    assert len(_ck_rows(tmp_path)) == 1


def test_changed_generation_may_create_new_checkpoint(tmp_path: Path) -> None:
    lineage = tmp_path / "data" / "cio" / "cio_workflow_lineage.jsonl"
    wf = "wf_gen"
    lineage.parent.mkdir(parents=True)
    record_cio_generation(wf, generation_id="gen-1", path=lineage)
    d1 = {"decision_id": "d1", "symbol": "SCHD", "recommendation": "HOLD", "material_generation": "gen-1"}
    d2 = {"decision_id": "d2", "symbol": "SCHD", "recommendation": "TRIM", "material_generation": "gen-2"}
    a = persist_canonical_checkpoint(tmp_path, wf, d1, source_sha="s", path=lineage)
    b = persist_canonical_checkpoint(tmp_path, wf, d2, source_sha="s", path=lineage)
    assert a["checkpoint_id"] != b["checkpoint_id"]
    assert len(_ck_rows(tmp_path)) == 2


def test_cio_skip_has_typed_reason_not_fake_id(tmp_path: Path) -> None:
    path = tmp_path / "lineage.jsonl"
    env = record_cio_generation("wf_skip", skip_reason="NO_CIO_REQUIRED", path=path)
    assert env["cio_generation_id"] is None
    assert env["cio_skip_reason"] == "NO_CIO_REQUIRED"
    assert env["stage_status"]["cio"] == STAGE_NOT_REQUIRED


def test_notification_suppression_persisted(tmp_path: Path) -> None:
    path = tmp_path / "lineage.jsonl"
    env = record_notification(
        "wf_n",
        notification_id="ntf_abc",
        classification=NOTIFICATION_SUPPRESSED,
        suppression_reason="unchanged_replay",
        path=path,
    )
    assert env["notification_id"] == "ntf_abc"
    assert env["notification_classification"] == NOTIFICATION_SUPPRESSED
    assert env["suppression_reason"] == "unchanged_replay"
    assert env["stage_status"]["notification"] == STAGE_SUPPRESSED


def test_hundred_replays_do_not_duplicate_checkpoints(tmp_path: Path) -> None:
    lineage = tmp_path / "lineage.jsonl"
    request = {"plan_id": "plan-loop", "research_id": "res-loop", "symbol": "SCHD"}
    record_hermes_request(request, path=lineage)
    ids = set()
    for _ in range(100):
        out = record_hermes_completion(
            request,
            {"research_id": "res-loop", "result_id": "art-loop"},
            path=lineage,
            root=tmp_path,
            source_sha="loop",
        )
        ids.add(out["checkpoint_id"])
    assert len(ids) == 1
    assert len(_ck_rows(tmp_path)) == 1
