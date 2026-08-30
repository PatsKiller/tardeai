"""InstrumentRecord@v1 — the persistent unit, and the cognition/behaviour split.

The operator's law for this slice:
  MBI_BEHAVIOR = 0   no broker, no size from a lesson, no invented delta
  MBI_COGNITION = 1  memory MUST change the next question, the eligibility,
                     the notify priority, or the narrative — and a write that
                     changes none of them is a FAILED persist, not a no-op.

Both halves are enforced in code here rather than asked for in a docstring,
because a memory system that cannot fail is a memory system that cannot be
trusted to have learned anything.
"""
import json

import pytest

from scripts.lib.cio_instrument_record import (
    BEHAVIOR_FIELDS, CASH_SLEEVE, COGNITION_FIELDS, BehaviorWriteRefused,
    CognitionNoOp, InstrumentRecordStore, apply_cognition, cc_narrative,
    content_hash, hash_changed, is_mintable, new_record, parse_subject_key,
    subject_key,
)


# ── subject keys ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,name,expect", [
    ("HELD", "schd", "HELD:SCHD"),
    ("held", "SCHD", "HELD:SCHD"),
    ("EXIT", "axti", "EXIT:AXTI"),
    ("WATCH", "spcx", "WATCH:SPCX"),
    ("SLEEVE", "CASH", "SLEEVE:CASH"),
])
def test_subject_keys_are_canonical(kind, name, expect):
    assert subject_key(kind, name) == expect


def test_the_cash_sleeve_is_a_sleeve_not_a_ticker():
    """The $630k question is SLEEVE:CASH. A fake CASH holding is how it leaks."""
    assert CASH_SLEEVE == "SLEEVE:CASH"
    assert parse_subject_key(CASH_SLEEVE) == ("SLEEVE", "CASH")
    ok, _ = is_mintable("SLEEVE", "CASH")
    assert ok


# ── what must never get a record ──────────────────────────────────────────

@pytest.mark.parametrize("sym", ["CASH", "USD", "SPAXX", "FDRXX", "TEST", "SPACEX_TEST"])
def test_cash_and_test_tickers_are_refused(sym):
    ok, why = is_mintable("HELD", sym)
    assert not ok and why == "cash_or_test_ticker"


@pytest.mark.parametrize("mv", [0.0, 1.5, 49.99])
def test_dust_is_refused(mv):
    ok, why = is_mintable("HELD", "SRNE", market_value=mv)
    assert not ok and why == "dust_residual"


def test_a_real_position_is_mintable():
    ok, why = is_mintable("HELD", "SCHD", market_value=50_000)
    assert ok and why == "ok"


def test_unknown_market_value_is_not_treated_as_dust():
    """Unknown MV is HELD, never dust — absence of a number is not a small one."""
    ok, _ = is_mintable("HELD", "SCHD", market_value=None)
    assert ok


# ── MBI_BEHAVIOR = 0 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("field", BEHAVIOR_FIELDS)
def test_behaviour_cannot_be_written_through_cognition(field):
    rec = new_record("HELD", "SCHD")
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(rec, next_research_question="q", **{field: 1})


def test_a_record_declares_zero_behaviour_influence():
    rec = new_record("HELD", "SCHD")
    assert rec["memory_behavior_influence"] == 0
    assert rec["memory_cognition_influence"] == 1


# ── MBI_COGNITION = 1 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("next_research_question", "Did the ex-div buffer change?"),
    ("next_eligible_at", "2026-09-01T00:00:00+00:00"),
    ("notify_priority", "cc"),
])
def test_each_cognition_field_counts_as_a_persist(field, value):
    rec = new_record("HELD", "SCHD")
    out, changed = apply_cognition(rec, **{field: value})
    assert changed == [field]
    assert out[field] == value


def test_a_narrative_change_counts():
    rec = new_record("HELD", "SCHD")
    _, changed = apply_cognition(rec, narrative=cc_narrative(what="deferred"))
    assert changed == ["cc_narrative"]


