"""Slice D — the daily research budget, and the librarian's shelf life.

The gate (Slice C) answers "what should run for THIS subject". Asked forty
times it answers forty times, which is how one cash question became 36 paid
jobs. This file pins the layer above it: which few subjects get a decision at
all today, and it pins the two properties the operator named by hand —

    36 S5 cash plans still collapse to ONE SLEEVE:CASH record
    a stale grade-B fact cannot corpus_hit

— plus the cap, the one-decision-per-subject-per-day collapse law, the
preference for movement over the calendar, and an empty book.
"""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cio_instrument_record import (
    CASH_SLEEVE, content_hash, new_record,
)
from scripts.lib.cio_research_budget import (
    DAILY_CAP, EVENT_HASHES, RANK_DUE, RANK_EVENT, RANK_NEVER, BudgetLedger,
    collapse_plans_to_subjects, day_of, eligibility, ledger_path, select,
    subject_key_for_plan,
)
from scripts.lib.cio_research_gate import decide
from scripts.lib import cio_research_librarian as librarian

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def held(sym, *, next_at=None, updated="2026-01-01T00:00:00+00:00", **kw):
    rec = new_record("HELD", sym, symbols=[sym], **kw)
    rec["next_eligible_at"] = next_at
    rec["updated_ts"] = updated
    return rec


def moved(rec, observable="weight"):
    """Give the record a PRIOR hash so a different observation is a change.

    An unset hash is deliberately not a change (first contact has no belief to
    contradict), so a test that forgets this silently tests nothing.
    """
    rec["hashes"] = dict(rec.get("hashes") or {})
    rec["hashes"][observable] = content_hash("old")
    return rec


# ── the operator's test 1: the cash question stays one question ───────────

def _s5(n):
    return [{"plan_id": f"plan_s5_{i:04d}", "situation_type": "S5_CASH_DEPLOYMENT",
             "symbols": [], "status": "draft"} for i in range(n)]


def test_36_s5_cash_plans_collapse_to_one_sleeve_cash_subject():
    """The budget must not re-explode the cash question into per-plan jobs."""
    subjects = collapse_plans_to_subjects(_s5(36))
    assert list(subjects) == [CASH_SLEEVE]
    assert len(subjects[CASH_SLEEVE]) == 36          # all 36 carried, as evidence


def test_36_s5_cash_plans_spend_exactly_one_budget_slot():
    """Not just one subject — one SLOT. The whole point of the budget."""
    sel = select([new_record("SLEEVE", "CASH")], now=NOW,
                 plan_subjects=collapse_plans_to_subjects(_s5(36)))
    cash = [r for r in sel["selected"] if r["subject_key"] == CASH_SLEEVE]
    assert len(cash) == 1
    assert len(cash[0]["plan_ids"]) == 36
    assert sel["selected_count"] == 1


def test_s5_collapse_survives_the_ledger_a_second_run_same_day():
    """A second run of the day re-asks nothing — the collapse law is per DAY."""
    recs = [new_record("SLEEVE", "CASH")]
    first = select(recs, now=NOW)
    assert first["selected_count"] == 1
    second = select(recs, now=NOW,
                    already_decided={r["subject_key"] for r in first["selected"]})
    assert second["selected_count"] == 0
    assert second["deferred_by_reason"]["already_decided_today"] == 1


def test_s5_plans_have_no_symbols_and_still_map_to_the_sleeve():
    """S5 is portfolio-level: `symbols` is always []. Cash is never a ticker."""
    assert subject_key_for_plan(
        {"plan_id": "p", "situation_type": "S5_CASH_DEPLOYMENT", "symbols": []}
    ) == CASH_SLEEVE


def test_a_cash_ticker_plan_is_refused_not_turned_into_a_holding():
    """CASH-as-a-ticker must never become HELD:CASH."""
    assert subject_key_for_plan(
        {"plan_id": "p", "situation_type": "S1_POSITION_LIFECYCLE",
         "symbols": ["CASH"]}) is None


