"""Lane A follow-up #3 — research/material-change selection → consumption.

Hermetic only: tmp_path + monkeypatch. No network, no live DB, no crontab.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_agent_wake import (  # noqa: E402
    FEATURE_FLAG,
    default_decide,
    run_scheduled_wake,
)
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402
from scripts.lib.wake_subject_selector import (  # noqa: E402
    SubjectCandidate,
    research_is_consumed,
)
from scripts.run_persistent_wake import run_once  # noqa: E402

SG = "b60bb80f-62f5-58b7-b3aa-3ed4ca29bede"
RESEARCH_ID = "ro-organic-001-verbatim"
MC_ID = "mc-organic-001-verbatim"
NOW = datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc)
ENV_ON = {
    FEATURE_FLAG: "1",
    "PERSISTENT_WAKE_SCHEDULE_ENABLED": "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "ad1b32a715b79b599ed78cee87f7ff49eecaccfd",
}


@pytest.fixture()
def state(tmp_path: Path):
    root = tmp_path / "state"
    root.mkdir()
    return root


def _mem_file(tmp_path: Path, rows: list[dict], name: str = "mem.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _fact(fid: str, content: str, *, hours_ago: float = 1.0, subject: str = SG):
    return {
        "fact_id": fid,
        "subject_guid": subject,
        "content": content,
        "as_of": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"),
        "relevant": True,
    }


def _research_selection(source_id: str = RESEARCH_ID) -> SubjectCandidate:
    return SubjectCandidate(
        subject_guid=SG,
        source="unconsumed_research",
        source_id=source_id,
        observed_at=NOW.isoformat().replace("+00:00", "Z"),
    )


def _effect_receipts(result: dict) -> list[dict]:
    return [r for r in (result.get("receipts") or []) if str(r.get("effect_kind") or "none") != "none"]


def test_research_selected_empty_memory_acts_changed_question(state, tmp_path):
    mem = _mem_file(tmp_path, [])
    sel = _research_selection()
    r = run_scheduled_wake(
        agent_id="cio",
        subject_guid=SG,
        state_root=state,
        memory_backend=mem,
        when=NOW,
        env=ENV_ON,
        selection=sel,
    )
    assert r["ok"] is True
    assert r["memory_empty"] is True
    assert r["wake"]["lifecycle_state"] == "SETTLED"
    assert len(r["commitments"]) == 1
    effects = _effect_receipts(r)
    assert effects, "expected a non-none effect receipt (consumption)"
    assert effects[0]["effect_kind"] == "changed_question"
    assert effects[0]["effect_ref"] == r["commitments"][0]["commitment_id"]


def test_receipt_source_id_equals_original_research_id(state, tmp_path):
    mem = _mem_file(tmp_path, [])
    original = "research-object-id-MUST-NOT-BE-REMINTEN"
    r = run_scheduled_wake(
        agent_id="cio",
        subject_guid=SG,
        state_root=state,
        memory_backend=mem,
        when=NOW,
        env=ENV_ON,
        selection=_research_selection(original),
    )
    effects = _effect_receipts(r)
    assert len(effects) == 1
    assert effects[0]["source_kind"] == "research_object"
    assert effects[0]["source_id"] == original
    assert effects[0]["subject_guid"] == SG
    assert r["wake"]["research_object_ids"] == [original]
    assert (r["wake"].get("selection") or {}).get("source_id") == original


def test_memory_present_unchanged_memory_salience_path(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha thesis")])
    # Even with a research selection present, memory wins (MEMORY_SALIENCE).
    r = run_scheduled_wake(
        agent_id="cio",
        subject_guid=SG,
        state_root=state,
        memory_backend=mem,
        when=NOW,
        env=ENV_ON,
        selection=_research_selection(),
    )
    assert r["ok"] and r["commitments"]
    assert r["commitments"][0]["commitment_kind"] == "MEMORY_SALIENCE"
    effects = _effect_receipts(r)
    assert any(e["effect_kind"] == "changed_commitment" for e in effects)
    assert any(e["source_kind"] == "memory_fact" and e["source_id"] == "f1" for e in effects)


def test_neither_memory_nor_selection_refuses(state, tmp_path):
    mem = _mem_file(tmp_path, [])
    r = run_scheduled_wake(
        agent_id="cio",
        subject_guid=SG,
        state_root=state,
        memory_backend=mem,
        when=NOW,
        env=ENV_ON,
        selection=None,
    )
    assert r["ok"] is True
    assert r["memory_empty"] is True
    assert r["wake"]["lifecycle_state"] == "LOADED"
    assert r["commitments"] == []
    assert "no_relevant_memory" in r["wake"]["provenance"]["policy_decisions"]
    assert _effect_receipts(r) == []


def test_replay_same_slot_subject_one_wake_commitment_receipt(state, tmp_path):
    mem = _mem_file(tmp_path, [])
    sel = _research_selection()
    a = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON, selection=sel,
    )
    b = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON, selection=sel,
    )
    store = JsonlStore(state)
    assert store.count("wakes") == 1
    assert store.count("commitments") == 1
    # Load-time none-effect receipts + one decision effect receipt on first run only
    effect_rows = [
        row for row in store.iter("receipts")
        if str(row.get("effect_kind") or "none") != "none"
    ]
    assert len(effect_rows) == 1
    assert a["wake"]["wake_id"] == b["wake"]["wake_id"]
    assert b.get("replay_suppressed") is True


def test_negative_control_effect_kind_none_does_not_mark_consumed():
    """§6: effect_kind='none' is never consumption maturity."""
    none_receipt = {
        "agent_id": "cio",
        "source_kind": "research_object",
        "source_id": RESEARCH_ID,
        "effect_kind": "none",
    }
    assert research_is_consumed(
        agent_id="cio",
        research_object_id=RESEARCH_ID,
        receipts=[none_receipt],
    ) is False
    real = dict(none_receipt, effect_kind="changed_question")
    assert research_is_consumed(
        agent_id="cio",
        research_object_id=RESEARCH_ID,
        receipts=[none_receipt, real],
    ) is True


def test_default_decide_selection_reaches_context_unchanged():
    ctx = {
        "memory_facts": [],
        "selection": {
            "source": "unconsumed_research",
            "source_id": RESEARCH_ID,
            "observed_at": "2026-09-08T03:00:00Z",
        },
    }
    d = default_decide(ctx)
    assert d["act"] is True
    assert d["allow_empty_memory"] is True
    assert d["effect_kind"] == "changed_question"
    assert d["primary_source_kind"] == "research_object"
    assert d["primary_source_id"] == RESEARCH_ID


def test_material_change_selection_acts_when_memory_empty(state, tmp_path):
    mem = _mem_file(tmp_path, [])
    sel = SubjectCandidate(
        subject_guid=SG,
        source="material_change",
        source_id=MC_ID,
        observed_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON, selection=sel,
    )
    assert r["ok"] and r["commitments"]
    effects = _effect_receipts(r)
    assert effects[0]["effect_kind"] == "changed_question"
    assert effects[0]["source_kind"] == "material_change"
    assert effects[0]["source_id"] == MC_ID


def test_run_once_threads_selector_candidate_into_wake(state, tmp_path, capsys):
    """CLI path: selector candidate source_id must reach the wake, not log-only."""
    mem = _mem_file(tmp_path, [])
    research = [{
        "research_object_id": RESEARCH_ID,
        "subject_guid": SG,
        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
    }]
    rc = run_once(
        agent_id="cio",
        subject_guid=None,
        dry_run=False,
        env={**ENV_ON, "TRADEAI_PERSISTENT_WAKE_STATE": str(state)},
        when=NOW,
        state_root=state,
        memory_backend=mem,
        research_objects=research,
        receipts=[],
        material_changes=[],
        limit=1,
    )
    assert rc == 0
    store = JsonlStore(state)
    wakes = list(store.iter("wakes"))
    assert len(wakes) == 1
    assert wakes[0]["lifecycle_state"] == "SETTLED"
    assert wakes[0]["research_object_ids"] == [RESEARCH_ID]
    effects = [
        r for r in store.iter("receipts")
        if str(r.get("effect_kind") or "none") != "none"
    ]
    assert len(effects) == 1
    assert effects[0]["source_id"] == RESEARCH_ID
    out = capsys.readouterr().out
    assert "selection_source" in out
    assert RESEARCH_ID in out or "selection_source_id" in out
