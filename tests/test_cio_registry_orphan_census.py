"""P9 — registry orphan census: tmp fixtures, fail-soft, read-only.

AUTHORITY: READ_ONLY_ADVISORY. MBI=0. never_auto_remediate.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "cio_registry_orphan_census",
    ROOT / "scripts" / "cio_registry_orphan_census.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows),
        encoding="utf-8",
    )


@pytest.fixture()
def fixture_root(tmp_path: Path) -> Path:
    """Minimal CanonicalStoreRegistry-shaped tree with known orphans."""
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
            # Missing event_id — missing cross-id on hub
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
            # Orphan: workflow_id not in lineage hub
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

    # Empty / absent stores stay fail-soft (no files for lesson_binds etc.)
    return tmp_path


def test_census_detects_orphan_and_missing_cross_ids(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    report = mod.census(root=fixture_root, days=30, include_lineage_baseline=True)

    assert report["authority"] == "READ_ONLY_ADVISORY"
    assert report["memory_behavior_influence"] == 0
    assert report["never_auto_remediate"] is True
    assert report["financial_action"] is False

    h = report["headline"]
    assert h["orphan_hits"] >= 2  # cp ghost workflow + null specialist (+ maybe receipt)
    assert h["missing_cross_id_hits"] >= 1

    edges = report["orphans"]["by_edge"]
    assert "cio.checkpoints.workflow_id->workflow_id" in edges
    assert "cio.specialist_artifacts.null_workflow_id" in edges

    miss = report["missing_cross_ids"]["by_store_field"]
    assert any(k.endswith(".event_id") or k.endswith(".workflow_id") for k in miss)


def test_census_fail_soft_on_empty_root(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    report = mod.census(root=tmp_path, days=7)
    assert report["headline"]["stores_present"] == 0
    assert report["headline"]["orphan_hits"] == 0
    # Every scanned store reported without raising
    assert len(report["stores"]) == len(mod.SCAN_STORES)


def test_census_is_read_only(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)

    def snapshot():
        return {p: p.stat().st_mtime_ns for p in sorted(fixture_root.rglob("*")) if p.is_file()}

    before = snapshot()
    mod.census(root=fixture_root, days=30)
    assert snapshot() == before


def test_census_does_not_leak_env(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    mod.census(root=fixture_root, days=30)
    assert "TRADEAI_ROOT" not in os.environ


def test_render_and_cli_json(fixture_root, monkeypatch, capsys):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    report = mod.census(root=fixture_root, days=30)
    text = mod.render(report)
    assert "orphan" in text.lower() or "orphan_hits" in text or "orphans" in text
    assert "READ_ONLY_ADVISORY" in text

    # CLI --json path
    import sys
    monkeypatch.setattr(
        sys, "argv",
        ["cio_registry_orphan_census.py", "--json", "--root", str(fixture_root), "--days", "30"],
    )
    rc = mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["schema"] == "CIORegistryOrphanCensus@v1"
    assert parsed["headline"]["orphan_hits"] >= 1


def test_lineage_baseline_integrated(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    report = mod.census(root=fixture_root, days=30, include_lineage_baseline=True)
    lb = report["lineage_baseline"]
    assert isinstance(lb, dict)
    # Fixture has 2 lineage envelopes
    assert lb.get("workflows") == 2
    assert lb.get("complete_to_checkpoint") == 1


def test_window_excludes_old_rows(fixture_root, monkeypatch):
    monkeypatch.delenv("TRADEAI_ROOT", raising=False)
    # All fixture rows are 2026-08-29; a 0-day window with cutoff=now still
    # includes them via days>0 using now-relative cutoff — use days=1 which
    # still includes Aug 29 when "now" is 2026-08-30. Instead write an ancient
    # orphan and prove days=1 can exclude it when we control timestamps.
    ancient = fixture_root / "data" / "cio" / "outcome_checkpoints.jsonl"
    rows = [json.loads(l) for l in ancient.read_text().splitlines() if l.strip()]
    rows.append({
        "checkpoint_id": "cp_ancient",
        "workflow_id": "wf_ancient_ghost",
        "status": "SCHEDULED",
        "created_at": "2020-01-01T00:00:00+00:00",
    })
    ancient.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    tight = mod.census(root=fixture_root, days=14)
    wide = mod.census(root=fixture_root, days=3650)
    # Ancient orphan only in wide window
    tight_vals = {s.get("value") for s in tight["orphans"]["samples"]}
    wide_vals = {s.get("value") for s in wide["orphans"]["samples"]}
    assert "wf_ancient_ghost" not in tight_vals
    assert "wf_ancient_ghost" in wide_vals
