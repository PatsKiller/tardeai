"""ANCHOR: CRON_LANE_RECEIPTS_BATCH3_20261101 — three more scheduled lanes prove their run with a
LaneRunReceipt, and their dry-run branches write nothing.

Hermetic: the producer calls are monkeypatched and TRADEAI_STATE_ROOT points at a tmp dir.
"""
from __future__ import annotations

import json
import sys

import pytest

from scripts import deepseek_balance_snapshot as D
from scripts import hermes_score_alerts as H
from scripts import report_goal_loop_baseline as G


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    (tmp_path / "data/cio").mkdir(parents=True, exist_ok=True)


def test_hermes_score_alerts_writes_a_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "run", lambda send=False: {"new_alerts": 2})
    monkeypatch.setattr(sys, "argv", ["hermes_score_alerts"])
    H.main()
    receipt = json.loads((tmp_path / "data/runtime/hermes-score-alerts_last.json").read_text())
    assert receipt["lane_id"] == "hermes-score-alerts" and receipt["ok_at"]
    assert receipt["summary"]["new_alerts"] == 2


def test_deepseek_balance_snapshot_writes_a_receipt_only_on_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "run_once", lambda apply=False: {"ok": True})
    assert D.main(["--apply"]) == 0
    path = tmp_path / "data/runtime/deepseek-balance-snapshot_last.json"
    assert json.loads(path.read_text())["lane_id"] == "deepseek-balance-snapshot"
    path.unlink()
    assert D.main([]) == 0  # dry run
    assert not path.exists(), "a dry run must not write a receipt"


def test_goal_loop_baseline_writes_a_receipt_and_no_write_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "collect", lambda **kwargs: {"schema": "GoalLoopBaseline@v1"})
    path = tmp_path / "data/runtime/goal-loop-baseline_last.json"
    monkeypatch.setattr(sys, "argv", ["report_goal_loop_baseline", "--json"])
    assert G.main() == 0
    assert json.loads(path.read_text())["lane_id"] == "goal-loop-baseline"
    path.unlink()
    monkeypatch.setattr(sys, "argv", ["report_goal_loop_baseline", "--json", "--no-write"])
    assert G.main() == 0
    assert not path.exists(), "--no-write must not write a receipt"