# ── the operator's test 2: a stale grade-B fact cannot corpus_hit ─────────

def _corpus(closes=True, **ref):
    base = {"source_id": "sta_b", "evidence_grade": "B"}
    base.update(ref)
    return {"closes": closes, "reason": "corpus_fact_reproduced",
            "source_refs": [base], "max_influence_pct": 10.0}


def test_a_stale_grade_b_fact_cannot_corpus_hit():
    """Grade B keeps for 90 days. A 200-day-old B is not an answer about today."""
    stale = (NOW - timedelta(days=200)).isoformat()
    r = decide({"material": True, "kind": "held_core_thesis",
                "corpus": _corpus(last_seen=stale)}, now=NOW)
    assert r["decision"] != "corpus_hit"
    assert r["decision"] == "flash"          # falls through to the normal ladder


def test_a_fresh_grade_b_fact_still_corpus_hits():
    """The mirror. Without this, the test above passes on a broken librarian."""
    fresh = (NOW - timedelta(days=10)).isoformat()
    r = decide({"material": True, "kind": "held_core_thesis",
                "corpus": _corpus(last_seen=fresh)}, now=NOW)
    assert r["decision"] == "corpus_hit"


def test_grade_a_outlives_grade_b_at_the_same_age():
    """Shelf life follows the grade's own meaning: A 365d, B 90d."""
    age = (NOW - timedelta(days=200)).isoformat()
    a = decide({"material": True, "kind": "held_core_thesis",
                "corpus": _corpus(evidence_grade="A", last_seen=age)}, now=NOW)
    b = decide({"material": True, "kind": "held_core_thesis",
                "corpus": _corpus(evidence_grade="B", last_seen=age)}, now=NOW)
    assert a["decision"] == "corpus_hit"
    assert b["decision"] != "corpus_hit"


def test_an_ungraded_source_gets_no_opinion_and_behaves_as_before():
    """The librarian may not make the corpus quieter than it found it."""
    r = decide({"material": True, "kind": "held_core_thesis",
                "corpus": {"closes": True, "reason": "corpus_fact_reproduced",
                           "source_refs": [{"source_id": "sta_x"}]}}, now=NOW)
    assert r["decision"] == "corpus_hit"


def test_one_stale_source_is_dropped_but_a_fresh_sibling_still_closes():
    """Drop the stale SOURCE, not the whole verdict."""
    corpus = {"closes": True, "reason": "corpus_fact_reproduced", "source_refs": [
        {"source_id": "old", "evidence_grade": "B",
         "last_seen": (NOW - timedelta(days=200)).isoformat()},
        {"source_id": "new", "evidence_grade": "B",
         "last_seen": (NOW - timedelta(days=5)).isoformat()},
    ]}
    out = librarian.filter_corpus(corpus, now=NOW)
    assert out["closes"] is True
    assert [r["source_id"] for r in out["source_refs"]] == ["new"]
    assert out["librarian_dropped"][0]["source_id"] == "old"


def test_an_invalidated_grade_x_source_never_closes():
    detail = librarian.staleness({"source_id": "s", "evidence_grade": "X"}, now=NOW)
    assert detail["stale"] is True and detail["reason"] == "grade_x_invalidated"


def test_a_discovery_candidate_cannot_close_until_an_operator_grades_it():
    """The other half of cio_source_discovery's no-ingest contract."""
    candidate = {"source_id": "sta_new", "status": "CANDIDATE",
                 "evidence_grade": None, "is_fact": False}
    assert librarian.candidate_may_close(candidate) is False
    out = librarian.filter_corpus(
        {"closes": True, "source_refs": [candidate]}, now=NOW)
    assert out["closes"] is False
    assert out["reason"] == "librarian_all_closing_sources_stale"


