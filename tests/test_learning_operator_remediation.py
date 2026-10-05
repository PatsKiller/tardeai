"""Replay prevention is not evidence that a judgment changed."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("learning_operator_wake", ROOT / "scripts/lib/persistent_agent_wake.py")
wake = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wake
spec.loader.exec_module(wake)
from scripts.lib.persistent_wake_store import JsonlStore
from scripts.lib.wake_subject_selector import select_subjects, research_is_consumed

NOW = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
SUBJECT = "fixture-subject-a"


def run(tmp_path, turns, when=NOW, subject=SUBJECT, selection=None):
    memory = tmp_path / "memory.jsonl"
    memory.write_text("")
    return wake.run_scheduled_wake(
        agent_id="cio", subject_guid=subject, state_root=tmp_path / "state", memory_backend=memory,
        when=when, comms=wake.NullCommsHistory(turns=[dict(t, subject_guid=subject) for t in turns]), selection=selection,
        env={wake.FEATURE_FLAG: "1", "PROVENANCE_PRODUCER": "test"},
    )


def test_consumed_turn_does_not_repeat_and_new_turn_remains_eligible(tmp_path):
    turn = {"id": 115, "text": "What changed in the evidence?"}
    first = run(tmp_path, [turn])
    assert first["commitments"][0]["commitment_kind"] == "OPERATOR_QUESTION"
    second = run(tmp_path, [turn], NOW + timedelta(hours=1))
    assert not second["commitments"]
    third = run(tmp_path, [{"id": 116, "text": "What is the new premise?"}, turn], NOW + timedelta(hours=2))
    assert third["commitments"][0]["commitment_kind"] == "OPERATOR_QUESTION"
    assert any(r["source_id"] == "116" and r["effect_kind"] != "none" for r in third["receipts"])


def test_same_turn_consumption_is_subject_scoped(tmp_path):
    turn = {"id": 115, "text": "Compare both subjects"}
    first = run(tmp_path, [turn])
    second = run(tmp_path, [turn], subject="fixture-subject-b")
    assert first["commitments"] and second["commitments"]
    ids_a = {r["receipt_id"] for r in first["receipts"]}
    assert not ids_a.intersection(r["receipt_id"] for r in second["receipts"])
    assert not run(tmp_path, [turn], NOW + timedelta(hours=1), subject="fixture-subject-b")["commitments"]


def test_answered_turn_and_approval_callback_do_not_trigger_work(tmp_path):
    result = run(tmp_path, [{"id": 115, "text": "Old question", "answered": True},
                            {"id": 116, "text": "/approve example"},
                            {"id": 117, "text": "Approve", "event_type": "callback_query"}])
    assert not result["commitments"]
    assert result["wake"]["prior_operator_turn_ids"] == ["115"]


def test_competing_operator_branch_receipts_selecting_research(tmp_path):
    selection = {"subject_guid": SUBJECT, "source": "unconsumed_research", "source_id": "fixture-research-1"}
    result = run(tmp_path, [{"id": 115, "text": "Explain this first"}], selection=selection)
    receipts = list(JsonlStore(tmp_path / "state").iter("receipts"))
    selected = [r for r in receipts if r["purpose"] == "wake_selection"]
    assert selected[0]["source_id"] == "fixture-research-1"
    assert selected[0]["effect_kind"] == "none"
    assert research_is_consumed(agent_id="cio", research_object_id="fixture-research-1", receipts=receipts)
    assert result["commitments"][0]["commitment_kind"] == "OPERATOR_QUESTION"
    rows = [{"subject_guid": SUBJECT, "research_object_id": "fixture-research-1"}]
    assert select_subjects("cio", research_objects=rows, receipts=receipts, now=NOW) == []
    # New evidence has a new causal id and is eligible without reopening the turn.
    rows.append({"subject_guid": SUBJECT, "research_object_id": "fixture-research-2"})
    assert select_subjects("cio", research_objects=rows, receipts=receipts, now=NOW)[0].source_id == "fixture-research-2"


def test_age_fairness_and_priority_replace_alphabetical_selection():
    rows = [
        {"subject_guid": "a", "research_object_id": "new", "priority": "high", "produced_at": NOW.isoformat()},
        {"subject_guid": "z", "research_object_id": "old", "priority": "low", "produced_at": (NOW - timedelta(days=4)).isoformat()},
    ]
    assert select_subjects("cio", research_objects=rows, now=NOW, limit=1)[0].source_id == "old"
    rows[1]["produced_at"] = NOW.isoformat()
    assert select_subjects("cio", research_objects=rows, now=NOW, limit=1)[0].source_id == "new"
