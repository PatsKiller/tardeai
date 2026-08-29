"""`desk_implications.notes` and `recommendation` are linted more strictly.

`do not <verb>` cannot be banned globally: the pinned legacy case
"do not sell shares before the ex-date" is ex-dividend CONTEXT and must stay
admitted, and it is grammatically identical to "do not add". No rule separates
them by shape.

It separates by **location**. Those two fields exist to tell the operator what
the desk thinks should happen; a summary does not. Measured across 471 stored
artifacts: 57 carry `do not <verb>` inside these fields (56 "do not add"), and
**zero** of those also mention ex-date/ex-dividend. The ambiguous case does not
occur where instructions live.
"""
from __future__ import annotations

import pytest

from scripts.lib.execution_language import (
    describe_field_directive, find_field_directive, find_imperative,
    instruction_field_text,
)
from scripts.lib.research_quality import critique

GATED = "2026-08-29T12:00:00+00:00"      # after IMPERATIVE_GATE_EFFECTIVE
LEGACY = "2026-08-01T12:00:00+00:00"     # before it


def _art(notes=None, recommendation=None, completed=GATED, **kw):
    a = {"summary": "SCHD steady as of 2026-08.", "sources": ["x"],
         "symbol": "SCHD", "completed_ts": completed}
    if notes is not None:
        a["desk_implications"] = {"notes": notes}
    if recommendation is not None:
        a["recommendation"] = recommendation
    a.update(kw)
    return a


# ------------------------------------------------------- the location rule

@pytest.mark.parametrize("notes", [
    "Maintain tight risk controls; do not add exposure at current levels.",
    "Do not add to position; treat as speculative lottery ticket or exit.",
    "do not add, do not average down, and either exit or demand a thesis",
    "do not buy into the print",
])
def test_do_not_verb_is_a_directive_inside_the_fields(notes):
    hit = find_field_directive(_art(notes=notes))
    assert hit, notes
    assert hit["field"] == "desk_implications.notes"
    assert hit["rule"] == "directive_negation"


def test_the_same_phrase_in_free_prose_stays_admitted():
    """The pin. Identical grammar, different location, different answer."""
    assert find_imperative("do not sell shares before the ex-date") is None
    art = _art(notes="Coverage improved.",
               summary="Note: do not sell shares before the ex-date.")
    assert find_field_directive(art) is None


def test_recommendation_is_also_instruction_shaped():
    hit = find_field_directive(_art(recommendation="do not add until confirmed"))
    assert hit and hit["field"] == "recommendation"


def test_ordinary_field_content_is_clean():
    assert find_field_directive(
        _art(notes="Dividend coverage improved; no action implied.")) is None


def test_the_ordinary_matcher_still_applies_inside_the_fields():
    """A plain imperative in a field is caught by the normal rule, not the strict one."""
    hit = find_field_directive(_art(notes="Sell half the position now."))
    assert hit and hit["rule"] == "imperative_clause"


def test_position_directives_are_caught_in_fields_too():
    hit = find_field_directive(
        _art(notes="Maintain small tracking position with hard invalidation."))
    assert hit and hit["match"].lower().startswith("maintain")


# ------------------------------------------------------------ field pickup

def test_only_the_declared_fields_are_read():
    fields = instruction_field_text(
        _art(notes="x", recommendation="y", findings="do not add here"))
    assert set(fields) == {"desk_implications.notes", "recommendation"}
    assert "findings" not in fields


def test_the_alternate_note_key_is_handled():
    """One stored artifact uses `note`, not `notes`."""
    art = {"desk_implications": {"note": "do not add exposure"}}
    hit = find_field_directive(art)
    assert hit and hit["field"] == "desk_implications.note"


def test_missing_and_malformed_artifacts_do_not_raise():
    for bad in (None, "", [], {}, {"desk_implications": None},
                {"desk_implications": "a string"}, {"recommendation": []}):
        assert find_field_directive(bad) is None


def test_describe_names_the_field_and_the_rule():
    d = describe_field_directive(_art(notes="do not add exposure"))
    assert d["instruction_in_field"] is True
    assert d["field"] == "desk_implications.notes"
    assert d["rule"] == "directive_negation"
    assert "desk_implications.notes" in d["fields_checked"]


# ---------------------------------------------------------------- the gate

def test_a_gated_artifact_fails_closed():
    r = critique(_art(notes="do not add exposure at current levels"))
    assert r["verdict"] == "FAILED"
    assert "forbidden_authority" in r["reasons"]
    assert "instruction_in_desk_implications.notes" in r["reasons"]


def test_a_legacy_artifact_is_grandfathered():
    """Decision 1: do not retro-detach. 468 of 471 sit before the boundary."""
    r = critique(_art(notes="do not add exposure at current levels",
                      completed=LEGACY))
    assert r["verdict"] != "FAILED"
    assert "forbidden_authority" not in r["reasons"]


def test_an_undated_artifact_is_treated_as_pre_existing():
    art = _art(notes="do not add exposure")
    art.pop("completed_ts")
    assert critique(art)["verdict"] != "FAILED"


def test_the_ex_dividend_pin_survives_the_gate():
    r = critique(_art(notes="Coverage improved.",
                      summary="Note: do not sell shares before the ex-date. "
                              "As of 2026-08."))
    assert r["verdict"] != "FAILED", r["reasons"]
