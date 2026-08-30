"""Rehydration: the record must actually change what the desk does next.

Slice A made memory exist. A record nothing reads is just a slower log, so
this file tests the thing that matters — that feeding the record into
ResearchNeedDecision@v2 changes the routing, and that a cycle's outcome is
written back as cognition.

The operator's two acceptance tests are at the bottom, run against the real
gate rather than a stub.
"""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cio_instrument_record import (
    CognitionNoOp, apply_cognition, content_hash, new_record,
)
from scripts.lib.cio_rehydrate import (
    DEFER_PUSH_DAYS, apply_after_cycle, attach_operator_turn,
    gate_input_from_record,
)
from scripts.lib.cio_research_gate import decide

NOW = datetime.now(timezone.utc)


def _schd_with_defer():
    rec = new_record("HELD", "SCHD", symbols=["SCHD"])
    rec, _ = attach_operator_turn(
        rec, intent="defer", text="wait for price buffer",
        plan_id="plan_79fe9e72f2d4", now=NOW)
    return rec


# ── the record feeds the gate ─────────────────────────────────────────────

def test_the_gate_input_comes_from_the_record_not_only_the_plan():
    rec = _schd_with_defer()
    inp = gate_input_from_record(rec, plan={"material": True, "symbols": ["SCHD"]})
    assert inp["next_eligible_at"] == rec["next_eligible_at"]
    assert inp["plan_id"] == "plan_79fe9e72f2d4"     # from the operator turn


def test_a_missing_record_does_not_break_rehydration():
    inp = gate_input_from_record(None, plan={"material": True, "symbols": ["X"]})
    assert inp["material"] is True and inp["next_eligible_at"] is None


# ── rule 1: defer honored ─────────────────────────────────────────────────

def test_a_defer_moves_the_question_the_date_and_the_narrative():
    rec = new_record("HELD", "SCHD", symbols=["SCHD"])
    rec, changed = attach_operator_turn(
        rec, intent="defer", text="wait for price buffer", now=NOW)
    assert set(changed) == {"next_research_question", "next_eligible_at",
                            "notify_priority", "cc_narrative"}
    assert "catalyst or earnings" in rec["next_research_question"]
    assert "wait for price buffer" in rec["next_research_question"]
    assert rec["cc_narrative"]["what"].startswith("Operator deferred:")
    pushed = datetime.fromisoformat(rec["next_eligible_at"])
    assert pushed > NOW + timedelta(days=DEFER_PUSH_DAYS - 1)


def test_the_defer_is_not_restated_twice_in_the_narrative():
    rec = _schd_with_defer()
    rec2, _ = apply_after_cycle(
        rec, lesson={"lesson_id": "L", "claim": "defer honored, no new catalyst"},
        now=NOW + timedelta(days=1))
    assert rec2["cc_narrative"]["what"].count("Operator deferred") == 1


# ── rule 2: a refused artifact must not re-ask the same prompt ────────────

@pytest.mark.parametrize("artifact", [
    {"verdict": "REJECT", "artifact_id": "a1"},
    {"verdict": "FAILED", "artifact_id": "a2"},
    {"verdict": "OK", "execution_language": True, "artifact_id": "a3"},
])
def test_a_refused_artifact_reframes_and_blocks(artifact):
    rec = _schd_with_defer()
    before = rec["next_research_question"]
    rec2, changed = apply_after_cycle(rec, artifact=artifact, now=NOW)
    assert rec2["research_blocked"] is True
    assert rec2["next_research_question"] != before
    assert "next_research_question" in changed


def test_an_accepted_artifact_does_not_flag_blocked():
    rec = _schd_with_defer()
    rec2, _ = apply_after_cycle(
        rec, artifact={"verdict": "VALID", "artifact_id": "a9"},
        decision={"next_eligible_at": (NOW + timedelta(days=2)).isoformat()},
        now=NOW)
    assert rec2.get("research_blocked") is False
    assert rec2["last_artifact_id"] == "a9"


# ── rule 3: a moved observable overrides the cadence ──────────────────────

def test_a_moved_weight_overrides_the_defer_window():
    rec = _schd_with_defer()
    # A baseline belief must exist before anything can contradict it.
    rec, _ = apply_cognition(rec, next_research_question="baseline",
                             hashes={"weight": content_hash(18.0)})
    rec2, changed = apply_after_cycle(rec, observed={"weight": 24.0}, now=NOW)
    assert "next_eligible_at" in changed
    assert datetime.fromisoformat(rec2["next_eligible_at"]) <= NOW + timedelta(seconds=1)
    assert "Weight changed" in rec2["next_research_question"]


