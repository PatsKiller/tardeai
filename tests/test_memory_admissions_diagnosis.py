"""A lane that can never produce must not be reported as blocked.

Measured 2026-08-27: memory_admissions read STARVED at 0/91 in 72h, with the
message "Work is entering this lane and nothing is coming out."

The implication was false. Of 430 memories in the durable store, 427 are
RESEARCH_REFERENCE, which `admit_status` deliberately never promotes -- research
is context, never policy. The only ACTIVE-eligible classes are
OPERATOR_EXPLICIT_PREFERENCE, AGENT_COMMITMENT and CASE_SUMMARY, and of those
the latter two have ZERO producers anywhere in the codebase; the single ACTIVE
memory came from the manual operator CLI.

So nothing was blocked. The gap is real but different, and needs a different
action: wire a producer, rather than unblock a queue that is not blocked. A
standing false alarm is one that gets ignored -- this system has already
produced one ("Hermes starved", 2026-07-23, false).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.pipeline_liveness import (  # noqa: E402
    LIVE, NO_ELIGIBLE_INPUT, QUIET, STARVED, UNKNOWN, Lane, evaluate,
)


def _lane(probe, name="l", min_expected=1):
    return Lane(name=name, window_hours=72.0, min_expected=min_expected,
                describe="d", probe=probe)


def _status(probe):
    return evaluate([_lane(probe)]).lanes[0]["status"]


# ── the incident ───────────────────────────────────────────────────────────

def test_offers_that_could_never_be_promoted_are_not_starvation():
    """90 offered, 0 produced, 0 eligible -- the measured shape."""
    assert _status(lambda since: (0, 90, "src", 0)) == NO_ELIGIBLE_INPUT


def test_a_genuine_blockage_is_still_starved():
    """Eligible work arrived and produced nothing. This must keep alerting --
    it is the 17-day shape the module exists to catch."""
    assert _status(lambda since: (0, 90, "src", 90)) == STARVED


def test_even_one_eligible_offer_makes_silence_starvation():
    """The distinction is 'could any of it have been promoted', not a ratio."""
    assert _status(lambda since: (0, 90, "src", 1)) == STARVED


def test_no_eligible_input_is_still_a_finding():
    """It is a real gap. Silencing it would trade a false alarm for a blind
    spot, which is the opposite of the point."""
    rep = evaluate([_lane(lambda since: (0, 90, "src", 0))])
    assert [f["lane"] for f in rep.findings] == ["l"]
    assert rep.findings[0]["status"] == NO_ELIGIBLE_INPUT


# ── nothing else moves ─────────────────────────────────────────────────────

def test_three_value_probes_keep_their_meaning():
    """Every attempt counts as eligible when a probe does not say otherwise, so
    the other two lanes are untouched."""
    assert _status(lambda since: (0, 5, "src")) == STARVED
    assert _status(lambda since: (3, 5, "src")) == LIVE
    assert _status(lambda since: (0, 0, "src")) == QUIET


def test_production_still_wins_over_eligibility():
    """If output exists the lane is LIVE, whatever the eligibility count says."""
    assert _status(lambda since: (3, 5, "src", 0)) == LIVE


def test_a_broken_probe_is_still_unknown():
    def boom(since):
        raise RuntimeError("source unreadable")
    assert _status(boom) == UNKNOWN


# ── eligibility resolution ─────────────────────────────────────────────────

def test_an_unresolvable_receipt_is_not_counted_as_eligible():
    """An unknown must never manufacture the appearance of eligible input --
    that would resurrect the false STARVED."""
    from scripts.lib.pipeline_liveness import _receipt_is_promotable
    assert _receipt_is_promotable({}) is False
    assert _receipt_is_promotable({"memory_id": "does-not-exist"}) is False


def test_an_explicit_promotable_flag_is_believed():
    from scripts.lib.pipeline_liveness import _receipt_is_promotable
    assert _receipt_is_promotable({"promotable": True}) is True
    assert _receipt_is_promotable({"promotable": False}) is False


def test_memory_type_decides_when_the_flag_is_absent():
    """Receipts written before the flag existed are resolved by type."""
    from scripts.lib.pipeline_liveness import _receipt_is_promotable
    assert _receipt_is_promotable({"memory_type": "RESEARCH_REFERENCE"}) is False
    assert _receipt_is_promotable({"memory_type": "CASE_SUMMARY"}) is True
    assert _receipt_is_promotable({"memory_type": "AGENT_COMMITMENT"}) is True


# ── the receipt records what was offered ───────────────────────────────────

def _admit(tmp_path, memory_type, subject="a preference about report timing"):
    from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider
    from scripts.lib.agent_memory_admission import admit_candidate
    prov = DurableJsonlMemoryProvider(path=tmp_path / "aif_memory.jsonl")
    return admit_candidate(
        {
            "candidate_id": f"c-{memory_type}",
            "memory_type": memory_type,
            "subject": subject,
            "content": "the operator prefers the digest at 07:00",
            "source_refs": ["operator_statement:chat-2026-08-27"],
        },
        provider=prov,
        admitted_by="test",
    )


def test_a_new_receipt_says_what_kind_of_memory_it_was(tmp_path):
    """Every receipt ever written carried authority_class
    NON_AUTHORITATIVE_CONTEXT, a constant that discriminates nothing -- so the
    audit trail could not distinguish a failed promotion from a class that is
    never promoted."""
    r = _admit(tmp_path, "RESEARCH_REFERENCE")
    assert r["accepted"], r.get("reason")
    assert r["memory_type"] == "RESEARCH_REFERENCE"
    assert r["promotable"] is False, "research context is deliberately never policy"


def test_a_promotable_class_is_marked_promotable(tmp_path):
    r = _admit(tmp_path, "OPERATOR_EXPLICIT_PREFERENCE")
    assert r["accepted"], r.get("reason")
    assert r["promotable"] is True
    assert r["display_status"] == "ADMITTED", "an explicit operator preference is ACTIVE"
