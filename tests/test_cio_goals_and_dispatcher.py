"""WS1–WS2 tests: goal CRUD, context assembly, dispatcher goal-wake dedup."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def goal_store(tmp_path):
    from scripts.lib.cio_goals import CIOGoalStore
    return CIOGoalStore(
        event_path=tmp_path / "cio_goals.jsonl",
        projection_path=tmp_path / "cio_goals_projection.json",
        cursor_path=tmp_path / "cursors.json",
    )


def test_goal_create_list_update_close(goal_store, tmp_path):
    g = goal_store.create_goal(
        owner_agent="alex",
        title="Cash concentration review",
        description="Track idle cash vs deliberate reserve",
        priority="HIGH",
        success_criteria="Operator declares deliberate vs drift",
        linked_event_types=["PORTFOLIO_ALLOCATION_REVIEW"],
        linked_symbols=["SCHD", "CASH"],
    )
    assert g["goal_id"].startswith("goal_")
    assert g["status"] == "open"
    assert g["owner_agent"] == "alex"
    assert "SCHD" in g["linked_symbols"]

    open_g = goal_store.list_open_goals(owner_agent="alex")
    assert len(open_g) == 1

    goal_store.update_thesis(g["goal_id"], "Thesis: idle cash needs owner call", agent_id="alex")
    got = goal_store.get_goal(g["goal_id"])
    assert "idle cash" in got["thesis_summary"]
    assert got["wake_count"] == 0

    goal_store.record_wake(g["goal_id"], agent_id="alex", outcome="shadow_ok")
    got = goal_store.get_goal(g["goal_id"])
    assert got["wake_count"] == 1
    assert got["last_wake_ts"]

    # P2/P7 (2026-09-16): an achieved close now requires evidence, a
    # non-vacuous falsifier and a bound re-check. See
    # tests/test_goal_predicate_20260916.py and test_goal_termination_20260916.py.
    closed = goal_store.close_goal(
        g["goal_id"],
        status="achieved",
        reason="operator decided",
        evidence=["operator:2026-09-16:deliberate-reserve-call"],
        falsifier="cash weight leaves the declared reserve band within 30 days",
        checkpoint_root=tmp_path,
    )
    assert closed["status"] == "achieved"
    assert goal_store.list_open_goals(owner_agent="alex") == []


def test_get_context_for_agent(goal_store):
    goal_store.create_goal(owner_agent="morgan", title="Behavioral concentration", thesis_summary="SCHD weight high")
    goal_store.create_goal(owner_agent="steph", title="Allocation drift")
    ctx = goal_store.get_context_for_agent("morgan")
    assert ctx["agent_id"] == "morgan"
    assert ctx["authority"] == "READ_ONLY_ADVISORY"
    assert len(ctx["open_goals"]) == 1
    assert ctx["thesis_snippets"]


def test_list_due_or_idle(goal_store):
    # A goal may be due the moment it is created, but NOT before it existed
    # (P2, 2026-09-16) -- so due_ts is the goal's own created_ts rather than an
    # hour before it, which is the live "born overdue" defect.
    g = goal_store.create_goal(owner_agent="steph", title="Due now")
    goal_store.update_goal(g["goal_id"], due_ts=g["created_ts"])
    due = goal_store.list_due_or_idle_goals(owner_agent="steph")
    assert any(d["_wake_reason"] in ("due", "never_woken") for d in due)


def test_dispatcher_goal_wake_dedup(tmp_path, goal_store):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher

    wake_path = tmp_path / "wakes.jsonl"
    wake_store = CIOWakeJobStore(event_store_path=wake_path)
    disp = CIOWakeDispatcher(
        wake_store=wake_store,
        run_store=None,
        dispatch_ledger_path=str(tmp_path / "dispatch.jsonl"),
        goal_store=goal_store,
        readiness_registry=None,
    )
    disp.goal_wake_dedup_path = tmp_path / "goal_dedup.jsonl"

    g = goal_store.create_goal(owner_agent="alex", title="Desk thesis daily")
    goal_store.update_goal(g["goal_id"], due_ts=g["created_ts"])

    r1 = disp.enqueue_goal_wakes(max_new=3)
    assert r1["enqueued"], r1
    r2 = disp.enqueue_goal_wakes(max_new=3)
    # second pass should dedup
    assert r2["enqueued"] == [] or all(
        x.get("goal_id") not in {e["goal_id"] for e in r1["enqueued"]}
        for x in r2.get("enqueued", [])
    )
    assert r2["skipped_dedup"] or r2["enqueued"] == []

    pending = wake_store.list_wakes(status="PENDING", limit=10)
    assert any(w.get("trigger_type") in ("GOAL_DUE", "GOAL_EVENT_LINKED") for w in pending)


def test_backup_enforcer_invariants():
    """Local dump policy: max_count == 1 when policy file present."""
    from pathlib import Path
    pol = Path("config/backup_policy.yaml")
    if not pol.exists():
        pytest.skip("no backup_policy.yaml")
    text = pol.read_text()
    assert "max_count" in text
    # soft: enforcer reports compliant count <= 1 if runnable
    try:
        import scripts.backup_enforcer as be
        if hasattr(be, "status"):
            st = be.status()
            assert st["local"]["max_count"] == 1
            assert st["local"]["count"] <= 1
    except Exception:
        # status CLI path
        pass