def test_stale_after_days_defaults_come_from_the_grade():
    assert librarian.stale_after_days_for("A") == 365
    assert librarian.stale_after_days_for("B") == 90
    assert librarian.stale_after_days_for("") is None          # no opinion
    assert librarian.stale_after_days_for("B", override=7) == 7


def test_the_librarian_fails_open_when_its_store_is_unreadable(monkeypatch):
    """A staleness gate that fails CLOSED would route every hit to a paid call."""
    def boom(*a, **kw):
        raise OSError("index unreadable")
    monkeypatch.setattr(librarian, "filter_corpus", boom)
    r = decide({"material": True, "kind": "held_core_thesis",
                "corpus": _corpus(last_seen=(NOW - timedelta(days=200)).isoformat())},
               now=NOW)
    assert r["decision"] == "corpus_hit"       # unchanged, not escalated


def test_grade_and_shelf_life_persist_onto_the_freshness_row(tmp_path):
    """The grade lands on research_source_index, not in a second store."""
    idx = tmp_path / "research_source_index.json"
    librarian.set_grade("sta_b", "B", path=idx, now=NOW)
    meta = librarian.source_meta("sta_b", path=idx)
    assert meta["grade"] == "B" and meta["stale_after_days"] == 90
    assert meta["present"] is True


def test_grading_a_source_does_not_reset_its_research_ttl(tmp_path):
    """Grading is not researching. Resetting fresh_until would hide staleness."""
    from scripts.lib import research_source_index as rsi
    idx = tmp_path / "research_source_index.json"
    rsi.upsert_row("sta_b", content_hash="abc", path=idx, freshness_days=30,
                   now=NOW)
    before = rsi.get_row("sta_b", path=idx)
    librarian.set_grade("sta_b", "B", path=idx, now=NOW + timedelta(days=5))
    after = rsi.get_row("sta_b", path=idx)
    assert after["fresh_until"] == before["fresh_until"]
    assert after["content_hash"] == "abc"
    assert after["extra"]["grade"] == "B"


# ── the cap holds ─────────────────────────────────────────────────────────

def test_the_daily_cap_holds_against_a_book_that_wants_everything():
    recs = [held(f"S{i:02d}") for i in range(40)] + [new_record("SLEEVE", "CASH")]
    sel = select(recs, now=NOW)
    assert sel["selected_count"] <= DAILY_CAP
    assert sel["cap"] == DAILY_CAP == 5


def test_the_slot_shape_is_three_held_plus_cash():
    recs = [held(f"S{i:02d}") for i in range(40)] + [new_record("SLEEVE", "CASH")]
    sel = select(recs, now=NOW)
    slots = [r["slot"] for r in sel["selected"]]
    assert slots.count("held") == 3
    assert slots.count("cash") == 1
    # No re-entry NEAR and no watch READY in this book, so the fifth slot is
    # legitimately empty — an unfilled slot is not a spare held slot.
    assert sel["selected_count"] == 4


def test_held_slots_never_overflow_into_the_cash_slot():
    """20 held names may not eat the sleeve's slot."""
    sel = select([held(f"S{i:02d}") for i in range(20)], now=NOW)
    assert [r["slot"] for r in sel["selected"]] == ["held"] * 3
    assert sel["selected_count"] == 3


def test_a_lowered_cap_binds_before_the_slot_shape():
    recs = [held(f"S{i:02d}") for i in range(10)] + [new_record("SLEEVE", "CASH")]
    sel = select(recs, now=NOW, cap=2)
    assert sel["selected_count"] == 2


# ── one decision per subject per day ──────────────────────────────────────

def test_one_decision_per_subject_per_day():
    recs = [held("AAA"), held("BBB")]
    sel = select(recs, now=NOW, already_decided={"HELD:AAA"})
    picked = {r["subject_key"] for r in sel["selected"]}
    assert "HELD:AAA" not in picked and "HELD:BBB" in picked


