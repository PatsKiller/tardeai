"""G-LOOP-01 — operator-gated DLQ ledger (dry-run) tests.

AUTHORITY: READ_ONLY_ADVISORY. MBI=0. never_auto_remediate.
No silent identity merge. Does not claim 99.99%.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    # Ensure package imports resolve for scripts.lib.*
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    return mod


ledger = _load("cio_dlq_ledger", "scripts/lib/cio_dlq_ledger.py")
cli = _load("cio_lifecycle_dlq", "scripts/cio_lifecycle_dlq.py")
census_mod = _load("cio_registry_orphan_census", "scripts/cio_registry_orphan_census.py")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows),
        encoding="utf-8",
    )


@pytest.fixture()
def fixture_root(tmp_path: Path) -> Path:
    """Minimal registry-shaped tree with missing_cross_id + orphan findings."""
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)

    _write_jsonl(cio / "cio_workflow_lineage.jsonl", [
        {
            "workflow_id": "wf_complete_1",
            "event_id": "evt_1",
            "checkpoint_id": "cp_1",
            "notification_id": "ntf_1",
            "complete_to_checkpoint": True,
            "stage_status": {
                "research": "COMPLETED",
                "specialist": "COMPLETED",
                "cio": "COMPLETED",
                "notification": "COMPLETED",
                "checkpoint": "COMPLETED",
            },
            "recorded_at": "2026-08-29T12:00:00+00:00",
            "updated_at": "2026-08-29T12:00:00+00:00",
        },
        {
            "workflow_id": "wf_no_event",
            "event_id": None,
            "complete_to_checkpoint": False,
            "stage_status": {
                "research": "COMPLETED",
                "specialist": "NOT_YET_CREATED",
                "cio": "NOT_YET_CREATED",
                "notification": "NOT_YET_CREATED",
                "checkpoint": "NOT_YET_CREATED",
            },
            "recorded_at": "2026-08-29T13:00:00+00:00",
            "updated_at": "2026-08-29T13:00:00+00:00",
        },
    ])

    _write_jsonl(cio / "outcome_checkpoints.jsonl", [
        {
            "checkpoint_id": "cp_1",
            "workflow_id": "wf_complete_1",
            "status": "COMPLETED",
            "created_at": "2026-08-29T12:05:00+00:00",
        },
        {
            "checkpoint_id": "cp_orphan",
            "workflow_id": "wf_ghost",
            "status": "SCHEDULED",
            "created_at": "2026-08-29T14:00:00+00:00",
        },
    ])

    _write_jsonl(cio / "cio_specialist_artifacts.jsonl", [
        {
            "artifact_id": "art_orphan",
            "workflow_id": None,
            "research_id": "res_1",
            "plan_id": "plan_1",
            "created_at": "2026-08-29T15:00:00+00:00",
        },
    ])

    _write_jsonl(cio / "cio_delivery_receipts.jsonl", [
        {
            "notification_id": "ntf_ghost",
            "plan_id": "plan_1",
            "dedupe_key": "dk_1",
            "created_at": "2026-08-29T15:01:00+00:00",
        },
    ])

    return tmp_path


def test_findings_from_census_map_reason_codes(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    report = census_mod.census(root=fixture_root, days=30)
    findings = ledger.findings_from_census(report)
    assert findings
    reasons = {f["reason_code"] for f in findings}
    assert ledger.REASON_MISSING_EVENT_ID in reasons
    assert ledger.REASON_NULL_WORKFLOW_ID in reasons or ledger.REASON_UNKNOWN_WORKFLOW_ID in reasons
    for f in findings:
        assert f["finding_id"].startswith("dlq_")
        assert f.get("source") == "cio_registry_orphan_census"


def test_write_ledger_appends_enqueue_only(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    lp = fixture_root / "data" / "cio" / "lifecycle_dlq.jsonl"

    # Snapshot hub mtimes — must not change on write-ledger.
    hubs = [
        fixture_root / "data" / "cio" / "cio_workflow_lineage.jsonl",
        fixture_root / "data" / "cio" / "outcome_checkpoints.jsonl",
        fixture_root / "data" / "cio" / "cio_specialist_artifacts.jsonl",
        fixture_root / "data" / "cio" / "cio_delivery_receipts.jsonl",
    ]
    before = {p: p.stat().st_mtime_ns for p in hubs}

    report = cli.build_run(
        root=fixture_root,
        census_days=30,
        write_ledger=True,
        replay_dry_run=False,
        apply=False,
        ledger_override=lp,
    )
    assert report["finding_count"] >= 1
    assert any(w.startswith("enqueue:") for w in report["written"])
    assert lp.is_file()
    rows = [json.loads(l) for l in lp.read_text().splitlines() if l.strip()]
    assert rows
    assert all(r["kind"] == "enqueue" for r in rows)
    assert all(r["mutates_historical_stores"] is False for r in rows)
    assert all(r["schema"] == ledger.SCHEMA for r in rows)
    assert all(r["authority"] == "READ_ONLY_ADVISORY" for r in rows)
    assert all(r["memory_behavior_influence"] == 0 for r in rows)

    after = {p: p.stat().st_mtime_ns for p in hubs}
    assert before == after


def test_replay_dry_run_prints_plans_optional_annotate(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    lp = fixture_root / "data" / "cio" / "lifecycle_dlq.jsonl"

    report = cli.build_run(
        root=fixture_root,
        census_days=30,
        write_ledger=True,
        replay_dry_run=True,
        apply=False,
        ledger_override=lp,
    )
    assert report["replay_plans"]
    assert all(p["mutates_historical_stores"] is False for p in report["replay_plans"])
    assert any(w.startswith("replay_plan:") for w in report["written"])

    kinds = {json.loads(l)["kind"] for l in lp.read_text().splitlines() if l.strip()}
    assert "enqueue" in kinds
    assert "replay_plan" in kinds


def test_apply_refused_without_env(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    lp = fixture_root / "data" / "cio" / "lifecycle_dlq.jsonl"

    report = cli.build_run(
        root=fixture_root,
        census_days=30,
        write_ledger=False,
        replay_dry_run=False,
        apply=True,
        ledger_override=lp,
    )
    assert report["apply_refused"] is not None
    assert report["apply_refused"]["reason"] == "APPLY_REFUSED"
    assert report["apply_receipt"] is None
    assert not lp.exists()


def test_apply_with_env_appends_receipt_only(fixture_root, monkeypatch):
    monkeypatch.setenv("TRADEAI_DLQ_APPLY", "1")
    lp = fixture_root / "data" / "cio" / "lifecycle_dlq.jsonl"

    hubs = list((fixture_root / "data" / "cio").glob("*.jsonl"))
    # Exclude ledger itself (created by apply).
    hub_before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in hubs
        if p.name != "lifecycle_dlq.jsonl"
    }

    report = cli.build_run(
        root=fixture_root,
        census_days=30,
        write_ledger=False,
        replay_dry_run=False,
        apply=True,
        ledger_override=lp,
    )
    assert report["apply_refused"] is None
    assert report["apply_receipt"] is not None
    assert report["apply_receipt"]["kind"] == "apply_receipt"
    assert report["apply_receipt"]["mutates_historical_stores"] is False
    assert report["apply_receipt"]["rewrote_lineage"] is False
    assert report["apply_receipt"]["rewrote_hubs"] is False
    assert "apply_receipt:1" in report["written"]

    rows = [json.loads(l) for l in lp.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["kind"] == "apply_receipt"

    for p, (content, _mtime) in hub_before.items():
        assert p.read_bytes() == content


def test_cli_apply_exit_code_refused(fixture_root, monkeypatch, capsys):
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cio_lifecycle_dlq.py",
            "--json",
            "--root", str(fixture_root),
            "--census-days", "30",
            "--ledger-path", str(fixture_root / "data" / "cio" / "lifecycle_dlq.jsonl"),
            "--apply",
        ],
    )
    rc = cli.main()
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["apply_refused"]["reason"] == "APPLY_REFUSED"


def test_cli_json_dry_run(fixture_root, monkeypatch, capsys):
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cio_lifecycle_dlq.py",
            "--json",
            "--root", str(fixture_root),
            "--census-days", "30",
            "--replay-dry-run",
        ],
    )
    rc = cli.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "CIOLifecycleDLQRun@v1"
    assert out["rails"]["claim_99_99"] is False
    assert out["rails"]["never_auto_remediate_store_consistency"] is True
    assert out["rails"]["no_silent_identity_merge"] is True
    assert out["mutates_historical_stores"] is False
    assert out["memory_behavior_influence"] == 0
    assert out["finding_count"] >= 1


def test_no_claim_99_99_in_render(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    report = cli.build_run(
        root=fixture_root,
        census_days=30,
        write_ledger=False,
        replay_dry_run=True,
        apply=False,
        ledger_override=fixture_root / "dlq.jsonl",
    )
    text = cli.render(report)
    assert "99.99%" not in text or "NOT a 99.99%" in text or "not claimed" in text.lower()
    assert "READ_ONLY_ADVISORY" in text
    assert "G-LOOP-01 OPEN" in text or "not claimed" in text.lower()


def test_apply_env_requires_exact_one(monkeypatch):
    monkeypatch.setenv("TRADEAI_DLQ_APPLY", "true")
    assert ledger.apply_env_armed() is False
    monkeypatch.setenv("TRADEAI_DLQ_APPLY", "1")
    assert ledger.apply_env_armed() is True
    monkeypatch.delenv("TRADEAI_DLQ_APPLY", raising=False)
    assert ledger.apply_env_armed() is False
