"""ANCHOR: CRON_LANE_RECEIPTS_BATCH4_20261101 — five more scheduled lanes write a LaneRunReceipt at
the process entry point when a live run exits 0; a dry run writes nothing.

Hermetic: the inner main/run_once is monkeypatched and TRADEAI_STATE_ROOT points at a tmp dir.
"""
from __future__ import annotations

import json
import sys

import pytest


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))


def _receipt(tmp_path, lane):
    return json.loads((tmp_path / f"data/runtime/{lane}_last.json").read_text())


def test_comms_lifecycle_writes_only_on_apply(tmp_path, monkeypatch):
    from scripts import comms_lifecycle as C

    monkeypatch.setattr(C, "main", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["comms_lifecycle"])
    assert C._entry() == 0
    assert not (tmp_path / "data/runtime/comms-lifecycle_last.json").exists()
    monkeypatch.setattr(sys, "argv", ["comms_lifecycle", "--apply"])
    assert C._entry() == 0
    assert _receipt(tmp_path, "comms-lifecycle")["lane_id"] == "comms-lifecycle"


def test_notify_material_change_writes_a_receipt(tmp_path, monkeypatch):
    from scripts import notify_material_change as N

    monkeypatch.setattr(N, "main", lambda: 0)
    assert N._entry() == 0
    assert _receipt(tmp_path, "material-change-notifier-stage2")["ok_at"]


def test_due_diligence_questions_skips_the_dry_run(tmp_path, monkeypatch):
    from scripts import due_diligence_questions as D

    monkeypatch.setattr(D, "main", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["due_diligence_questions", "--dry-run"])
    assert D._entry() == 0
    assert not (tmp_path / "data/runtime/due-diligence-questions_last.json").exists()
    monkeypatch.setattr(sys, "argv", ["due_diligence_questions", "--apply"])
    assert D._entry() == 0
    assert _receipt(tmp_path, "due-diligence-questions")["ok_at"]


def test_persistent_wake_writes_a_receipt_but_not_on_dry_run(tmp_path, monkeypatch):
    from scripts import run_persistent_wake as W

    monkeypatch.setattr(W, "run_once", lambda **kwargs: 0)
    assert W.main(["--agent-id", "cio", "--dry-run"]) == 0
    assert not (tmp_path / "data/runtime/persistent-wake-hourly_last.json").exists()
    assert W.main(["--agent-id", "cio"]) == 0
    assert _receipt(tmp_path, "persistent-wake-hourly")["summary"]["agent_id"] == "cio"


def test_claude_escalation_handler_writes_a_receipt(tmp_path):
    from scripts import claude_escalation_handler as E

    E._write_run_receipt()
    assert _receipt(tmp_path, "claude-escalation-handler")["ok_at"]