def test_a_subject_is_never_selected_twice_within_one_run():
    """SLEEVE:CASH filling the cash slot cannot also fill the fifth."""
    sel = select([new_record("SLEEVE", "CASH")], now=NOW,
                 statuses={CASH_SLEEVE: "NEAR"})
    keys = [r["subject_key"] for r in sel["selected"]]
    assert keys.count(CASH_SLEEVE) == 1


def test_the_ledger_round_trips_the_days_choice(tmp_path):
    led = BudgetLedger(tmp_path / "ledger.jsonl")
    assert led.decided_on(day_of(NOW)) == set()
    sel = select([held("AAA"), new_record("SLEEVE", "CASH")], now=NOW,
                 run_id="run_1")
    assert led.record(sel) == 2
    assert led.decided_on(day_of(NOW)) == {"HELD:AAA", CASH_SLEEVE}


def test_the_ledger_refuses_to_double_write_the_same_subject_same_day(tmp_path):
    led = BudgetLedger(tmp_path / "ledger.jsonl")
    sel = select([held("AAA")], now=NOW)
    assert led.record(sel) == 1
    assert led.record(sel) == 0                  # idempotent, not appended twice
    assert len(led.rows()) == 1


def test_yesterdays_ledger_does_not_block_today():
    """The collapse law is scoped to a calendar day, not forever."""
    led_day = day_of(NOW - timedelta(days=1))
    assert led_day != day_of(NOW)


def test_the_ledger_path_does_not_follow_the_cwd(tmp_path, monkeypatch):
    """Several CIO stores follow the CWD; the spend ledger must not."""
    monkeypatch.chdir(tmp_path)
    assert ledger_path().is_absolute()
    assert ledger_path(tmp_path) == tmp_path / "data" / "cio" / \
        "cio_research_budget_ledger.jsonl"


# ── preference: movement outranks the calendar ────────────────────────────

# The names below are chosen so BOTH tie-breaks (updated_ts, then subject_key)
# point at the WRONG answer. The first version of these two tests named the
# expected winner "CHANGED"/"DUE" against a loser "DUE"/"NEVER" — alphabetical
# order alone produced the expected result, and a mutant that ignored rank
# entirely still passed both. A preference test whose subject sorts first
# anyway is not testing the preference.

def test_a_hash_changed_subject_is_preferred_over_a_merely_due_one():
    due = held("AAA", next_at=(NOW - timedelta(days=1)).isoformat(),
               updated="2026-01-01T00:00:00+00:00")
    changed = moved(held("ZZZ", next_at=(NOW - timedelta(days=1)).isoformat(),
                         updated="2026-08-28T00:00:00+00:00"))
    sel = select([due, changed], now=NOW,
                 observed={"HELD:ZZZ": {"weight": "new"}},
                 cap=1, held_slots=1)
    assert [r["subject_key"] for r in sel["selected"]] == ["HELD:ZZZ"]
    assert sel["selected"][0]["reason"] == "hash_changed:weight"


def test_a_due_subject_is_preferred_over_one_never_scheduled():
    never = held("AAA", updated="2026-01-01T00:00:00+00:00")
    due = held("ZZZ", next_at=(NOW - timedelta(days=1)).isoformat(),
               updated="2026-08-28T00:00:00+00:00")
    sel = select([never, due], now=NOW, cap=1, held_slots=1)
    assert [r["subject_key"] for r in sel["selected"]] == ["HELD:ZZZ"]


def test_the_three_ranks_are_ordered_event_then_due_then_never():
    assert RANK_EVENT < RANK_DUE < RANK_NEVER


def test_a_first_contact_hash_is_not_a_change():
    """An UNSET prior hash means no belief to contradict — Slice A's law."""
    rec = held("FRESH")                       # hashes all None
    v = eligibility(rec, now=NOW, observed={"weight": "anything"})
    assert v["rank"] == RANK_NEVER


