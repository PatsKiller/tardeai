"""A curated alert must be more useful than the JSON, and never less true.

The alert that prompted this reached the operator with a `Fix:` section that
restated its own trigger — `error_streak:11>=5, zero_non_error_24h,
error_rate_24h:100.0>=15`. The real cause was a model pin in a proxy the message
never mentioned. These tests pin both halves: that curation adds the cause, and
that it cannot add anything the evidence does not support.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.alert_curation import (  # noqa: E402
    KNOWN_CAUSES,
    CuratedAlert,
    curate,
    deterministic_curation,
    firing_lanes,
    validate_curation,
)

# The report shape measured live on 2026-09-05, six lanes firing.
REPORT = {
    "as_of": "2026-09-05T22:37:44+00:00",
    "lanes": [
        {"lane": "deepseek", "ok": False, "firing": ["zero_non_error_24h"],
         "error_streak": 0, "non_error_24h": 0, "attempts_24h": 0},
        {"lane": "grok", "ok": True, "firing": [], "error_streak": 0,
         "non_error_24h": 3, "attempts_24h": 3},
        {"lane": "chatgpt", "ok": False,
         "firing": ["error_streak:11>=5", "zero_non_error_24h", "error_rate_24h:100.0>=15"],
         "error_streak": 11, "non_error_24h": 0, "attempts_24h": 11},
        {"lane": "drive-sync", "ok": False, "firing": ["DEGRADED_STALE_SOURCE"],
         "error_streak": None, "non_error_24h": None, "attempts_24h": None},
        {"lane": "lane-registry", "ok": False, "firing": ["ORPHANED", "SILENT"],
         "error_streak": None, "non_error_24h": None, "attempts_24h": None},
        {"lane": "search-providers", "ok": False, "firing": ["engine_pool_impaired"],
         "error_streak": None, "non_error_24h": None, "attempts_24h": None},
    ],
}


# ── it must not lose anything ────────────────────────────────────────────────

def test_no_firing_lane_is_dropped():
    """The message that prompted this showed 2 of 6. Curation may reorder and
    summarise; it may not make a fault disappear."""
    c = curate(REPORT)
    rendered = c.render()
    for row in firing_lanes(REPORT):
        assert str(row["lane"]) in rendered, f"{row['lane']} vanished from the alert"


def test_healthy_lanes_are_not_reported_as_faults():
    c = curate(REPORT)
    assert "grok" not in c.lanes


def test_the_validator_catches_a_dropped_lane():
    """Negative control for the rule above."""
    bad = CuratedAlert(headline="chatgpt is down", urgency="ACT_NOW",
                       lanes=["chatgpt"], plain_english="only chatgpt",
                       evidence=["chatgpt: 11 attempts"])
    problems = validate_curation(bad, REPORT)
    assert any("dropped firing lane" in p for p in problems)
    for lane in ("deepseek", "drive-sync", "lane-registry", "search-providers"):
        assert any(lane in p for p in problems)


# ── it must not invent ───────────────────────────────────────────────────────

def test_a_model_that_invents_a_number_is_discarded():
    """The whole risk of LLM curation in one test."""
    def liar(_prompt):
        return "The chatgpt lane has been failing for 3 weeks across 87 attempts."

    c = curate(REPORT, call_model=liar)
    assert c.curated_by == "deterministic", "invented figures were sent"
    assert "87" not in c.render()


def test_terse_model_prose_is_allowed_because_the_message_still_names_everything():
    """This test originally asserted the opposite and was wrong.

    The guarantee that matters is that the OPERATOR SEES EVERY FAULT, not that
    the summary sentence enumerates them. Evidence is deterministic and always
    lists every firing lane, and the headline carries "(+N more firing)", so
    prose reading "chatgpt is broken" does not hide anything.

    Demanding the prose name all six would reject good writing to prevent a
    problem the message does not have — and a guard that rejects everything is
    an off switch wearing a guard's name. What is asserted instead is the real
    property: whatever the model writes, the rendered message is complete.
    """
    def forgetful(_prompt):
        return "chatgpt is broken."

    c = curate(REPORT, call_model=forgetful)
    rendered = c.render()
    for row in firing_lanes(REPORT):
        assert str(row["lane"]) in rendered
    assert "more firing" in c.headline


def test_a_faithful_model_answer_is_kept():
    """The guard must not reject everything — otherwise it is just an off switch."""
    def honest(_prompt):
        return ("Six research lanes are failing. The chatgpt lane has tried "
                "repeatedly and succeeded never; deepseek, overnight-deep, "
                "drive-sync, lane-registry and search-providers are also firing.")

    rep = {"lanes": REPORT["lanes"] + [
        {"lane": "overnight-deep", "ok": False, "firing": ["zero_non_error_24h"],
         "error_streak": 0, "non_error_24h": 0, "attempts_24h": 0}]}
    c = curate(rep, call_model=honest)
    assert c.curated_by.startswith("llm"), validate_curation(c, rep)


def test_a_model_that_raises_falls_back_rather_than_failing():
    def broken(_prompt):
        raise RuntimeError("ollama is down")

    c = curate(REPORT, call_model=broken)
    assert c.curated_by == "deterministic"
    assert c.render()


def test_an_empty_model_answer_falls_back():
    c = curate(REPORT, call_model=lambda _p: "   ")
    assert c.curated_by == "deterministic"


def test_the_action_is_never_model_authored():
    """A model may rephrase the diagnosis. It may not invent the instruction."""
    def chatty(_prompt):
        return "Everything is fine, no action needed."

    c = curate(REPORT, call_model=chatty)
    assert "no action needed" not in c.action


# ── it must not state a measurement that was never taken ────────────────────

def test_a_lane_without_counters_is_not_rendered_as_zero():
    """drive-sync reports no attempt counters. Printing '0 attempts in 24h, 0
    succeeded' for it states a measurement nobody took — the same defect as
    reading an unmetered provider window as a ceiling of zero."""
    c = deterministic_curation(REPORT)
    drive = [e for e in c.evidence if e.startswith("drive-sync")][0]
    assert "0 attempts" not in drive
    assert "no call counters" in drive
    assert "DEGRADED_STALE_SOURCE" in drive


def test_a_lane_with_counters_still_shows_them():
    c = deterministic_curation(REPORT)
    chat = [e for e in c.evidence if e.startswith("chatgpt")][0]
    assert "11 attempts in 24h" in chat
    assert "0 succeeded" in chat


# ── it must be more useful than the raw JSON ────────────────────────────────

def test_a_known_cause_produces_an_action_not_a_restatement():
    c = deterministic_curation(REPORT)
    assert c.cause_known
    assert "CHATGPT_PROXY_MODEL" in c.action
    # The defining failure: the action must not merely echo the trigger.
    assert "error_streak" not in c.action
    assert "error_rate_24h" not in c.action


def test_an_undiagnosed_failure_says_so_rather_than_bluffing():
    rep = {"lanes": [{"lane": "brand-new", "ok": False, "firing": ["weird_trigger:9>=5"],
                      "error_streak": 9, "non_error_24h": 0, "attempts_24h": 9}]}
    c = deterministic_curation(rep)
    assert c.cause_known is False
    assert "Cause not diagnosed" in c.render()


def test_repeated_total_failure_is_urgent_but_an_idle_lane_is_not():
    """11 attempts and 0 successes is broken. 0 attempts is not the same thing
    and must not shout as loudly."""
    busy = {"lanes": [REPORT["lanes"][2]]}
    idle = {"lanes": [REPORT["lanes"][0]]}
    assert deterministic_curation(busy).urgency == "ACT_NOW"
    assert deterministic_curation(idle).urgency != "ACT_NOW"


def test_every_known_cause_carries_an_action_that_is_not_the_symptom():
    for kc in KNOWN_CAUSES:
        assert kc.action.strip()
        assert kc.cause.strip()
        assert "error_streak" not in kc.action


# ── the structural guard on the upstream producer ───────────────────────────

def test_fix_hint_never_returns_the_firing_reasons():
    """research_lane_health.fix_hint used to end `if firing: return firing`, so
    any lane without a hand-written branch printed its own trigger under a
    heading that promises a cause. This asserts no lane can do that again."""
    from research_lane_health import fix_hint

    for lane in ("chatgpt", "deepseek", "drive-sync", "a-lane-nobody-has-branched",
                 "another-new-one"):
        firing = ["some_trigger:9>=5", "zero_non_error_24h"]
        hint = fix_hint({"lane": lane, "firing": firing})
        assert hint != firing
        assert hint != " ".join(firing)
        assert isinstance(hint, str) and len(hint) > 40, (
            f"{lane}: hint is too short to be a cause or an instruction")


def test_an_undiagnosed_lane_hint_admits_it():
    from research_lane_health import fix_hint

    hint = fix_hint({"lane": "never-seen", "firing": ["x:1>=0"]})
    assert "CAUSE NOT DIAGNOSED" in hint
