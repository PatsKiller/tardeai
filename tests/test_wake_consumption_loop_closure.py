"""Lane R — close the wake consumption loop (durable).

Observed on deployed canary 54639ff5a (2026-09-08): slots 13:00Z and 14:00Z both
SETTLED with act=true and both selected the same three sources, emitting the
same three UUIDv5 receipt ids. The receipts store did not grow. Ten other
research objects were never reached.

Cause: the selector reads the DB-regenerated feed (TRADEAI_WAKE_RECEIPTS_PATH),
which never contains receipts the runner writes to its JSONL state root. Every
feed receipt carried effect_kind='none', which INTERFACE_CONTRACTS.md §6
correctly refuses as consumption — so a consumed object read as unconsumed.

Local repair 2b2111e unions emitted receipts into selector input. This suite
independently proves that repair, extends it with a MaterialChange reevaluation
policy, and pins the §6 none-effect negative control.

Hermetic only: tmp_path. No network, no live DB, no crontab, no production writes.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.campaign_interfaces import mint_receipt_id  # noqa: E402
from scripts.lib.persistent_agent_wake import FEATURE_FLAG, run_scheduled_wake  # noqa: E402
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402
from scripts.lib.wake_subject_selector import (  # noqa: E402
    MATERIAL_CHANGE_REEVAL_HOURS,
    material_change_is_suppressed,
    research_is_consumed,
    select_subjects,
)
from scripts.run_persistent_wake import _emitted_receipts, run_once  # noqa: E402

AGENT = "cio"
RID = "research:46057"
RID2 = "research:20568"
MC_ID = "a4f78a19-fb75-5e3a-b747-23ac5b4236e7"
MC_ID_NEW = "b5e89b20-0c86-6f4b-c858-34bd6c5347f8"
SG = "b60bb80f-62f5-58b7-b3aa-3ed4ca29bede"
SG2 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
ENV_ON = {
    FEATURE_FLAG: "1",
    "PERSISTENT_WAKE_SCHEDULE_ENABLED": "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "54639ff5aaae0e3f56e6e0a327a7c99c06c5d466",
}


def _write_state(root: Path, rows: list[dict], name: str = "receipts") -> Path:
    d = root
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def _real_receipt(rid: str = RID, agent: str = AGENT, *, kind: str = "research_object",
                  effect: str = "changed_question", when: datetime | None = None) -> dict:
    when = when or NOW
    ts = when.isoformat().replace("+00:00", "Z")
    return {
        "receipt_id": mint_receipt_id(agent, kind, rid, "wake_decision"),
        "agent_id": agent,
        "source_kind": kind,
        "source_id": rid,
        "influence_source_ids": [rid],
        "effect_kind": effect,
        "effect_ref": "commitment-1",
        "acknowledged_at": ts,
        "retrieved_at": ts,
        "produced_at": ts,
    }


def _feed_receipt(rid: str = RID, agent: str = AGENT, *, kind: str = "research_object") -> dict:
    """What the DB-backed feed actually contained: effect_kind 'none'."""
    return {
        "receipt_id": "5e727887-eedd-540b-8",
        "agent_id": agent,
        "source_kind": kind,
        "source_id": rid,
        "influence_source_ids": [rid],
        "effect_kind": "none",
    }


def _mem_file(tmp_path: Path, rows: list[dict] | None = None) -> Path:
    p = tmp_path / "mem.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in (rows or [])))
    return p


# --- 2. effect_kind=none never counts ---------------------------------------

def test_feed_receipt_with_effect_none_does_not_mark_consumed():
    """§6: 'none' is never consumption. Must NOT be the repair strategy."""
    assert research_is_consumed(
        agent_id=AGENT, research_object_id=RID, receipts=[_feed_receipt()],
    ) is False


def test_real_receipt_does_mark_consumed():
    assert research_is_consumed(
        agent_id=AGENT, research_object_id=RID, receipts=[_real_receipt()],
    ) is True


# --- 1 + 5. emitted receipt prevents reselection; advances to others --------

def test_emitted_receipts_reads_the_state_store(tmp_path):
    _write_state(tmp_path, [_real_receipt()])
    got = _emitted_receipts(tmp_path)
    assert [r["source_id"] for r in got] == [RID]


def test_consumed_research_not_reselected_after_union(tmp_path):
    research = [
        {"research_object_id": RID, "subject_guid": SG, "observed_at": "2026-09-07T10:45:04Z"},
        {"research_object_id": RID2, "subject_guid": SG2, "observed_at": "2026-09-07T10:46:04Z"},
    ]
    feed = [_feed_receipt()]
    _write_state(tmp_path, [_real_receipt()])

    before = select_subjects(
        AGENT, limit=3, research_objects=research, receipts=feed, material_changes=[],
    )
    assert any(c.source_id == RID for c in before), "control must reproduce re-selection"

    after = select_subjects(
        AGENT, limit=3, research_objects=research,
        receipts=feed + _emitted_receipts(tmp_path), material_changes=[],
    )
    ids = {c.source_id for c in after}
    assert RID not in ids
    assert RID2 in ids, "selector must advance to other eligible sources"


# --- 3. unreadable receipt state fails safely --------------------------------

def test_emitted_receipts_missing_store_is_empty_and_silent(tmp_path):
    assert _emitted_receipts(tmp_path / "does-not-exist") == []


def test_emitted_receipts_corrupt_json_fails_safe(tmp_path):
    """Corrupt JSONL must not raise into the wake path."""
    d = tmp_path / "state"
    d.mkdir()
    (d / "receipts.jsonl").write_text("{not-json\n{\"partial\":\n")
    assert _emitted_receipts(d) == []


# --- 4. UUIDv5 retry idempotency --------------------------------------------

def test_uuidv5_receipt_id_stable_across_retries():
    a = mint_receipt_id(AGENT, "research_object", RID, "wake_decision")
    b = mint_receipt_id(AGENT, "research_object", RID, "wake_decision")
    assert a == b
    assert a.startswith("acr_")


def test_same_slot_replay_one_wake_one_effect_receipt(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    mem = _mem_file(tmp_path)
    sel = {
        "source": "unconsumed_research",
        "source_id": RID,
        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    a = run_scheduled_wake(
        agent_id=AGENT, subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON, selection=sel,
    )
    b = run_scheduled_wake(
        agent_id=AGENT, subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON, selection=sel,
    )
    store = JsonlStore(state)
    assert store.count("wakes") == 1
    assert store.count("commitments") == 1
    effects = [
        r for r in store.iter("receipts")
        if str(r.get("effect_kind") or "none") != "none"
    ]
    assert len(effects) == 1
    assert effects[0]["source_id"] == RID
    assert effects[0]["receipt_id"] == mint_receipt_id(
        AGENT, "research_object", RID, "wake_decision",
    )
    assert b.get("replay_suppressed") is True
    assert a["wake"]["wake_id"] == b["wake"]["wake_id"]


# --- 6. material change: not permanently consumed ----------------------------

def test_material_change_suppressed_within_reeval_window():
    consumed_at = NOW - timedelta(hours=1)
    assert material_change_is_suppressed(
        agent_id=AGENT, change_guid=MC_ID,
        receipts=[_real_receipt(MC_ID, kind="material_change", when=consumed_at)],
        now=NOW, reeval_hours=MATERIAL_CHANGE_REEVAL_HOURS,
    ) is True


def test_material_change_reevaluable_after_interval():
    consumed_at = NOW - timedelta(hours=MATERIAL_CHANGE_REEVAL_HOURS + 1)
    assert material_change_is_suppressed(
        agent_id=AGENT, change_guid=MC_ID,
        receipts=[_real_receipt(MC_ID, kind="material_change", when=consumed_at)],
        now=NOW, reeval_hours=MATERIAL_CHANGE_REEVAL_HOURS,
    ) is False


def test_material_change_none_effect_never_suppresses():
    assert material_change_is_suppressed(
        agent_id=AGENT, change_guid=MC_ID,
        receipts=[_feed_receipt(MC_ID, kind="material_change")],
        now=NOW,
    ) is False


def test_newer_material_change_version_still_selectable():
    """A new change_guid (materiality revision) is not blocked by an old receipt."""
    mcs = [
        {
            "schema_version": "MaterialChange@v1",
            "subject_guid": SG,
            "change_guid": MC_ID,
            "observed_at": (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        },
        {
            "schema_version": "MaterialChange@v1",
            "subject_guid": SG,
            "change_guid": MC_ID_NEW,
            "observed_at": (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        },
    ]
    receipts = [_real_receipt(MC_ID, kind="material_change", when=NOW - timedelta(hours=1))]
    got = select_subjects(
        AGENT, limit=3, now=NOW, research_objects=[],
        receipts=receipts, material_changes=mcs,
    )
    ids = {c.source_id for c in got}
    assert MC_ID not in ids
    assert MC_ID_NEW in ids


def test_same_material_change_version_suppressed_in_selector():
    mcs = [{
        "schema_version": "MaterialChange@v1",
        "subject_guid": SG,
        "change_guid": MC_ID,
        "observed_at": (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }]
    receipts = [_real_receipt(MC_ID, kind="material_change", when=NOW - timedelta(minutes=10))]
    got = select_subjects(
        AGENT, limit=3, now=NOW, research_objects=[],
        receipts=receipts, material_changes=mcs,
    )
    assert got == []


# --- end-to-end: run_once unions emitted receipts ----------------------------

def test_run_once_second_slot_advances_past_consumed_research(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    mem = _mem_file(tmp_path)
    # subject_guid sort puts SG2 (aaaaaaaa…) ahead of SG — first pick is RID2.
    research = [
        {"research_object_id": RID, "subject_guid": SG,
         "observed_at": "2026-09-07T10:45:04Z"},
        {"research_object_id": RID2, "subject_guid": SG2,
         "observed_at": "2026-09-07T10:46:04Z"},
    ]
    first_expected, second_expected = RID2, RID

    rc1 = run_once(
        agent_id=AGENT, subject_guid=None, env=ENV_ON, when=NOW,
        state_root=state, memory_backend=mem,
        research_objects=research,
        receipts=[_feed_receipt(first_expected)],
        material_changes=[],
        limit=1,
    )
    assert rc1 == 0
    wakes1 = list(JsonlStore(state).iter("wakes"))
    assert len(wakes1) == 1
    assert wakes1[0]["selection"]["source_id"] == first_expected

    # Slot 2 — one hour later; must advance to the other id, not re-pick the first.
    later = NOW + timedelta(hours=1)
    rc2 = run_once(
        agent_id=AGENT, subject_guid=None, env=ENV_ON, when=later,
        state_root=state, memory_backend=mem,
        research_objects=research,
        receipts=[_feed_receipt(first_expected)],
        material_changes=[],
        limit=1,
    )
    assert rc2 == 0
    wakes2 = list(JsonlStore(state).iter("wakes"))
    assert len(wakes2) == 2
    second = [w for w in wakes2 if w["schedule_slot_utc"] != wakes1[0]["schedule_slot_utc"]][0]
    assert second["selection"]["source_id"] == second_expected

    effect_ids = {
        r["source_id"]
        for r in JsonlStore(state).iter("receipts")
        if str(r.get("effect_kind") or "none") != "none"
    }
    assert effect_ids == {RID, RID2}


def test_receipt_for_different_agent_does_not_suppress(tmp_path):
    _write_state(tmp_path, [_real_receipt(agent="other-agent")])
    assert research_is_consumed(
        agent_id=AGENT, research_object_id=RID,
        receipts=_emitted_receipts(tmp_path),
    ) is False
