"""Question ids must mean something, and must not move.

The defect was not cosmetic naming. Ids were assigned POSITIONALLY (`q{i+1}`),
so `q2` meant "whatever was second in the list that day". Reorder the questions
and every carried-forward answer keyed on `q2` silently attaches to a different
question — no error, just a wrong mapping.

That breaks the ladder's core premise: Flash asks question_ids, Pro answers
*those* ids, OpenAI takes the residual, and the critique judges completeness
against them. A live Grok critique flagged it on SPCX on 2026-08-29; a scan of
all 471 stored results found the same shape book-wide (q1/q2/q3 337/191/191,
q_cat_1..3 134 each).

Nothing is backfilled. These ids apply to new questions.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_hermes_research import default_questions_for_plan
from scripts.lib.cio_question_ids import (
    DIM_TO_INTENT, KNOWN_INTENTS, assign_ids, is_positional, question_id_for,
    unknown_intents,
)
from scripts.lib.research_need_decision import decide


# ---------------------------------------------------- the property that broke

def test_ids_do_not_depend_on_question_order():
    """The actual bug: reorder the list, ids must not move."""
    base = [{"intent": "catalyst_map", "text": "a"},
            {"intent": "invalidation", "text": "b"},
            {"intent": "thesis_check", "text": "c"}]
    fwd = {q["intent"]: q["question_id"] for q in assign_ids(base)}
    rev = {q["intent"]: q["question_id"] for q in assign_ids(list(reversed(base)))}
    assert fwd == rev


def test_dropping_a_question_does_not_renumber_the_rest():
    """Positional ids shifted every id after a removal. Semantic ids do not."""
    base = [{"intent": "catalyst_map"}, {"intent": "invalidation"},
            {"intent": "thesis_check"}]
    full = {q["intent"]: q["question_id"] for q in assign_ids(base)}
    short = {q["intent"]: q["question_id"] for q in assign_ids(base[1:])}
    for intent, qid in short.items():
        assert full[intent] == qid


def test_the_same_intent_yields_the_same_id_every_time():
    a = question_id_for({"intent": "invalidation"})
    b = question_id_for({"intent": "invalidation"}, index=5)
    assert a == b == "q_invalidation"


# ------------------------------------------------------------- id derivation

def test_intent_drives_the_id():
    assert question_id_for({"intent": "catalyst_map"}) == "q_catalyst_map"


def test_dim_maps_through_to_the_same_vocabulary():
    """Two vocabularies for one concept is how earlier drift bugs started."""
    assert question_id_for({"dim": "bear_case"}) == "q_bear_case"
    assert question_id_for({"dim": "what_is_priced_in"}) == "q_priced_in"
    assert set(DIM_TO_INTENT) == {"structural_drivers", "bear_case",
                                  "what_is_priced_in"}


def test_an_explicit_id_is_honoured():
    """Callers that already thought about this keep their contract."""
    assert question_id_for({"question_id": "q_custom", "intent": "regime"}) == "q_custom"
    assert question_id_for({"id": "q_legacy"}) == "q_legacy"


def test_positional_fallback_survives_a_malformed_question():
    """A question with no semantics still gets an id rather than crashing."""
    assert question_id_for({}, index=2) == "q3"


def test_duplicate_intents_are_disambiguated_not_collided():
    """Colliding ids would let the second answer overwrite the first."""
    ids = [q["question_id"] for q in assign_ids(
        [{"intent": "catalyst_map"}, {"intent": "catalyst_map"}])]
    assert ids == ["q_catalyst_map", "q_catalyst_map_2"]
    assert len(set(ids)) == 2


# ------------------------------------------------------------- end to end

@pytest.mark.parametrize("stype,expected", [
    ("S6_CONCENTRATION_OR_DISPOSITION",
     ["q_drift_attribution", "q_catalyst_map", "q_invalidation"]),
    ("S1_POSITION_LIFECYCLE",
     ["q_catalyst_map", "q_invalidation", "q_thesis_check"]),
    ("S5_CASH_DEPLOYMENT",
     ["q_deployment_candidates", "q_regime", "q_liquidity"]),
])
def test_default_questions_carry_semantic_ids(stype, expected):
    qs = assign_ids(default_questions_for_plan(
        {"situation_type": stype, "symbols": ["SCHD"]}))
    assert [q["question_id"] for q in qs] == expected


def test_no_default_question_gets_a_positional_id():
    for stype in ("S6_CONCENTRATION_OR_DISPOSITION", "S1_POSITION_LIFECYCLE",
                  "S5_CASH_DEPLOYMENT", "S3_REENTRY_CANDIDATE"):
        for q in assign_ids(default_questions_for_plan(
                {"situation_type": stype, "symbols": ["V"]})):
            assert not is_positional(q["question_id"]), (stype, q)


def test_the_v1_gate_emits_semantic_ids():
    d = decide({"symbol": "SCHD", "is_holding": True, "material": True})
    ids = [q.get("question_id") for q in d["questions"]]
    assert ids == ["q_structural_drivers", "q_bear_case", "q_priced_in"]
    assert not any(is_positional(i) for i in ids)


def test_every_default_intent_is_known():
    """An unlisted intent should be visible, not silently minted into an id."""
    for stype in ("S6_CONCENTRATION_OR_DISPOSITION", "S1_POSITION_LIFECYCLE",
                  "S5_CASH_DEPLOYMENT", "S3_REENTRY_CANDIDATE"):
        qs = default_questions_for_plan({"situation_type": stype, "symbols": ["V"]})
        assert unknown_intents(qs) == []


def test_known_intents_covers_both_vocabularies():
    assert {"catalyst_map", "invalidation", "thesis_check"} <= KNOWN_INTENTS
    assert set(DIM_TO_INTENT.values()) <= KNOWN_INTENTS


# ------------------------------------------------------------- legacy shape

@pytest.mark.parametrize("qid,expected", [
    ("q1", True), ("q2", True), ("q_cat_1", True),
    ("q_catalyst_map", False), ("q_bear_case", False), ("q_custom", False),
])
def test_is_positional_recognises_the_legacy_shapes(qid, expected):
    assert is_positional(qid) is expected


def test_nothing_was_backfilled():
    """Historical results keep their ids; this contract is for new questions."""
    from pathlib import Path

    root = Path("/home/johnclaw/trade-ai-releases/persistent-state/data/cio")
    p = root / "hermes_research_results.jsonl"
    if not p.is_file():
        pytest.skip("results store not present")
    import json

    legacy = 0
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[:400]:
        try:
            o = json.loads(line)
        except Exception:
            continue
        for a in (o.get("answers") or [])[:6]:
            if isinstance(a, dict) and is_positional(a.get("question_id")):
                legacy += 1
    assert legacy > 0, (
        "expected historical positional ids to remain untouched; a backfill "
        "would rewrite evidence rather than fix the contract")
