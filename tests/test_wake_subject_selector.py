"""Subject selector for scheduled wakes — hermetic, no crontab/network/DB."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_agent_wake import FEATURE_FLAG as WAKE_FLAG  # noqa: E402
from scripts.lib.persistent_wake_schedule import FEATURE_FLAG as SCHED_FLAG  # noqa: E402
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402
from scripts.lib.wake_subject_selector import (  # noqa: E402
    SOURCE_MATERIAL_CHANGE,
    SOURCE_UNCONSUMED_RESEARCH,
    select_subjects,
)
from scripts.run_persistent_wake import run_once  # noqa: E402

NOW = datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc)
SG_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SG_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SG_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SG_D = "dddddddd-dddd-dddd-dddd-dddddddddddd"
ENV_BOTH = {
    WAKE_FLAG: "1",
    SCHED_FLAG: "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "bcc9cd6eb7a4e24de2fcca49e66311c4a0c97e2d",
}


def _ro(rid: str, sg: str) -> dict:
    return {
        "research_object_id": rid,
        "subject_guid": sg,
        "published_at": (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "schema_version": "ResearchObject@v1",
    }


def _receipt(*, agent_id: str, rid: str, effect_kind: str) -> dict:
    return {
        "receipt_id": f"r-{rid}-{effect_kind}",
        "agent_id": agent_id,
        "source_kind": "research_object",
        "source_id": rid,
        "effect_kind": effect_kind,
        "schema_version": "AgentConsumptionReceipt@v2",
    }


def _mc(cid: str, sg: str, *, hours_ago: float = 1.0) -> dict:
    return {
        "change_guid": cid,
        "subject_guid": sg,
        "symbol": "X",
        "kind": "MOVE",
        "observed_at": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"),
        "schema_version": "MaterialChange@v1",
    }


def test_picks_subject_with_unconsumed_research():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=[_ro("ro-1", SG_A)],
        receipts=[],
        material_changes=[],
    )
    assert len(cands) == 1
    assert cands[0].subject_guid == SG_A
    assert cands[0].source == SOURCE_UNCONSUMED_RESEARCH
    assert cands[0].source_id == "ro-1"


def test_skips_subject_with_non_none_receipt():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=[_ro("ro-1", SG_A)],
        receipts=[_receipt(agent_id="cio", rid="ro-1", effect_kind="changed_view")],
        material_changes=[],
    )
    assert cands == []


def test_does_not_skip_effect_kind_none_receipt():
    """effect_kind='none' is not consumption (INTERFACE_CONTRACTS.md §6)."""
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=[_ro("ro-1", SG_A)],
        receipts=[_receipt(agent_id="cio", rid="ro-1", effect_kind="none")],
        material_changes=[],
    )
    assert len(cands) == 1
    assert cands[0].subject_guid == SG_A


def test_picks_subject_with_recent_material_change():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=[],
        receipts=[],
        material_changes=[_mc("ch-1", SG_B, hours_ago=1)],
    )
    assert len(cands) == 1
    assert cands[0].subject_guid == SG_B
    assert cands[0].source == SOURCE_MATERIAL_CHANGE


def test_ignores_stale_material_change():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        recent_hours=24,
        research_objects=[],
        receipts=[],
        material_changes=[_mc("ch-old", SG_B, hours_ago=48)],
    )
    assert cands == []


def test_research_outranks_material_change_and_limit():
    cands = select_subjects(
        "cio",
        limit=2,
        now=NOW,
        research_objects=[_ro("ro-c", SG_C), _ro("ro-a", SG_A)],
        receipts=[],
        material_changes=[_mc("ch-b", SG_B), _mc("ch-d", SG_D)],
    )
    # Research first (A,C sorted), then material for remaining slots — limit 2 ⇒ A,C only
    assert [c.subject_guid for c in cands] == [SG_A, SG_C]
    assert all(c.source == SOURCE_UNCONSUMED_RESEARCH for c in cands)


def test_material_fills_after_research_within_limit():
    cands = select_subjects(
        "cio",
        limit=3,
        now=NOW,
        research_objects=[_ro("ro-a", SG_A)],
        receipts=[],
        material_changes=[_mc("ch-b", SG_B), _mc("ch-d", SG_D)],
    )
    assert [c.subject_guid for c in cands] == [SG_A, SG_B, SG_D]
    assert cands[0].source == SOURCE_UNCONSUMED_RESEARCH
    assert cands[1].source == SOURCE_MATERIAL_CHANGE


def test_respects_limit():
    ros = [_ro(f"ro-{i}", f"{i:08x}-0000-0000-0000-00000000000{i}") for i in range(1, 6)]
    # fix guids to be valid-looking sorted strings
    ros = [
        _ro("ro-1", "11111111-1111-1111-1111-111111111111"),
        _ro("ro-2", "22222222-2222-2222-2222-222222222222"),
        _ro("ro-3", "33333333-3333-3333-3333-333333333333"),
        _ro("ro-4", "44444444-4444-4444-4444-444444444444"),
    ]
    cands = select_subjects("cio", limit=2, now=NOW, research_objects=ros, receipts=[], material_changes=[])
    assert len(cands) == 2


def test_deterministic_order_across_repeated_calls():
    ros = [_ro("ro-b", SG_B), _ro("ro-a", SG_A), _ro("ro-c", SG_C)]
    mcs = [_mc("ch-d", SG_D), _mc("ch-b2", SG_B)]  # B already covered by research
    a = select_subjects("cio", limit=5, now=NOW, research_objects=ros, receipts=[], material_changes=mcs)
    b = select_subjects("cio", limit=5, now=NOW, research_objects=list(reversed(ros)), receipts=[], material_changes=list(reversed(mcs)))
    assert [c.subject_guid for c in a] == [c.subject_guid for c in b]
    assert [c.source_id for c in a] == [c.source_id for c in b]


def test_empty_when_nothing_qualifies():
    assert select_subjects("cio", limit=3, now=NOW, research_objects=[], receipts=[], material_changes=[]) == []


def test_runner_reports_selector_returned_no_candidates(tmp_path, capsys):
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
    )
    assert rc == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["outcome"] == "nothing_due"
    assert line["detail"] == "selector returned no candidates"
    assert "no --subject-guid" not in line["detail"]


def test_negative_control_empty_selector_writes_nothing(tmp_path):
    state = tmp_path / "s"
    assert run_once(
        agent_id="cio",
        subject_guid=None,
        env=ENV_BOTH,
        when=NOW,
        state_root=state,
        research_objects=[],
        receipts=[],
        material_changes=[],
    ) == 0
    assert JsonlStore(state).count("wakes") == 0
    assert JsonlStore(state).count("commitments") == 0
    assert JsonlStore(state).count("receipts") == 0


def test_runner_uses_selector_when_subject_omitted(tmp_path, capsys):
    state = tmp_path / "s"
    mem = tmp_path / "mem.jsonl"
    # Memory for SG_A so wake can act
    mem.write_text(json.dumps({
        "fact_id": "f1",
        "subject_guid": SG_A,
        "content": "alpha",
        "as_of": (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }) + "\n")
    rc = run_once(
        agent_id="cio",
        subject_guid=None,
        env=ENV_BOTH,
        when=NOW,
        state_root=state,
        memory_backend=mem,
        research_objects=[_ro("ro-1", SG_A)],
        receipts=[],
        material_changes=[],
        limit=3,
    )
    assert rc == 0
    assert JsonlStore(state).count("wakes") == 1
    wake = next(JsonlStore(state).iter("wakes"))
    assert wake["subject_guid"] == SG_A
    out = capsys.readouterr().out
    assert "unconsumed_research" in out or "ok" in out
