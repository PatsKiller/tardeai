"""Tests for CIO goals store + reactive wake cycle (READ_ONLY_ADVISORY)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_goal_crud_and_context(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_goals import CIOGoalStore

    store = CIOGoalStore(
        event_path=tmp_path / "goals.jsonl",
        projection_path=tmp_path / "proj.json",
        cursor_path=tmp_path / "cursors.json",
    )
    g = store.create_goal(
        owner_agent="alex",
        title="Desk thesis: risk-off posture",
        description="Maintain living desk thesis under READ_ONLY_ADVISORY",
        priority="HIGH",
        thesis_summary="Initial: observe only; no capital action without operator.",
        linked_event_types=["allocation.drift", "portfolio.material_change"],
        actor_id="test",
    )
    assert g["status"] == "open"
    assert g["owner_agent"] == "alex"
    gid = g["goal_id"]

    store.update_thesis(gid, "Updated thesis after drift signal.", agent_id="alex")
    g2 = store.get_goal(gid)
    assert "Updated thesis" in (g2 or {}).get("thesis_summary", "")

    open_g = store.list_open_goals(owner_agent="alex")
    assert any(x["goal_id"] == gid for x in open_g)

    ctx = store.get_context_for_agent("alex")
    assert ctx["authority"] == "READ_ONLY_ADVISORY"
    assert any(x["goal_id"] == gid for x in ctx["open_goals"])
    assert ctx["thesis_snippets"]

    store.close_goal(gid, status="achieved", reason="test done", actor_id="test")
    assert store.get_goal(gid)["status"] == "achieved"
    assert not any(x["goal_id"] == gid for x in store.list_open_goals(owner_agent="alex"))


def test_goal_dedup_list_due(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_goals import CIOGoalStore

    store = CIOGoalStore(
        event_path=tmp_path / "goals.jsonl",
        projection_path=tmp_path / "proj.json",
        cursor_path=tmp_path / "cursors.json",
    )
    store.create_goal(
        owner_agent="morgan",
        title="Wealth framing goal",
        thesis_summary="Disposition cost to goals.",
        actor_id="test",
    )
    due = store.list_due_or_idle_goals(owner_agent="morgan", limit=5)
    assert due and due[0].get("_wake_reason") in ("never_woken", "due", "idle")


def test_wake_trigger_types_include_event_bus():
    from scripts.lib.cio_wake_jobs import TRIGGER_TYPES
    assert "EVENT_BUS" in TRIGGER_TYPES
    assert "GOAL_DUE" in TRIGGER_TYPES
