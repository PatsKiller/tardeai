"""An unanswered operator turn is selected for its own subject.

Research was filling every wake slot, so operator rows after 2026-09-29 never
became a subject. One slot is reserved for the newest eligible turn. Memory
influence is not involved: this only chooses who the wake is about.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.persistent_agent_wake import FEATURE_FLAG as WAKE_FLAG
from scripts.lib.persistent_wake_schedule import FEATURE_FLAG as SCHED_FLAG
from scripts.lib.wake_subject_selector import (
    SOURCE_OPERATOR_TURN,
    load_selection_inputs,
    select_subjects,
)
from scripts.run_persistent_wake import run_once

NOW = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
ENV_BOTH = {
    WAKE_FLAG: "1",
    SCHED_FLAG: "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "dbb8628ab962bdb9e398ae3663de9284f78bf6aa",
}


def _ro(sg: str, rid: str) -> dict:
    return {"subject_guid": sg, "research_object_id": rid, "published_at": "2026-10-05T12:00:00Z"}


def _turn(
    turn_id: int,
    subject: str,
    *,
    at: str = "2026-10-05T16:32:00Z",
    text: str = "what changed after the close",
    role: str = "operator",
    answered: bool = False,
    channel: str = "telegram",
) -> dict:
    return {
        "id": turn_id,
        "role": role,
        "sanitized_body": text,
        "subject_guid": subject,
        "occurred_at": at,
        "answered": answered,
        "channel": channel,
    }


def _research_fill() -> list[dict]:
    return [_ro("g-a", "r1"), _ro("g-b", "r2"), _ro("g-c", "r3"), _ro("g-d", "r4")]


def test_newest_unanswered_turn_takes_a_slot_when_research_would_fill_the_limit():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=_research_fill(),
        operator_turns=[
            _turn(655, "g-old", at="2026-09-30T15:00:00Z"),
            _turn(781, "g-new", at="2026-10-05T16:32:00Z"),
        ],
    )
    assert len(cands) == 3
    assert cands[0].source == SOURCE_OPERATOR_TURN
    assert cands[0].subject_guid == "g-new"
    assert cands[0].source_id == "781"
    assert [c.source for c in cands].count(SOURCE_OPERATOR_TURN) == 1
    assert all(c.subject_guid != "g-new" or c.source == SOURCE_OPERATOR_TURN for c in cands)
    assert "g-old" not in {c.subject_guid for c in cands}


def test_turn_is_not_attached_to_a_different_subject():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=_research_fill(),
        operator_turns=[_turn(790, "g-own")],
    )
    chosen = next(c for c in cands if c.source == SOURCE_OPERATOR_TURN)
    assert chosen.subject_guid == "g-own"
    assert chosen.source_id == "790"
    assert {c.subject_guid for c in cands if c.source != SOURCE_OPERATOR_TURN} <= {
        "g-a", "g-b", "g-c", "g-d"
    }


def test_one_operator_slot_leaves_the_instrument_reservation_intact():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=_research_fill(),
        operator_turns=[_turn(790, "g-own")],
        instrument_records=[
            {"subject_key": "HELD:MCD", "next_eligible_at": "2026-09-01T00:00:00Z"},
            {"subject_key": "HELD:V", "next_eligible_at": "2026-09-01T00:00:00Z"},
        ],
        guid_for_symbol=lambda sym: f"g-{sym.lower()}",
    )
    assert [c.source for c in cands] == [
        "operator_turn",
        "unconsumed_research",
        "instrument_record_due",
    ]
    assert cands[2].source_id == "HELD:MCD"


def test_answered_approval_role_and_missing_subject_are_skipped():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=[_ro("g-a", "r1")],
        operator_turns=[
            _turn(1, "g-answered", answered=True),
            _turn(2, "g-approve", text="/approve 12"),
            _turn(3, "g-callback", channel="telegram_callback"),
            _turn(4, "g-agent", role="agent"),
            _turn(5, ""),
        ],
    )
    assert [c.source for c in cands] == ["unconsumed_research"]


def test_non_none_receipt_consumes_the_turn_and_effect_none_does_not():
    turn = _turn(781, "g-new")
    consumed = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=_research_fill(),
        operator_turns=[turn],
        receipts=[{
            "agent_id": "cio",
            "source_kind": "operator_turn",
            "source_id": "781",
            "effect_kind": "changed_question",
        }],
    )
    assert SOURCE_OPERATOR_TURN not in [c.source for c in consumed]
    still = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=_research_fill(),
        operator_turns=[turn],
        receipts=[{
            "agent_id": "cio",
            "source_kind": "operator_turn",
            "source_id": "781",
            "effect_kind": "none",
        }],
    )
    assert still[0].source == SOURCE_OPERATOR_TURN
    assert still[0].source_id == "781"


def test_no_operator_turns_keeps_the_research_fill():
    cands = select_subjects(
        "cio", limit=3, now=NOW, research_objects=_research_fill(), operator_turns=[]
    )
    assert [c.source for c in cands] == ["unconsumed_research"] * 3


def test_loader_reads_jsonl_and_fail_soft_on_a_dead_database(tmp_path, monkeypatch):
    path = tmp_path / "turns.jsonl"
    path.write_text(json.dumps(_turn(781, "g-new")) + "\n")
    loaded = load_selection_inputs({"TRADEAI_WAKE_OPERATOR_TURNS_PATH": str(path)})
    assert loaded["operator_turns"][0]["id"] == 781

    missing = load_selection_inputs({
        "TRADEAI_WAKE_OPERATOR_TURNS_PATH": str(tmp_path / "missing.jsonl")
    })
    assert missing["operator_turns"] == []

    import db_adapter
    import scripts.lib.wake_comms_history as hist

    class Boom:
        def recent_operator_turns(self, limit=50):
            raise RuntimeError("db down")

    monkeypatch.setattr(hist, "DbCommsHistory", Boom)
    monkeypatch.setattr(db_adapter, "get_connection", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    from scripts.lib import wake_subject_selector as sel

    assert sel._load_operator_turns({}) == []


def test_runner_select_only_names_the_operator_turn_and_writes_nothing(tmp_path, capsys):
    state = tmp_path / "s"
    rc = run_once(
        agent_id="cio",
        subject_guid=None,
        env=ENV_BOTH,
        when=NOW,
        state_root=state,
        memory_backend=None,
        research_objects=[],
        receipts=[],
        material_changes=[],
        operator_turns=[_turn(790, "g-own", at="2026-10-05T20:32:00Z")],
        select_only=True,
        limit=3,
    )
    assert rc == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["outcome"] == "select_only"
    sources = [c["source"] for c in line["candidates"]]
    assert sources == ["operator_turn"]
    assert line["candidates"][0]["source_id"] == "790"
    assert line["candidates"][0]["subject_guid"] == "g-own"
    assert not state.exists() or not any(Path(state).rglob("wakes.jsonl"))