def test_an_unmoved_observable_is_not_an_event():
    rec = _schd_with_defer()
    rec, _ = apply_cognition(rec, next_research_question="q",
                             hashes={"weight": content_hash(18.0)})
    with pytest.raises(CognitionNoOp):
        apply_after_cycle(rec, observed={"weight": 18.0}, now=NOW)


# ── MBI_BEHAVIOR stays 0 ──────────────────────────────────────────────────

def test_no_cycle_outcome_can_carry_a_size():
    from scripts.lib.cio_instrument_record import BehaviorWriteRefused
    rec = _schd_with_defer()
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(rec, next_research_question="q", size_usd=1000)


# ══ THE OPERATOR'S TWO ACCEPTANCE TESTS ═══════════════════════════════════

def test_two_cycles_same_hashes_second_is_reuse_or_skip_and_defer_survives():
    """'two cycles on SCHD with same hashes -> second is reuse/skip,
    narrative still shows defer (memory used)'."""
    rec = _schd_with_defer()
    rec, _ = apply_cognition(rec, next_research_question=rec["next_research_question"] + " ",
                             hashes={"weight": content_hash(18.0),
                                     "earnings": content_hash("2026-11-01")})

    # cycle 1
    inp1 = gate_input_from_record(
        rec, plan={"material": True, "symbols": ["SCHD"]},
        observed={"weight": 18.0, "earnings": "2026-11-01"})
    d1 = decide(inp1, now=NOW)

    # cycle 2 — nothing observable moved
    inp2 = gate_input_from_record(
        rec, plan={"material": True, "symbols": ["SCHD"]},
        observed={"weight": 18.0, "earnings": "2026-11-01"})
    d2 = decide(inp2, now=NOW + timedelta(minutes=5))

    assert d2["decision"] in {"skip", "reuse"}, d2
    assert d2.get("reason") in {"cadence_not_due", "source_index_skip_fresh",
                                "source_index_skip_unchanged",
                                "valid_on_disk_within_ttl", "not_material"}, d2
    # memory used: the defer is still what the CC would render
    assert rec["cc_narrative"]["what"].startswith("Operator deferred:")
    assert "wait for price buffer" in rec["cc_narrative"]["what"]


def test_an_earnings_hash_flip_makes_it_due_now_and_not_skip_fresh():
    """'earnings hash flip -> next_eligible_at now, decision not skip-fresh'."""
    rec = _schd_with_defer()
    rec, _ = apply_cognition(rec, next_research_question="baseline",
                             hashes={"earnings": content_hash("2026-11-01")})
    assert rec["next_eligible_at"] > NOW.isoformat()      # deferred into the future

    rec2, changed = apply_after_cycle(
        rec, observed={"earnings": "2026-09-15"}, now=NOW)

    assert "next_eligible_at" in changed
    assert datetime.fromisoformat(rec2["next_eligible_at"]) <= NOW + timedelta(seconds=1)

    inp = gate_input_from_record(
        rec2, plan={"material": True, "symbols": ["SCHD"]},
        observed={"earnings": "2026-09-15"})
    assert inp["event_fired"] is False   # already absorbed into the record
    d = decide(gate_input_from_record(
        rec, plan={"material": True, "symbols": ["SCHD"]},
        observed={"earnings": "2026-09-15"}), now=NOW)
    assert d.get("reason") != "cadence_not_due", d
    assert d.get("reason") not in {"source_index_skip_fresh"}, d


def test_first_contact_is_not_an_event():
    """An UNSET hash is not a change.

    Treating it as one fired a spurious override on every freshly migrated
    record — overriding the very defer the record was created to remember.
    Caught on the live SCHD record, where the gate routed to `flash` twice
    instead of honouring a week-long defer.
    """
    rec = _schd_with_defer()
    assert (rec.get("hashes") or {}).get("weight") is None
    inp = gate_input_from_record(rec, plan={"material": True, "symbols": ["SCHD"]},
                                 observed={"weight": 18.0})
    assert inp["event_fired"] is False
    assert inp["next_eligible_at"] == rec["next_eligible_at"]   # defer survives
    with pytest.raises(CognitionNoOp):
        apply_after_cycle(rec, observed={"weight": 18.0}, now=NOW)


def test_a_deferred_subject_is_skipped_on_cadence():
    """The whole point: memory prevents the re-run."""
    rec = _schd_with_defer()
    rec, _ = apply_cognition(rec, next_research_question="baseline",
                             hashes={"weight": content_hash(18.0)})
    d = decide(gate_input_from_record(
        rec, plan={"material": True, "symbols": ["SCHD"]},
        observed={"weight": 18.0}), now=NOW)
    assert d["decision"] == "skip" and d["reason"] == "cadence_not_due", d