def test_only_weight_and_earnings_movement_overrides_the_calendar():
    """A price tick is not a thesis event; it must not jump the queue."""
    assert EVENT_HASHES == ("weight", "earnings")
    rec = moved(held("P", next_at=(NOW + timedelta(days=5)).isoformat()), "price")
    v = eligibility(rec, now=NOW, observed={"price": "new"})
    assert v["eligible"] is False and v["reason"] == "not_due"


def test_the_tie_break_rotates_rather_than_picking_the_same_names_forever():
    """Least-recently-touched first, so today's picks sort last tomorrow."""
    recs = [held("AAA", updated="2026-08-28T00:00:00+00:00"),
            held("BBB", updated="2026-01-01T00:00:00+00:00"),
            held("CCC", updated="2026-06-01T00:00:00+00:00")]
    sel = select(recs, now=NOW, cap=1, held_slots=1)
    assert sel["selected"][0]["subject_key"] == "HELD:BBB"   # oldest, not "AAA"


# ── a defer is not overridable by a quiet day ─────────────────────────────

def test_a_deferred_subject_is_ineligible_not_merely_low_ranked():
    """Slice B remembers the operator said wait. The budget may not undo it."""
    rec = held("SCHD", next_at=(NOW + timedelta(days=8)).isoformat())
    sel = select([rec], now=NOW)
    assert sel["selected_count"] == 0
    assert sel["deferred_by_reason"] == {"not_due": 1}


def test_a_moved_observable_does_override_a_defer():
    """Rule 3 from Slice B: the thing the last answer was about has changed."""
    rec = moved(held("SCHD", next_at=(NOW + timedelta(days=8)).isoformat()))
    sel = select([rec], now=NOW, observed={"HELD:SCHD": {"weight": "new"}})
    assert [r["subject_key"] for r in sel["selected"]] == ["HELD:SCHD"]


def test_a_research_blocked_record_does_not_get_a_slot():
    rec = held("BAD")
    rec["research_blocked"] = True
    sel = select([rec], now=NOW)
    assert sel["selected_count"] == 0
    assert sel["deferred_by_reason"] == {"research_blocked": 1}


# ── dust, TEST and cash-as-a-ticker are never selected ────────────────────

def test_dust_test_and_cash_tickers_are_refused_not_ranked():
    recs = [held("TEST"), held("DUMMY"), held("REAL")]
    sel = select(recs, now=NOW, market_values={"HELD:REAL": 10_000.0})
    assert {r["subject_key"] for r in sel["selected"]} == {"HELD:REAL"}
    assert sel["refused_count"] == 2


def test_a_dust_position_is_refused_on_market_value():
    sel = select([held("DUST")], now=NOW, market_values={"HELD:DUST": 12.50})
    assert sel["selected_count"] == 0
    assert sel["refused_by_reason"] == {"refused:dust_residual": 1}


def test_cash_as_a_ticker_can_never_reach_the_cash_slot():
    """SLEEVE:CASH is the cash question; HELD:CASH is a leak."""
    rec = new_record("HELD", "CASH")
    rec["subject_key"] = "HELD:CASH"
    sel = select([rec], now=NOW)
    assert sel["selected_count"] == 0
    assert sel["refused_by_reason"] == {"refused:cash_or_test_ticker": 1}


# ── the fifth slot: re-entry NEAR, ELSE watch READY ───────────────────────

def test_the_fifth_slot_takes_a_reentry_near():
    recs = [new_record("EXIT", "AXTI")]
    sel = select(recs, now=NOW, statuses={"EXIT:AXTI": "NEAR"})
    assert [(r["slot"], r["subject_key"]) for r in sel["selected"]] == [
        ("reentry_or_watch", "EXIT:AXTI")]


def test_a_reentry_near_beats_a_watch_ready_when_both_exist():
    """'else', not a merge — the slot is spent on the re-entry."""
    recs = [new_record("EXIT", "AXTI"), new_record("WATCH", "NVDA")]
    sel = select(recs, now=NOW,
                 statuses={"EXIT:AXTI": "NEAR", "WATCH:NVDA": "READY"})
    picked = [r for r in sel["selected"] if r["slot"] == "reentry_or_watch"]
    assert [r["subject_key"] for r in picked] == ["EXIT:AXTI"]


