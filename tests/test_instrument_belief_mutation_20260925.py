#!/usr/bin/env python3
"""Agentic-memory tranche 1, Slice 2: a belief written from settled outcomes
changes the next judgment — and can never carry behaviour.

D2 acceptance item 3 (mutation test): two state roots identical except one
record carries a `beliefs` block; the dispatcher route / next question and the
persistent-wake commitment differ, and no BEHAVIOR_FIELDS key appears anywhere
in either output.

    .venv/bin/python -m pytest tests/test_instrument_belief_mutation_20260925.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import cio_belief_writer as bw  # noqa: E402
from scripts.lib import persistent_agent_wake as paw  # noqa: E402
from scripts.lib.cio_instrument_record import (  # noqa: E402
    BEHAVIOR_FIELDS,
    BELIEF_SCHEMA,
    DEFAULT_PATH,
    BehaviorWriteRefused,
    CognitionNoOp,
    InstrumentRecordStore,
    apply_belief,
    belief_sentence,
    latest_belief,
    new_record,
    weak_beliefs,
)
from scripts.lib.cio_rehydrate import gate_input_from_record  # noqa: E402
from scripts.lib.cio_research_gate import decide as gate_decide  # noqa: E402
from scripts.lib.cio_research_preflight import decide_after_load  # noqa: E402

NOW = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)

WEAK = {
    "belief_key": "HELD:MCD|TRIM|30d",
    "population": "advisory_verdict",
    "horizon": "30d",
    "recommendation": "TRIM",
    "sample_size": 6,
    "successful": 1,
    "success_rate": 0.166667,
    "outcome_ids": [f"adv:row{i}:30d" for i in range(6)],
    "lesson_ids": [],
    "belief_proposal_id": "bp-weak-1",
    "revision": 1,
    "as_of": "2026-09-25T14:00:00+00:00",
}


def _walk(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)
    return out


def _root(tmp_path: Path, name: str, *, belief: dict | None) -> Path:
    root = tmp_path / name
    store = InstrumentRecordStore(root / DEFAULT_PATH)
    rec = new_record("HELD", "MCD", symbols=["MCD"], thesis_ref="thesis:MCD:v3")
    if belief is not None:
        rec, _ = apply_belief(rec, belief=belief)
    store.upsert(rec)
    return root


# ── the rail ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", BEHAVIOR_FIELDS)
def test_a_belief_may_not_carry_behaviour_anywhere_in_the_block(field):
    rec = new_record("HELD", "MCD", symbols=["MCD"])
    nested = dict(WEAK, provenance={"note": {field: 1}})
    with pytest.raises(BehaviorWriteRefused):
        apply_belief(rec, belief=nested)
    top = dict(WEAK); top[field] = 1
    with pytest.raises(BehaviorWriteRefused):
        apply_belief(rec, belief=top)


def test_a_belief_may_not_request_live_mutation():
    with pytest.raises(BehaviorWriteRefused):
        apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=dict(WEAK, live_mutation=True))


def test_apply_belief_writes_the_block_and_declares_zero_behaviour_influence():
    rec, changed = apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=WEAK)
    assert changed == ["beliefs"]
    blk = rec["beliefs"][0]
    assert blk["schema"] == BELIEF_SCHEMA
    assert blk["live_mutation"] is False and blk["memory_behavior_influence"] == 0
    assert latest_belief(rec)["belief_key"] == WEAK["belief_key"]
    assert weak_beliefs(rec)[0]["belief_proposal_id"] == "bp-weak-1"


def test_an_unchanged_belief_is_a_failed_persist():
    rec, _ = apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=WEAK)
    with pytest.raises(CognitionNoOp):
        apply_belief(rec, belief=WEAK)
    same, changed = apply_belief(rec, belief=WEAK, strict=False)
    assert changed == [] and same["beliefs"] == rec["beliefs"]
    rev2 = dict(WEAK, belief_proposal_id="bp-weak-2", revision=2, successful=2, success_rate=0.333333)
    rec2, changed = apply_belief(rec, belief=rev2)
    assert changed == ["beliefs"] and len(rec2["beliefs"]) == 1  # replaced, not appended
    assert rec2["beliefs"][0]["revision"] == 2


def test_a_missing_required_field_is_refused():
    with pytest.raises(ValueError):
        apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief={"belief_key": "x"})


def test_belief_sentence_is_numbers_not_instructions():
    s = belief_sentence(WEAK)
    assert "1 of 6" in s and "0.17" in s and "TRIM" in s
    assert not any(w in s.lower() for w in ("buy", "sell now", "order", "size"))


# ── mutation: dispatcher path (Path A) ─────────────────────────────────────

def test_gate_input_carries_the_belief_and_routes_flash_to_pro():
    rec, _ = apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=WEAK)
    bare = new_record("HELD", "MCD", symbols=["MCD"])
    inp_with = gate_input_from_record(rec, plan={"material": True})
    inp_without = gate_input_from_record(bare, plan={"material": True})
    assert inp_with["belief"][0]["belief_key"] == WEAK["belief_key"]
    assert inp_without["belief"] == []
    d_with = gate_decide(inp_with, now=NOW)
    d_without = gate_decide(inp_without, now=NOW)
    assert d_without["decision"] == "flash"
    assert d_with["decision"] == "pro"
    assert d_with["reason"] == "prior_belief_weak_escalates"
    assert d_with["belief_key"] == WEAK["belief_key"]
    assert "wrong 5 of 6" in d_with["belief_question"]
    assert not (_walk(d_with) & set(BEHAVIOR_FIELDS))


def test_a_strong_belief_does_not_escalate():
    strong = dict(WEAK, successful=5, success_rate=0.833333, belief_proposal_id="bp-strong")
    rec, _ = apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=strong)
    d = gate_decide(gate_input_from_record(rec, plan={"material": True}), now=NOW)
    assert d["decision"] == "flash"


def test_a_belief_below_the_sample_floor_does_not_escalate():
    thin = dict(WEAK, sample_size=3, successful=0, success_rate=0.0, belief_proposal_id="bp-thin",
                outcome_ids=WEAK["outcome_ids"][:3])
    rec, _ = apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=thin)
    d = gate_decide(gate_input_from_record(rec, plan={"material": True}), now=NOW)
    assert d["decision"] == "flash"


def test_decide_after_load_differs_with_and_without_the_belief(tmp_path):
    """The D2 mutation test on the scheduled dispatcher path."""
    with_root = _root(tmp_path, "with", belief=WEAK)
    without_root = _root(tmp_path, "without", belief=None)
    out_with = decide_after_load("HELD:MCD", plan={"material": True}, root=with_root, now=NOW)
    out_without = decide_after_load("HELD:MCD", plan={"material": True}, root=without_root, now=NOW)
    assert out_with["decision"] != out_without["decision"]
    assert out_with["decision"] == "pro" and out_with["reason"] == "prior_belief_weak_escalates"
    assert out_without["decision"] == "flash"
    assert not (_walk(out_with) & set(BEHAVIOR_FIELDS))
    assert not (_walk(out_without) & set(BEHAVIOR_FIELDS))


def test_after_cycle_the_belief_question_becomes_the_next_question():
    from scripts.lib.cio_rehydrate import apply_after_cycle

    rec, _ = apply_belief(new_record("HELD", "MCD", symbols=["MCD"]), belief=WEAK)
    decision = gate_decide(gate_input_from_record(rec, plan={"material": True}), now=NOW)
    updated, changed = apply_after_cycle(rec, decision=decision, now=NOW, strict=False)
    assert "next_research_question" in changed
    assert updated["next_research_question"] == decision["belief_question"]
    assert updated["last_outcome"] == "pro"  # the route, not a market outcome


# ── mutation: persistent-wake path (Path B) ────────────────────────────────

def _context(belief):
    return {
        "wake_id": "w1", "agent_id": "cio", "subject_guid": "guid-mcd",
        "memory_facts": [], "comm_events": [], "operator_turns": [], "memory_empty": True,
        "selection": {"source": "instrument_record_due", "source_id": "HELD:MCD"},
        "instrument_record": {"subject_key": "HELD:MCD", "thesis_ref": "thesis:MCD:v3"},
        "instrument_belief": belief,
    }


def test_default_decide_commitment_differs_with_and_without_the_belief():
    with_b = paw.default_decide(_context(WEAK))
    without_b = paw.default_decide(_context(None))
    assert with_b["commitment"]["commitment_kind"] == "BELIEF_REVIEW"
    assert without_b["commitment"]["commitment_kind"] == "SELECTION_OBSERVATION"
    assert with_b["commitment"]["claim"] != without_b["commitment"]["claim"]
    assert "HELD:MCD|TRIM|30d@rev1" in with_b["commitment"]["claim"]
    # Source provenance is the selection's own — the belief is context, not a source kind.
    assert with_b["primary_source_kind"] == without_b["primary_source_kind"]
    assert with_b["primary_source_id"] == "HELD:MCD"
    assert not (_walk(with_b) & set(BEHAVIOR_FIELDS))


def test_a_changed_belief_changes_the_commitment_claim():
    a = paw.default_decide(_context(WEAK))["commitment"]["normalized_claim"]
    b = paw.default_decide(_context(dict(WEAK, revision=2, successful=2, success_rate=0.333333)))["commitment"]["normalized_claim"]
    assert a != b


def test_operator_question_still_outranks_the_belief():
    ctx = _context(WEAK)
    ctx["operator_turns"] = [{"turn_id": "t1", "sanitized_body": "what about MCD?"}]
    assert paw.default_decide(ctx)["commitment"]["commitment_kind"] == "OPERATOR_QUESTION"


def test_l3_question_carries_thesis_narrative_and_belief():
    rec = {"thesis_ref": "thesis:MCD:v3",
           "cc_narrative": {"what": "Franchise margin thesis", "thesis_fit": "intact"},
           "next_research_question": "Did the price increases hold traffic?"}
    s = paw.instrument_record_context_sentence(rec, WEAK)
    assert "thesis:MCD:v3" in s and "Franchise margin thesis" in s and "intact" in s
    assert "Did the price increases hold traffic?" in s
    assert "1 of 6" in s
    assert paw.instrument_record_context_sentence(None, None) == ""


def test_wake_loads_the_record_for_an_instrument_record_selection(tmp_path, monkeypatch):
    root = _root(tmp_path, "state", belief=WEAK)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    out = paw._load_instrument_record_for_selection(
        {"source": "instrument_record_due", "source_id": "HELD:MCD"}, "guid-mcd")
    assert out["status"] == "LOADED" and out["subject_key"] == "HELD:MCD"
    assert latest_belief(out["record"])["belief_key"] == WEAK["belief_key"]
    assert out["store_path"].startswith(str(root))
    none = paw._load_instrument_record_for_selection({"source": "unconsumed_research", "source_id": "ro1"}, "g")
    assert none["status"] == "NO_SUBJECT" and none["record"] is None


# ── the writer: settled rows only, through the rail ────────────────────────

def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_writer_builds_a_belief_from_six_settled_advisory_outcomes_and_nothing_else(tmp_path):
    root = tmp_path / "state"
    store = InstrumentRecordStore(root / DEFAULT_PATH)
    store.upsert(new_record("HELD", "MCD", symbols=["MCD"]))
    store.upsert(new_record("WATCH", "V", symbols=["V"]))
    adv = [{"source_row_id": f"r{i}", "symbol": "MCD", "verdict": "TRIM", "horizon_d": 30,
            "correct": i == 0, "scored_at": f"2026-09-{10+i:02d}T00:00:00+00:00"} for i in range(6)]
    adv.append({"source_row_id": "v1", "symbol": "V", "verdict": "HOLD", "horizon_d": 30, "correct": True})  # n=1
    adv.append({"source_row_id": "x1", "symbol": "XYZ", "verdict": "BUY", "horizon_d": 30, "correct": True})  # no record
    adv.append({"source_row_id": "p1", "symbol": "MCD", "verdict": "TRIM", "horizon_d": 60, "correct": None})  # unsettled
    _write_jsonl(root / bw.ADVISORY_OUTCOMES_REL, adv)
    _write_jsonl(root / bw.KB_LESSONS_REL, [
        {"id": "kb-ratified", "status": "ratified", "symbols": ["MCD"]},
        {"id": "kb-candidate", "status": "candidate", "symbols": ["MCD"]},
    ])
    _write_jsonl(root / bw.CIO_LESSONS_REL, [
        {"lesson_id": "cio-prov", "promotion_stage": "PROVISIONAL", "scope": {"symbols": ["MCD"]}},
    ])

    out = bw.update_beliefs_from_settled(root, wake_root=None, apply=True, now="2026-09-25T18:50:00+00:00")
    assert out["written_beliefs"] == 1 and out["subjects_written"] == ["HELD:MCD"]
    assert out["skipped"]["advisory_no_record"] == 1 and out["skipped"]["advisory_no_settled_bit"] == 1
    assert out["groups"]["group_unqualified"] == 1  # V with n=1

    rec = InstrumentRecordStore(root / DEFAULT_PATH).load("HELD:MCD")
    b = latest_belief(rec)
    assert b["belief_key"] == "HELD:MCD|TRIM|30d" and b["sample_size"] == 6 and b["successful"] == 1
    assert b["lesson_ids"] == ["kb-ratified"]  # PROVISIONAL / candidate never reach a belief
    assert b["revision"] == 1 and b["live_mutation"] is False
    assert (root / bw.LATEST_REL).is_file()
    assert json.loads((root / bw.LATEST_REL).read_text())["written_beliefs"] == 1

    # Idempotent: same settled rows -> no new revision, no-op counted.
    again = bw.update_beliefs_from_settled(root, wake_root=None, apply=True, now="2026-09-25T19:00:00+00:00")
    assert again["written_beliefs"] == 0 and again["noop"] == 1

    # A new settled row -> revision 2, different proposal id.
    adv.append({"source_row_id": "r6", "symbol": "MCD", "verdict": "TRIM", "horizon_d": 30, "correct": True,
                "scored_at": "2026-09-20T00:00:00+00:00"})
    _write_jsonl(root / bw.ADVISORY_OUTCOMES_REL, adv)
    third = bw.update_beliefs_from_settled(root, wake_root=None, apply=True, now="2026-09-26T18:50:00+00:00")
    assert third["written_beliefs"] == 1
    b2 = latest_belief(InstrumentRecordStore(root / DEFAULT_PATH).load("HELD:MCD"))
    assert b2["revision"] == 2 and b2["sample_size"] == 7 and b2["belief_proposal_id"] != b["belief_proposal_id"]


def test_writer_scores_checkpoints_only_with_a_direction_and_commitments_only_when_settled(tmp_path):
    root = tmp_path / "state"
    wake_root = tmp_path / "wake"
    store = InstrumentRecordStore(root / DEFAULT_PATH)
    store.upsert(new_record("HELD", "MCD", symbols=["MCD"]))
    obs = [{"outcome_id": f"o{i}", "decision_id": f"d{i}", "horizon": "5_sessions", "observed_at": "2026-09-20T00:00:00+00:00",
            "original_decision_state": {"symbol": "MCD", "recommendation": "TRIM"},
            "realized_state": {"change_pct": -1.0 if i < 4 else 2.0}} for i in range(6)]
    obs.append({"outcome_id": "hold", "decision_id": "dh", "horizon": "5_sessions",
                "original_decision_state": {"symbol": "MCD", "recommendation": "HOLD"},
                "realized_state": {"change_pct": -3.0}})  # HOLD never scored
    obs.append({"outcome_id": "linked", "decision_id": "dl", "horizon": "5_sessions",
                "original_decision_state": {"symbol": "MCD", "recommendation": "TRIM"},
                "realized_state": {"linked": True}})  # today's shape: no price delta
    _write_jsonl(root / bw.OBSERVATIONS_REL, obs)
    _write_jsonl(wake_root / bw.COMMITMENT_OUTCOMES_NAME, [
        {"commitment_id": f"c{i}", "outcome_id": f"co{i}", "subject_guid": "guid-mcd", "horizon": "7d",
         "stance": "BEARISH", "outcome": "CONFIRMED" if i < 2 else "REFUTED"} for i in range(5)
    ] + [{"commitment_id": "cx", "subject_guid": "guid-mcd", "horizon": "7d", "outcome": "EXPIRED"},
         {"commitment_id": "cy", "subject_guid": "guid-mcd", "horizon": "7d", "outcome": "INSUFFICIENT_EVIDENCE"}])

    out = bw.update_beliefs_from_settled(root, wake_root=wake_root, apply=True,
                                         subject_key_for_guid=lambda g: "HELD:MCD" if g == "guid-mcd" else None,
                                         now="2026-09-25T18:50:00+00:00")
    assert out["settled_rows"] == {"advisory": 0, "checkpoint": 6, "governed_commitment": 5}
    assert out["skipped"]["checkpoint_no_direction"] == 2
    assert out["skipped"]["commitment_not_settled"] == 2
    assert out["written_beliefs"] == 2
    rec = InstrumentRecordStore(root / DEFAULT_PATH).load("HELD:MCD")
    keys = {b["belief_key"]: b for b in rec["beliefs"]}
    assert keys["HELD:MCD|TRIM|5_sessions|checkpoint"]["successful"] == 4
    assert keys["HELD:MCD|BEARISH|7d|governed_commitment"]["success_rate"] == 0.4
