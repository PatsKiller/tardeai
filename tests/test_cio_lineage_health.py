"""Lineage completion metrics — the loop that ran for a day without closing.

Fixtures reproduce the 2026-08-27 production shape: two arcs under two different
workflow-id systems, neither able to satisfy is_complete_to_checkpoint.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.lib.cio_lineage import LineageStore
from scripts.lib.cio_lineage_health import (
    ARC_CIO,
    ARC_RESEARCH,
    classify_arc,
    completion_report,
    findings,
    latest_envelopes,
)
from scripts.lib.cio_workflow_envelope import STAGE_COMPLETED

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def lineage(tmp_path: Path) -> Path:
    return tmp_path / "lineage.jsonl"


def _research_arc(store: LineageStore, wid: str) -> None:
    """Arc A: research + specialist + checkpoint, no notification."""
    store.upsert_envelope(wid, {
        "stage_status": {"research": STAGE_COMPLETED, "specialist": STAGE_COMPLETED,
                         "checkpoint": STAGE_COMPLETED},
        "checkpoint_id": f"ckpt_{wid}",
        "subject_id": "SCHD",
    })


def _cio_arc(store: LineageStore, wid: str) -> None:
    """Arc B: cio + notification, no checkpoint."""
    store.upsert_envelope(wid, {
        "stage_status": {"cio": STAGE_COMPLETED, "notification": STAGE_COMPLETED},
        "cio_generation_id": f"gen_{wid}",
        "notification_id": f"notif_{wid}",
    })


def test_latest_envelope_per_workflow_not_per_row(lineage: Path):
    """Append-only lineage: fold to newest per workflow, don't count rows."""
    s = LineageStore(lineage)
    s.upsert_envelope("wf_1", {"stage_status": {"research": STAGE_COMPLETED}})
    s.upsert_envelope("wf_1", {"stage_status": {"specialist": STAGE_COMPLETED}})
    s.upsert_envelope("wf_2", {"stage_status": {"research": STAGE_COMPLETED}})

    envs = latest_envelopes(lineage)
    assert set(envs) == {"wf_1", "wf_2"}
    # wf_1's newest row carries both stages, not just the last one written
    ss = envs["wf_1"]["stage_status"]
    assert ss["research"] == STAGE_COMPLETED
    assert ss["specialist"] == STAGE_COMPLETED


def test_identity_fork_is_detected(lineage: Path):
    """The production fault: both arcs present, zero completions."""
    s = LineageStore(lineage)
    for i in range(6):
        _research_arc(s, f"wf_r{i}")
        _cio_arc(s, f"run-uuid-{i}")

    rep = completion_report(lineage)
    assert rep["workflows"] == 12
    assert rep["complete_to_checkpoint"] == 0
    assert rep["arcs"] == {ARC_RESEARCH: 6, ARC_CIO: 6}
    assert rep["identity_fork_suspected"] is True

    found = findings(rep, min_workflows=10)
    assert [f["check"] for f in found] == ["cio_lineage_identity_fork"]
    assert found[0]["severity"] == "critical"


def test_joined_workflow_completes(lineage: Path):
    """The fix's acceptance test: one workflow carrying both arcs completes.

    This is what closing the loop must produce. It fails today in production not
    because a stage errors but because these two halves land on different ids.
    """
    s = LineageStore(lineage)
    s.upsert_envelope("wf_joined", {
        "stage_status": {"research": STAGE_COMPLETED, "specialist": STAGE_COMPLETED,
                         "cio": STAGE_COMPLETED, "notification": STAGE_COMPLETED,
                         "checkpoint": STAGE_COMPLETED},
        "checkpoint_id": "ckpt_joined",
    })

    rep = completion_report(lineage)
    assert rep["complete_to_checkpoint"] == 1
    assert rep["completion_rate"] == 1.0
    assert rep["identity_fork_suspected"] is False
    assert findings(rep, min_workflows=1) == []


def test_checkpoint_without_notification_does_not_count(lineage: Path):
    """Guard the predicate: a checkpoint alone is not a completed workflow."""
    s = LineageStore(lineage)
    _research_arc(s, "wf_only_checkpoint")

    envs = latest_envelopes(lineage)
    env = envs["wf_only_checkpoint"]
    assert classify_arc(env) == ARC_RESEARCH
    assert completion_report(lineage)["complete_to_checkpoint"] == 0


def test_quiet_window_stays_silent(lineage: Path):
    """Below the floor, say nothing — an alert that fires nightly is noise."""
    s = LineageStore(lineage)
    _research_arc(s, "wf_lonely")
    assert findings(path=lineage, min_workflows=10) == []


def test_missing_lineage_file_is_not_an_error(tmp_path: Path):
    rep = completion_report(tmp_path / "absent.jsonl")
    assert rep["workflows"] == 0
    assert rep["completion_rate"] is None
    assert findings(rep) == []


def test_cli_runs_the_way_cron_would(lineage: Path):
    """Invoke as a script: catches the scripts.-import bootstrap regressing."""
    s = LineageStore(lineage)
    for i in range(6):
        _research_arc(s, f"wf_r{i}")
        _cio_arc(s, f"run-uuid-{i}")

    proc = subprocess.run(
        [sys.executable, "scripts/cio_lineage_completion_report.py",
         "--path", str(lineage), "--json"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads(proc.stdout)
    assert payload["report"]["identity_fork_suspected"] is True
    assert payload["findings"][0]["check"] == "cio_lineage_identity_fork"


def test_cli_can_gate(lineage: Path):
    """--fail-on-finding exits non-zero so cron/CI can act on it."""
    s = LineageStore(lineage)
    for i in range(6):
        _research_arc(s, f"wf_r{i}")
        _cio_arc(s, f"run-uuid-{i}")

    proc = subprocess.run(
        [sys.executable, "scripts/cio_lineage_completion_report.py",
         "--path", str(lineage), "--fail-on-finding"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1
    assert "IDENTITY FORK SUSPECTED" in proc.stdout
