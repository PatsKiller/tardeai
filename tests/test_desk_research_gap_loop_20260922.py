"""The desk does not stop at "nothing on file": it says wait, goes and finds out,
answers truthfully, and records the outcome so the same question is never empty twice.

Operator, 2026-09-22, verbatim: "the proper thing to do is say wait while i
research, reach it and give truthfull answer and add to memoery".

WHAT PRODUCED THIS. The transcript:

    Operator: "how is S for entry on cyber give me CIO opinion"
    Desk:     "...Research on file: none about S. CIO opinion: I can't give one
               -- no research, no levels, and it's not on the re-entry desk.
               Next: say 'research S' to queue a fresh review."

The honesty is correct. Stopping there is the defect: the operator had to issue
a second command to start work the desk had already decided was needed.

Measured in `data/cio/cio_operator_gap_requests.jsonl` at 2026-09-22T17:03:00Z
(chat 8797974247): the one gap that reached the registry was
`{"domain": "analyst_view", "symbol": "S", "gap_type": "missing_analyst_coverage"}`
with `"registered": 0, "not_registered": 1`. Re-running that question's evidence
gather offline gives `blocking_gaps == []` and `complete == True`, so the gap
resolver -- gated on `if blocking:` -- never ran at all.

These tests pin, each with a real negative control that goes red when the wiring
is reverted:

* an empty-subject gap is RAISED and the reply says WAIT, not "say 'research X'"
* "still nothing found" is said plainly and never dressed up as a result
* the second identical question is answered from the record, not re-searched
* only FREE vectors may run inline, and the slow producer is excluded
* a gap type with no resolver action is never claimed as queued

Offline: the resolver, the registry write and the answer ledger are all
replaced. No database, no provider, no network, no host path.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402
import scripts.lib.gap_resolver as gr  # noqa: E402

COVERS = ["scripts/lib/cio_operator_desk_loop.py"]

INTENT = {"intent": "analyst_view", "symbols": ["S"], "needs": ["analyst_view"],
          "text": "how is S for entry on cyber give me CIO opinion"}

# The two gaps the live desk actually produces for that question.
ANALYST_GAP = {"domain": "analyst_view", "symbol": "S", "field": "analyst_view",
               "reason": "no analyst coverage on file for S",
               "gap_type": "missing_analyst_coverage"}
RESEARCH_GAP = {"domain": "hermes_research", "symbol": "S", "field": "research",
                "reason": "no promoted research for S", "gap_type": "missing_research"}
# A partial-levels gap, which the loop must NOT take over.
LEVEL_GAP = {"domain": "reentry_decision_desk", "symbol": "SCHG", "field": "levels",
             "reason": "partial levels", "gap_type": "soft"}


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    """The answer ledger, redirected off the repo tree."""
    p = tmp_path / "cio_operator_gap_answers.jsonl"
    monkeypatch.setattr(desk, "GAP_ANSWERS_PATH", p)
    return p


@pytest.fixture()
def raised(monkeypatch):
    """Capture the registry raise without touching a database."""
    calls: list[list[dict]] = []

    def fake_register(gaps, *, chat_id, pending_id):
        calls.append(list(gaps))
        return {"registered": 1, "gap_ids": [4242], "not_registered": 1}

    monkeypatch.setattr(desk, "_register_gaps", fake_register)
    return calls


def _resolution(**kw) -> gr.Resolution:
    """A real Resolution, so the test pins the resolver's own field names."""
    return gr.Resolution(**kw)


def _fake_resolve(monkeypatch, result, counter: list | None = None):
    def fake(gap, *, chain=None, ctx=None, **_):
        if counter is not None:
            counter.append((gap.domain, gap.subject))
        out = result(gap) if callable(result) else result
        out.domain = out.domain or gap.domain
        out.subject = out.subject or gap.subject
        return out

    monkeypatch.setattr(gr, "resolve", fake)


def _rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── 1. raise + say wait ──────────────────────────────────────────────────────


