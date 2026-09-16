"""P10 — the subject-collapse law, enforced in the LIVE path.

`scripts/lib/cio_research_budget.py` encodes the operator's law: one research
decision per subject_key per calendar day, cap 5. It was written explicitly to
stop "one cash question became 36 paid jobs". Measured 2026-09-16: its only two
importers both declare NO_CONSUMER_REASON, so it was a transitive dark chain and
the law was enforced nowhere in the live path.

The live path is `scripts/cio_wake_dispatch_entrypoint.py`, the `*/5 * * * *`
dispatcher that is the one scheduled caller of the research gate. These tests
pin that the law is now applied there.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cio_wake_dispatch_entrypoint as entry
from scripts.lib.cio_research_budget import (
    CASH_SLEEVE,
    DAILY_CAP,
    collapse_plans_to_subjects,
)


def test_thirty_six_cash_plans_collapse_to_one_subject() -> None:
    """The law is expressed in SUBJECTS, never in plans. This is the whole point."""
    plans = [{"plan_id": f"p{i}", "situation_type": "S5_CASH_DEPLOYMENT",
              "symbols": []} for i in range(36)]
    collapsed = collapse_plans_to_subjects(plans)
    assert list(collapsed) == [CASH_SLEEVE]
    assert len(collapsed[CASH_SLEEVE]) == 36, (
        "36 cash plans must cost ONE slot carrying 36 plan_ids, not 36 slots"
    )


def test_budget_allows_a_fresh_subject() -> None:
    state = {"enforced": True, "spent": set(), "cap": DAILY_CAP}
    verdict = entry._budget_allows("HELD:PFLT", state)
    assert verdict["allow"] is True
    assert verdict["reason"] == "within_budget"


def test_budget_refuses_a_subject_already_decided_today() -> None:
    """The collapse law's memory: a second run of the day must not re-ask."""
    state = {"enforced": True, "spent": {"HELD:PFLT"}, "cap": DAILY_CAP}
    verdict = entry._budget_allows("HELD:PFLT", state)
    assert verdict["allow"] is False
    assert verdict["reason"] == "already_decided_today"


def test_budget_refuses_once_the_daily_cap_is_reached() -> None:
    state = {"enforced": True,
             "spent": {f"HELD:S{i}" for i in range(DAILY_CAP)},
             "cap": DAILY_CAP}
    verdict = entry._budget_allows("HELD:NEW", state)
    assert verdict["allow"] is False
    assert verdict["reason"] == "daily_cap_reached"


def test_cap_is_five() -> None:
    """The operator's starting cap. Raising it is an operator change."""
    assert DAILY_CAP == 5


def test_unenforced_budget_allows_everything() -> None:
    """Fail-soft: a budget that could not load must not block the dispatcher."""
    state = {"enforced": False, "reason": "unavailable:OSError", "spent": set(), "cap": 0}
    verdict = entry._budget_allows("HELD:PFLT", state)
    assert verdict["allow"] is True
    assert verdict["reason"] == "unavailable:OSError"


def test_enforcement_can_be_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator escape hatch that needs no code change."""
    monkeypatch.setenv("CIO_RESEARCH_BUDGET_ENFORCE", "0")
    state = entry._research_budget_state()
    assert state["enforced"] is False
    assert state["reason"] == "disabled_by_CIO_RESEARCH_BUDGET_ENFORCE"


def test_enforced_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent the env var the law is ON -- the safe direction is less spend."""
    monkeypatch.delenv("CIO_RESEARCH_BUDGET_ENFORCE", raising=False)
    state = entry._research_budget_state()
    assert state["enforced"] is True
    assert state["cap"] == DAILY_CAP


def test_absent_ledger_permits_the_first_decision_of_the_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An absent ledger is 'nothing spent yet', not 'deny everything'.

    This is deliberately NOT the search_budget 'BudgetUnavailable => DENY' case:
    this ledger records what was already spent, and it legitimately does not
    exist before the day's first decision. Denying on absence would mean the law
    could never permit a first decision at all.
    """
    monkeypatch.delenv("CIO_RESEARCH_BUDGET_ENFORCE", raising=False)
    monkeypatch.setattr(entry, "_PROJECT", tmp_path)
    state = entry._research_budget_state()
    assert state["enforced"] is True
    assert state["spent"] == set()
    assert entry._budget_allows("HELD:PFLT", state)["allow"] is True


def test_recording_a_decision_spends_the_subjects_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Record once, and the same subject is refused for the rest of the day."""
    monkeypatch.delenv("CIO_RESEARCH_BUDGET_ENFORCE", raising=False)
    monkeypatch.setattr(entry, "_PROJECT", tmp_path)
    state = entry._research_budget_state()

    assert entry._budget_record("HELD:PFLT", {"decision": "RESEARCH"}, state) is True
    assert "HELD:PFLT" in state["spent"]
    assert entry._budget_allows("HELD:PFLT", state)["allow"] is False

    ledger = tmp_path / "data" / "cio" / "cio_research_budget_ledger.jsonl"
    assert ledger.is_file(), "the decision must be durable, not in-memory only"
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert [r["subject_key"] for r in rows] == ["HELD:PFLT"]


def test_a_second_record_of_the_same_subject_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CIO_RESEARCH_BUDGET_ENFORCE", raising=False)
    monkeypatch.setattr(entry, "_PROJECT", tmp_path)
    state = entry._research_budget_state()
    entry._budget_record("HELD:PFLT", {"decision": "RESEARCH"}, state)
    # A fresh state re-reads the ledger, as the next cron cycle would.
    state2 = entry._research_budget_state()
    assert "HELD:PFLT" in state2["spent"]
    assert entry._budget_record("HELD:PFLT", {"decision": "RESEARCH"}, state2) is False


def test_the_live_dispatcher_actually_consults_the_budget() -> None:
    """Import-graph honesty: the gate call must be guarded in the live loop.

    A grep for a symbol cannot see which branch the symbol is in -- the exact
    failure that let `decide_after_load` sit behind `--dry-run` for months while
    a test asserted only that the NAME appeared in the file. So this asserts the
    guard wraps the gate call, not merely that the budget is imported somewhere.
    """
    source = Path(entry.__file__).read_text(encoding="utf-8")
    assert "budget_state = _research_budget_state()" in source

    # Scope to the LIVE dispatch loop. `decide_after_load` is ALSO called in
    # `dry_run_record_consult`, which runs only under --dry-run and appears
    # earlier in the file, so a whole-file index matches that call instead and
    # proves nothing about the scheduled path. This is the same trap the module
    # docstring records: `test_entrypoint_exposes_dry_run_flag` asserted only
    # that a NAME appeared in this file, which a dry-run-only call satisfied,
    # and the #810 gate sat unreachable behind --dry-run for months.
    live = source[source.index("budget_state = _research_budget_state()"):]
    assert live.index("budget_verdict = _budget_allows(") \
        < live.index("research = decide_after_load("), \
        "the budget must be consulted BEFORE the research gate in the live loop"
    assert "_budget_record(subject_key, research, budget_state)" in live
    assert "BUDGET_SKIPPED" in live, "a refusal must be recorded with its reason"
