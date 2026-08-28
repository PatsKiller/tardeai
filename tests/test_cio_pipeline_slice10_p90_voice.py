"""Slice 10: remaining P9.0 voice fields stamped T/D, not A.

Meaning is not rewritten. CASE_SUMMARY stays A-context.
"""
from __future__ import annotations

from scripts.lib.cio_investment_product import _summary
from scripts.lib.cio_p90_voice import (
    VOICE_A,
    VOICE_D,
    VOICE_T,
    apply_operator_voice,
    stamp_nothing_requires_action,
)


def test_nothing_requires_action_is_d_not_a():
    s = _summary(
        {"title": "RISK ON TREND — SELECTIVE RISK"},
        {"counts": {}, "names": [], "count": 0},
        {"DO_NOW": [], "WATCH_CLOSELY": []},
    )
    assert "[D] Nothing requires action today." in s
    assert "[A] Nothing requires action today." not in s
    assert "Nothing requires action today." in s
    assert "Advisory only — no orders placed." in s


def test_stamp_is_idempotent_and_preserves_words():
    once = stamp_nothing_requires_action()
    twice = stamp_nothing_requires_action(once)
    assert once == twice == "[D] Nothing requires action today."
    assert once.replace("[D] ", "") == "Nothing requires action today."


def test_operator_voice_labels_td_not_a():
    product = apply_operator_voice({
        "executive_summary": "RISK ON TREND — SELECTIVE RISK. Nothing requires action today.",
        "action_now": [{"symbol": "FAKE", "decision": "AVOID", "urgency": "NOW"}],
        "case_summaries": {
            "banner": "A-context · NON_AUTHORITATIVE · does not change action",
            "class": "A",
            "count": 1,
            "items": [{"subject": "research_case:SCHD"}],
        },
    })
    assert product["executive_summary_class"] == VOICE_T
    assert product["action_now_class"] == VOICE_D
    assert product["nothing_requires_action_class"] == VOICE_D
    assert product["executive_summary"].startswith("[T] ")
    assert "[D] Nothing requires action today." in product["executive_summary"]
    assert product["case_summaries"]["class"] == VOICE_A
    # meaning preserved
    assert "RISK ON TREND — SELECTIVE RISK." in product["executive_summary"]
    assert product["action_now"][0]["symbol"] == "FAKE"
    assert product["action_now"][0]["decision"] == "AVOID"
    # never stamped A on these fields
    assert product["executive_summary_class"] != VOICE_A
    assert product["action_now_class"] != VOICE_A