def test_a_watch_ready_fills_the_slot_when_no_reentry_is_near():
    recs = [new_record("EXIT", "AXTI"), new_record("WATCH", "NVDA")]
    sel = select(recs, now=NOW,
                 statuses={"EXIT:AXTI": "WAIT", "WATCH:NVDA": "READY"})
    picked = [r for r in sel["selected"] if r["slot"] == "reentry_or_watch"]
    assert [r["subject_key"] for r in picked] == ["WATCH:NVDA"]


def test_an_exit_with_no_reentry_status_is_not_a_candidate():
    """24 EXIT records are not 24 re-entry candidates."""
    sel = select([new_record("EXIT", f"X{i:02d}") for i in range(24)], now=NOW)
    assert sel["selected_count"] == 0


def test_the_stronger_published_status_is_taken_first():
    """REENTER outranks NEAR in the book's own ordering; honour that."""
    recs = [new_record("EXIT", "AAA"), new_record("EXIT", "BBB")]
    sel = select(recs, now=NOW,
                 statuses={"EXIT:AAA": "NEAR", "EXIT:BBB": "REENTER"})
    picked = [r for r in sel["selected"] if r["slot"] == "reentry_or_watch"]
    assert [r["subject_key"] for r in picked] == ["EXIT:BBB"]


def test_a_blocked_watch_never_reaches_the_slot():
    sel = select([new_record("WATCH", "NVDA")], now=NOW,
                 statuses={"WATCH:NVDA": "BLOCK"})
    assert sel["selected_count"] == 0


# ── an empty book is not a crash ──────────────────────────────────────────

def test_an_empty_book_does_not_crash():
    sel = select([], now=NOW)
    assert sel["selected"] == [] and sel["selected_count"] == 0
    assert sel["considered"] == 0
    assert sel["schema"] == "ResearchBudget@v1"


def test_none_and_junk_rows_do_not_crash():
    sel = select([None, "nonsense", {}, 42], now=NOW)
    assert sel["selected_count"] == 0


def test_no_plans_and_no_statuses_do_not_crash():
    sel = select([held("AAA")], now=NOW, plan_subjects=None, statuses=None,
                 observed=None, market_values=None, already_decided=None)
    assert sel["selected_count"] == 1


def test_collapse_ignores_plans_it_cannot_place():
    subjects = collapse_plans_to_subjects(
        [{"plan_id": "a", "situation_type": "S9_UNKNOWN", "symbols": ["X"]},
         {"plan_id": "b", "situation_type": "S1_POSITION_LIFECYCLE", "symbols": []},
         None, "junk"])
    assert subjects == {}


# ── the authority boundary ────────────────────────────────────────────────

def test_the_budget_carries_no_behaviour():
    sel = select([held("AAA")], now=NOW)
    blob = repr(sel)
    for banned in ("recommended_delta_usd", "size_usd", "shares", "target_weight_pct"):
        assert banned not in blob
    assert sel["financial_action"] is False
    assert sel["memory_behavior_influence"] == 0
    assert sel["memory_cognition_influence"] == 1
    assert sel["authority"] == "READ_ONLY_ADVISORY"


def test_selecting_is_read_only_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    select([held("AAA"), new_record("SLEEVE", "CASH")], now=NOW)
    assert list(tmp_path.iterdir()) == []


def test_the_budget_takes_no_vendor_hop():
    """Slice D routes nothing. It hands a short list to whoever does."""
    import scripts.lib.cio_research_budget as mod
    src = open(mod.__file__, encoding="utf-8").read()
    for banned in ("requests", "urllib", "httpx", "openai", "genai", "socket"):
        assert f"import {banned}" not in src
