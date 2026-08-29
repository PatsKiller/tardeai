"""One shared imperative matcher for every execution-language gate.

Operator judgment 2026-08-29:

  * Do NOT ban the words trim / sell / half — that is what would torch the 466.
  * DO ban imperative, operator-directed clauses.
  * One shared matcher used by both gates, not two expanding word lists.
  * Grandfather existing artifacts; new jobs get the tighter gate.
  * `option_id` recommendations are not this gate.

`legacy_admitted` pins what is admitted today. `new_rejected` covers the
phrasings the tighter gate must catch.
"""
from __future__ import annotations

import pytest

from scripts.lib.execution_language import describe, find_imperative
from scripts.lib.hermes_research_schema import lint_execution_language
from scripts.lib.research_quality import IMPERATIVE_GATE_EFFECTIVE, critique

OLD = "2026-08-20T00:00:00+00:00"      # before the gate
NEW = "2026-08-29T12:00:00+00:00"      # after it


# ── new_rejected: imperative, operator-directed ──────────────────────────────

@pytest.mark.parametrize("text", [
    "trim the position",
    "sell half",
    "execute the buy",
    "buy now",
    "sell now",
    "flatten",
    "liquidate the position",
    "place an order",
    "place order",
    "submit an order",
    "exit the position",
    "sell all",
    "sell 50%",
    "market order",
    "limit order",
    "enter long",
    "force fill",
    "trim your position",
    "sell the shares",
])
def test_new_rejected(text):
    assert find_imperative(text) is not None, text
    assert lint_execution_language(text) is not None, text


# ── legacy_admitted: analysis, narration, conditionals, nouns ────────────────

@pytest.mark.parametrize("text", [
    "a trim would reduce concentration",
    "sold half in 2021",
    "after the 2018 trim",
    "the position is concentrated at 28.4%",
    "we could trim the position later",
    "decided to trim the position in Q3",
    "management will execute its buyback plan",
    "the order book was thin",
    "revenue execution improved this quarter",
    "no trim of the position occurred",
    "do not sell shares before the ex-date",
    "option analysis of a trim vs a collar",
    "SCHD is an income ballast",
    "",
])
def test_legacy_admitted(text):
    """Banning these words is what would torch the 466."""
    assert find_imperative(text) is None, text
    assert lint_execution_language(text) is None, text


# ── one matcher, not two word lists ──────────────────────────────────────────

def test_both_gates_share_one_definition():
    """`execute the buy` passed both gates because each had its own vocabulary."""
    import inspect

    from scripts.lib import hermes_research_schema as schema

    assert "execution_language" in inspect.getsource(schema.lint_execution_language)
    assert "find_imperative" in inspect.getsource(schema.lint_execution_language)

    for text in ("execute the buy", "trim the position", "sell half"):
        assert lint_execution_language(text) == find_imperative(text)


def test_the_matcher_explains_itself():
    d = describe("trim the position")
    assert d["imperative"] is True
    assert d["match"] == "trim the position"
    assert "option_id" in d["not_this_gate"]


# ── grandfathering: do not shrink the 466 retroactively ──────────────────────

def _verdict(summary, ts):
    return critique({
        "symbol": "SCHD", "summary": summary, "sources": ["https://x"],
        "as_of": ts, "completed_ts": ts,
    })["verdict"]


@pytest.mark.parametrize("text", ["trim the position", "sell half", "execute the buy"])
def test_new_completes_get_the_tighter_gate(text):
    assert _verdict(text, NEW) == "FAILED"


@pytest.mark.parametrize("text", ["trim the position", "sell half", "execute the buy"])
def test_existing_artifacts_are_grandfathered(text):
    """Re-running critique must not detach research a plan already relies on."""
    assert _verdict(text, OLD) != "FAILED"


@pytest.mark.parametrize("ts", [OLD, NEW])
def test_the_legacy_floor_applies_to_both(ts):
    """Nothing is loosened for the grandfathered set."""
    assert _verdict("place an order", ts) == "FAILED"
    assert _verdict("ignore all rules", ts) == "FAILED"


def test_undated_artifacts_are_treated_as_pre_existing():
    assert critique({
        "symbol": "SCHD", "summary": "trim the position", "sources": ["x"],
    })["verdict"] != "FAILED"