def test_a_write_that_changes_nothing_is_a_failed_persist():
    """The law, stated as a test. Silence is how memory fakes learning."""
    rec = new_record("HELD", "SCHD")
    rec, _ = apply_cognition(rec, next_research_question="q1")
    with pytest.raises(CognitionNoOp):
        apply_cognition(rec, next_research_question="q1")


def test_provenance_alone_is_not_a_persist():
    """A lesson that moves no decision has not been applied."""
    rec = new_record("HELD", "SCHD")
    with pytest.raises(CognitionNoOp):
        apply_cognition(rec, lesson={"lesson_id": "L1", "claim": "defer honored"})


def test_a_probe_may_ask_without_raising():
    rec = new_record("HELD", "SCHD")
    rec, _ = apply_cognition(rec, notify_priority="cc")
    out, changed = apply_cognition(rec, notify_priority="cc", strict=False)
    assert changed == []


def test_lessons_are_support_only_and_cognition_scoped():
    rec = new_record("HELD", "SCHD")
    out, _ = apply_cognition(rec, next_research_question="q",
                             lesson={"lesson_id": "L1", "claim": "defer honored"})
    les = out["lessons"][-1]
    assert les["support_only"] is True
    assert les["applied_to"] == "cognition"


def test_notify_priority_is_constrained():
    with pytest.raises(ValueError):
        apply_cognition(new_record("HELD", "SCHD"), notify_priority="fire_now")


# ── change detection ──────────────────────────────────────────────────────

def test_hash_changed_detects_a_moved_observable():
    rec = new_record("HELD", "SCHD")
    rec, _ = apply_cognition(rec, next_research_question="q",
                             hashes={"weight": content_hash(18.0)})
    assert hash_changed(rec, "weight", 19.0) is True
    assert hash_changed(rec, "weight", 18.0) is False


def test_the_event_hash_moves_with_cognition():
    rec = new_record("HELD", "SCHD")
    a, _ = apply_cognition(rec, next_research_question="q1")
    b, _ = apply_cognition(a, next_research_question="q2")
    assert a["last_event_hash"] != b["last_event_hash"]


# ── the store ─────────────────────────────────────────────────────────────

def test_store_round_trip_and_last_write_wins(tmp_path):
    store = InstrumentRecordStore(tmp_path / "rec.jsonl")
    rec = new_record("HELD", "SCHD")
    store.upsert(rec)
    rec, _ = apply_cognition(rec, next_research_question="q2")
    store.upsert(rec)
    got = store.load("HELD:SCHD")
    assert got["next_research_question"] == "q2"
    assert len(store.all()) == 1                     # one subject, not two rows


def test_the_store_is_append_only(tmp_path):
    """History is the evidence that a lesson moved a decision. Keep every row."""
    path = tmp_path / "rec.jsonl"
    store = InstrumentRecordStore(path)
    rec = new_record("HELD", "SCHD")
    store.upsert(rec)
    rec, _ = apply_cognition(rec, next_research_question="q2")
    store.upsert(rec)
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 2


def test_a_fresh_reader_sees_persisted_state(tmp_path):
    path = tmp_path / "rec.jsonl"
    InstrumentRecordStore(path).upsert(
        apply_cognition(new_record("SLEEVE", "CASH"), notify_priority="cc")[0])
    assert InstrumentRecordStore(path).load(CASH_SLEEVE)["notify_priority"] == "cc"


def test_a_missing_store_is_empty_not_an_error(tmp_path):
    store = InstrumentRecordStore(tmp_path / "absent.jsonl")
    assert store.all() == [] and store.load("HELD:SCHD") is None


def test_the_store_is_registered_canonically():
    from scripts.lib.canonical_store_registry import registry
    entry = registry()["stores"]["cio.instrument_records"]
    assert entry["schema"] == "InstrumentRecord@v1"
    assert entry["append_only"] is True
    assert entry["id_fields"] == ["subject_key"]