def test_empty_subject_gap_is_raised_and_the_reply_says_wait(monkeypatch, ledger, raised):
    _fake_resolve(monkeypatch, _resolution(
        outcome="queued", vector="operator_ask", eta_seconds=1800,
        attempts=[{"vector": "backup_provider", "outcome": "no_answer"},
                  {"vector": "operator_ask", "outcome": "queued"}],
    ))
    summary = desk._close_subject_gap_loop(
        [ANALYST_GAP, RESEARCH_GAP, LEVEL_GAP],
        intent=INTENT, text=INTENT["text"], chat_id="8797974247", pending_id="opr_test",
    )

    # The level gap is not this loop's business; the two empty-subject gaps are.
    assert summary["considered"] == 2
    assert len(summary["queued"]) == 2

    # RAISED -- through the desk's one registry entry point, with both gaps.
    assert raised, "the gap was never raised into the registry"
    assert {g["gap_type"] for g in raised[0]} == {"missing_analyst_coverage", "missing_research"}

    note = desk._gap_loop_note(summary)
    assert "wait" in note.lower()
    assert "researching this now" in note
    # The defect being fixed: the reply must not send the operator back to do it.
    assert "say 'research" not in note

    # PERSISTED -- one row per gap, so the next asking can read it.
    assert len(_rows(ledger)) == 2


def test_negative_control_wiring_off_restores_the_old_dead_end(monkeypatch, ledger, raised):
    """Revert the wiring: nothing is raised, nothing runs, nothing is recorded.

    Without this control the test above would pass on a loop that ran
    unconditionally, proving nothing about the switch that gates it.
    """
    monkeypatch.setenv("CIO_OPERATOR_GAP_LOOP", "0")
    _fake_resolve(monkeypatch, _resolution(outcome="queued", vector="operator_ask", eta_seconds=1800))

    summary = desk._close_subject_gap_loop(
        [ANALYST_GAP, RESEARCH_GAP],
        intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p",
    )
    assert summary["queued"] == []
    assert not raised, "nothing may be raised when the loop is off"
    assert desk._gap_loop_note(summary) == ""
    assert not ledger.exists() or _rows(ledger) == []


# ── 2. "still nothing found" is a truthful outcome ───────────────────────────


def test_still_nothing_found_is_said_and_never_dressed_up(monkeypatch, ledger, raised):
    _fake_resolve(monkeypatch, _resolution(
        outcome="no_coverage",
        attempts=[{"vector": "backup_provider", "outcome": "no_answer"}],
    ))
    summary = desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p",
    )
    assert len(summary["still_nothing"]) == 1
    assert summary["answered"] == []

    note = desk._gap_loop_note(summary)
    assert "still found nothing" in note
    assert "backup_provider=no_answer" in note   # says WHAT was tried
    assert "found it" not in note                # never claims a result


def test_negative_control_an_answer_is_reported_as_an_answer(monkeypatch, ledger, raised):
    """The same assertions must discriminate: an answered gap reads differently.

    A "still nothing" assertion that also passes on a real answer would be
    measuring nothing.
    """
    _fake_resolve(monkeypatch, _resolution(
        outcome="answered", answered=True, vector="backup_provider",
        source="backup_provider:yfinance_on_demand", as_of="2026-09-22T18:00:00+00:00",
        answer={"symbol": "S", "target_mean": 31.4},
        attempts=[{"vector": "backup_provider", "outcome": "answered"}],
    ))
    summary = desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p",
    )
    assert len(summary["answered"]) == 1
    assert summary["still_nothing"] == []

    note = desk._gap_loop_note(summary)
    assert "went and found it" in note
    assert "still found nothing" not in note


# ── 3. the same question is never empty twice ────────────────────────────────


def test_the_same_question_is_answered_from_the_record(monkeypatch, ledger, raised):
    """Second asking reads the first asking's outcome instead of re-searching."""
    calls: list = []
    _fake_resolve(monkeypatch, _resolution(
        outcome="no_coverage", attempts=[{"vector": "backup_provider", "outcome": "no_answer"}],
    ), counter=calls)

    first = desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p1")
    assert len(calls) == 1 and len(first["still_nothing"]) == 1

    second = desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p2")
    assert len(calls) == 1, "the second asking re-ran the search instead of reading the record"
    assert len(second["recalled"]) == 1
    assert second["still_nothing"] == []

    note = desk._gap_loop_note(second)
    assert "already went looking" in note