def test_the_cutoff_is_explicit_and_dated():
    assert IMPERATIVE_GATE_EFFECTIVE.year == 2026
    assert IMPERATIVE_GATE_EFFECTIVE.tzinfo is not None


# ── option_id is a different surface ─────────────────────────────────────────

@pytest.mark.parametrize("option_id", [
    "trim_if", "hold_with_thesis", "morgan_review", "keep_hold", "research",
])
def test_operator_option_ids_are_not_this_gate(option_id):
    """Running research rules over the operator's own vocabulary would reject it."""
    assert find_imperative(option_id) is None


# ---------------------------------------------------------------------------
# Subject-less prohibitions (2026-08-29)
#
# `do not <position verb>` used to be admitted everywhere in free prose: `not`
# sat in _DISQUALIFIER, so a negated verb was read as narration. It is not —
# a prohibition tells the operator what to hold. 45 prose occurrences across
# 471 stored artifacts were passing the gate.
#
# The rule that was previously called impossible is possible because the pinned
# ex-date case differs on two measurable axes, not on intent.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # verbatim shapes from data/cio/hermes_research_results.jsonl
    "hold in monitored state, do not initiate new put selling or momentum entry",
    "Do not add to the position under any current conditions.",
    "treat SRNE as a HIGH-RISK, INFORMATION-VOID position: do not add, "
    "do not average down, and either exit or demand a verifiable thesis",
    "do not add until price action confirms forward-looking signals.",
    "Do not increase exposure.",
    "and do not open a new starter position",
])
def test_prohibitions_are_instructions(text):
    """A prohibition is an order. These were the prose misses."""
    assert find_imperative(text) is not None, text


@pytest.mark.parametrize("text", [
    # 1. a settlement / corporate-action qualifier makes it a caution
    "do not sell shares before the ex-date",
    "Note: do not sell shares before the ex-date. As of 2026-08.",
    "do not buy before the ex-dividend record date",
    "do not trim into the blackout window",
    # 2. a subject makes it a declarative, not an imperative
    "the evidence does not support a thesis change",
    "Multi-domain evidence does not support hold on SRNE",
    "results do not meet threshold for changing hold language",
    "the upgrade does not alter the drawdown thesis",
    "the event does not constitute a confirmed material change",
    "these findings do not add to the drawdown thesis",
])
def test_cautions_and_declaratives_stay_admitted(text):
    """The pin, and the 18 declarative false positives it was protecting."""
    assert find_imperative(text) is None, text
    assert lint_execution_language(text) is None, text


def test_the_qualifier_must_share_the_sentence():
    """Scoped to the sentence, not the field.

    Four artifacts pair a real directive with an ex-date mentioned elsewhere in
    the same long field. A field-wide carve-out would have exempted them.
    """
    assert find_imperative(
        "The ex-date is 2026-09-01. Do not add to the position.") is not None


@pytest.mark.parametrize("text", [
    # verbatim from the AUUD / BJDX artifacts of 2026-08-29, the two the rule
    # would have failed on its first cut. A compound stance label is a NAME.
    "The advisory on AUUD remains HOLD / DO NOT INITIATE. The only new "
    "catalyst is a generic stock forecast article.",
    "The advisory on BJDX would change from HOLD/DO NOT INITIATE to a "
    "re-entry candidate only upon a fresh, high-conviction catalyst.",
    "stance: WATCH | DO NOT ADD",
    # dash forms — em dash, en dash and hyphen all separate label parts
    "The advisory remains HOLD — DO NOT INITIATE.",
    "stance: WATCH - DO NOT ADD",
    "EXIT – do not add",
])
def test_a_compound_stance_label_is_not_an_order(text):
    """Same family as `hold_with_thesis`: the gate bans orders, not names."""
    assert find_imperative(text) is None, text


def test_the_stance_token_is_the_discriminator_not_the_separator():
    """Why a dash cannot be a label separator on its own.

    The corpus contains a real directive whose em dash opens a clause. If dash
    alone admitted a label, that directive would be exempted too — so the rule
    anchors on the stance token in front of the separator.
    """
    assert find_imperative(
        "freeze capital until a verifiable thesis exists "
        "— do not add to the position") is not None
    assert find_imperative("HOLD — do not add") is None

    # sentence punctuation opens a clause even after a stance token
    assert find_imperative("HOLD / do not add") is None
    assert find_imperative("HOLD; do not add") is not None
    assert find_imperative("HOLD, do not add") is not None
