"""M5 — a scheduled wake loads the record before it acts.

`InstrumentRecordStore.load(subject_key)` is built, correct and tested, and no
scheduled wake called it. The reason is a level deeper than "nobody wired it",
measured against the live release 2026-08-30:

    wakes in the store                       1,513
    wakes carrying a subject_key                 0
    wakes mentioning a record subject at all      1

The wake queue has no subject field. 1,395 of 1,513 are GOAL_DUE keyed on
goal_id/owner_agent. The one wake that names a record subject is an operator
message carrying it in free text: "What should I watch on SCHD this week?".
There was nothing to load BY.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.cio_wake_subject import (
    NO_RECORD, NO_SUBJECT, PROCEED, SKIP_CADENCE,
    decide, resolve_subject_key, summarise,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class _Store:
    def __init__(self, records): self._r = {r["subject_key"]: r for r in records}
    def all(self): return list(self._r.values())
    def load(self, key): return self._r.get(key)


def _wake(**kw):
    base = {"wake_job_id": "w1", "trigger_type": "GOAL_DUE", "context": {}}
    base.update(kw)
    return base


# ── resolving a subject ───────────────────────────────────────────────────

def test_an_explicit_subject_key_wins():
    k, src = resolve_subject_key(_wake(subject_key="HELD:NOC"), {"HELD:NOC"})
    assert (k, src) == ("HELD:NOC", "wake.subject_key")


def test_a_symbol_resolves_against_records_that_exist():
    k, src = resolve_subject_key(_wake(context={"symbol": "noc"}), {"HELD:NOC"})
    assert (k, src) == ("HELD:NOC", "context.symbol")


def test_operator_prose_resolves_only_against_a_real_record():
    """The live case: the subject was in free text, not a field."""
    w = _wake(trigger_type="OPERATOR_MESSAGE",
              context={"text": "What should I watch on SCHD this week?"})
    assert resolve_subject_key(w, {"HELD:SCHD"}) == ("HELD:SCHD", "context.text")
    # ...and must NOT invent a subject that has no record.
    assert resolve_subject_key(w, {"HELD:NOC"})[0] is None


def test_a_goal_wake_resolves_to_no_subject_and_that_is_not_a_failure():
    w = _wake(context={"goal_id": "goal_abc", "owner_agent": "morgan"})
    assert resolve_subject_key(w, {"HELD:NOC"})[0] is None
    d = decide(w, store=_Store([]), now=NOW, known_keys={"HELD:NOC"})
    assert d["verdict"] == NO_SUBJECT
    assert d["subject_resolved"] is False


# ── the record changes the decision ───────────────────────────────────────

def test_a_deferred_subject_is_skipped_before_anything_is_claimed():
    """The M5 shape: a disposition recorded earlier changes what happens now."""
    rec = {"subject_key": "HELD:SCHD",
           "next_eligible_at": (NOW + timedelta(hours=16)).isoformat(),
           "next_research_question": "what independent evidence would settle this?"}
    w = _wake(trigger_type="OPERATOR_MESSAGE",
              context={"text": "What should I watch on SCHD this week?"})
    d = decide(w, store=_Store([rec]), now=NOW, known_keys={"HELD:SCHD"})

    assert d["without_record"] == PROCEED, "without the record the wake proceeds"
    assert d["verdict"] == SKIP_CADENCE, "with the record it does not"
    assert d["record_used"] is True
    assert "defers research until" in d["reason"]


def test_an_elapsed_deferral_proceeds_again():
    rec = {"subject_key": "HELD:SCHD",
           "next_eligible_at": (NOW - timedelta(hours=1)).isoformat()}
    d = decide(_wake(subject_key="HELD:SCHD"), store=_Store([rec]), now=NOW,
               known_keys={"HELD:SCHD"})
    assert d["verdict"] == PROCEED
    assert d["record_used"] is True, "the record was still consulted"


def test_a_subject_with_no_record_proceeds_and_says_so():
    d = decide(_wake(subject_key="HELD:XYZ"), store=_Store([]), now=NOW,
               known_keys={"HELD:XYZ"})
    assert d["verdict"] == NO_RECORD
    assert d["record_found"] is False


def test_an_unreadable_store_proceeds_rather_than_stalling_the_cycle():
    class Broken:
        def all(self): raise RuntimeError("disk gone")
        def load(self, k): raise RuntimeError("disk gone")
    d = decide(_wake(), store=Broken(), now=NOW)
    assert d["verdict"] == PROCEED
    assert "unreadable" in str(d["reason"])
    assert d["record_used"] is False, "must not claim it used a record it could not read"


# ── the metric must not overstate itself ──────────────────────────────────

def test_only_a_changed_OUTCOME_counts_as_changed_by_the_record():
    """First run of this report claimed 1,515 decisions changed when the true
    number was 1: `proceed/no_subject` differs from `proceed` as a STRING while
    the wake still proceeds. A metric that overstates its own effect is worse
    than no metric."""
    decisions = [
        {"verdict": NO_SUBJECT, "without_record": PROCEED},
        {"verdict": NO_RECORD, "without_record": PROCEED},
        {"verdict": PROCEED, "without_record": PROCEED},
        {"verdict": SKIP_CADENCE, "without_record": PROCEED,
         "wake_job_id": "w", "subject_key": "HELD:SCHD", "reason": "deferred"},
    ]
    s = summarise(decisions)
    assert s["decisions_changed_by_record"] == 1
    assert s["skipped_cadence_not_due"] == 1
    assert s["no_subject"] == 1 and s["no_record"] == 1
    assert len(s["changed"]) == 1


# ── the dispatcher consults it before claiming ────────────────────────────

def test_the_dispatcher_consults_the_record_before_it_claims_a_wake():
    """Ordering is the whole point: a deferred subject must cost no lease and
    create no run."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_wake_dispatcher.py").read_text(encoding="utf-8")
    consult = src.index("M5: load the record before acting")
    claim = src.index("# ── Claim with lease ─")
    assert consult < claim, "the record must be read before the wake is claimed"


def test_the_dispatcher_reports_what_the_record_changed_every_cycle():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_wake_dispatcher.py").read_text(encoding="utf-8")
    assert '"record_consult": _summarise_subject(subject_decisions)' in src


def test_the_record_consult_failure_path_is_never_a_bare_except():
    from pathlib import Path
    for f in ("scripts/lib/cio_wake_dispatcher.py", "scripts/lib/cio_wake_subject.py"):
        src = (Path(__file__).resolve().parent.parent / f).read_text(encoding="utf-8")
        assert "except:" not in src.replace("except:  # noqa", ""), f