def test_a_recalled_queued_gap_says_it_is_still_running(monkeypatch, ledger, raised):
    """Recall must not flatten "research is running" into "found nothing".

    Caught on a live demo of the real S question: the first asking queued work,
    and the second asking reported "I already went looking and found nothing".
    That is false twice -- nothing was concluded, and it tells the operator the
    work has finished when it is still running.
    """
    _fake_resolve(monkeypatch, _resolution(
        outcome="queued", vector="operator_ask", eta_seconds=7200,
        attempts=[{"vector": "operator_ask", "outcome": "queued"}],
    ))
    desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p1")

    def _explode(*a, **k):
        raise AssertionError("the resolver re-ran instead of reading the record")

    monkeypatch.setattr(gr, "resolve", _explode)
    second = desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p2")

    note = desk._gap_loop_note(second)
    assert "still running" in note
    assert "found nothing" not in note


def test_negative_control_an_aged_out_record_is_searched_again(monkeypatch, ledger, raised):
    """A stale "nothing found" must not harden into a permanent answer.

    Without this control, recall could silently become "never look again".
    """
    calls: list = []
    _fake_resolve(monkeypatch, _resolution(
        outcome="no_coverage", attempts=[{"vector": "backup_provider", "outcome": "no_answer"}],
    ), counter=calls)

    stale = datetime.now(timezone.utc) - timedelta(hours=desk.GAP_ANSWER_TTL_HOURS + 1)
    ledger.write_text(json.dumps({
        "ts": stale.isoformat(), "symbol": "S", "domain": "analyst_view",
        "outcome": "no_coverage", "tried": ["backup_provider=no_answer"],
    }) + "\n", encoding="utf-8")

    summary = desk._close_subject_gap_loop(
        [ANALYST_GAP], intent=INTENT, text=INTENT["text"], chat_id="c", pending_id="p")
    assert len(calls) == 1, "an aged-out record must be searched again"
    assert summary["recalled"] == []


# ── 4. only free vectors run while the operator waits ────────────────────────


def test_inline_chain_is_free_vectors_only(monkeypatch):
    """Spending on this path is an operator decision (AGENTS §17), so it cannot happen."""
    chain = desk._desk_inline_chain("analyst_opinion")
    vectors = [c["vector"] for c in chain]

    # Positive control: the filter is not simply returning nothing.
    assert "backup_provider" in vectors, "the on-demand vector must survive the filter"
    assert all(c["cost_class"] == "free" for c in chain)
    assert "governed_search" not in vectors   # metered
    assert "llm_curation" not in vectors      # metered
    # Excluded on runtime, not cost: its writer fetches a whole universe.
    assert "refresh_producer" not in vectors


def test_negative_control_the_free_rail_holds_even_if_the_vector_list_widens(monkeypatch):
    """Widening DESK_INLINE_VECTORS must not be enough to admit a metered vector.

    Two independent rails guard this path; this proves the cost rail works on
    its own, so a later edit to the vector list cannot quietly start spending.
    """
    monkeypatch.setattr(
        desk, "DESK_INLINE_VECTORS",
        ("backup_provider", "operator_ask", "governed_search", "llm_curation"),
    )
    vectors = [c["vector"] for c in desk._desk_inline_chain("analyst_opinion")]
    assert "governed_search" not in vectors
    assert "llm_curation" not in vectors
    assert "backup_provider" in vectors


# ── 5. never claim a refresh nothing will perform ────────────────────────────


def test_a_gap_type_with_no_resolver_action_is_not_claimed_as_queued():
    """The registry only admits a gap type the resolver has an action for.

    `missing_research` maps to `stale_news`, which dispatches a real research
    job. `missing_analyst_coverage` maps to nothing: no action in
    data_gap_resolver.GAP_RESOLVERS fetches analyst coverage, so mapping it
    would make the reply promise a refresh nothing performs. It is pursued
    through the declared on_gap chain instead.
    """
    assert desk._registry_gap_type(RESEARCH_GAP) == "stale_news"
    assert desk._registry_gap_type(ANALYST_GAP) is None

    from lib.writers.data_gap_registry_writer import GAP_TYPES
    assert "stale_news" in GAP_TYPES
    assert "missing_analyst_coverage" not in GAP_TYPES
