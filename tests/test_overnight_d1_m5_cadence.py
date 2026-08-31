"""Overnight D1 / M5 — normal-path next_eligible_at closes the cadence loop.

AGENTS.md §15 M5 (Persistence): a scheduled wake loads the record before acting,
and a disposition made days earlier is still honoured with nobody replaying it.

PR #732 put ROUTINE_LOOK_DAYS on apply_after_cycle's normal_completion branch.
This file proves the join the maturity bar needs:

  1. Record lacks next_eligible_at
  2. Normal artifact completion (NOT rejection, NOT defer) stamps a future value
  3. A later wake consult returns skip/cadence_not_due
  4. summarise().decisions_changed_by_record is non-zero

Unattended-on-schedule observation is a separate claim: no already-scheduled
caller invokes apply_after_cycle today (cio_residual_web is NEVER_SCHEDULED and
must not be installed here). This proof is tests + tmp-store dry-run. Mark M5
NOT OBSERVED on schedule in the audit doc until a scheduled consumer exists.

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. Hardening CI allowlist gate overnight_d1_m5_cadence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_instrument_record import InstrumentRecordStore, new_record
from scripts.lib.cio_rehydrate import ROUTINE_LOOK_DAYS, apply_after_cycle
from scripts.lib.cio_wake_subject import (
    PROCEED,
    SKIP_CADENCE,
    decide,
    summarise,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)  # still inside the ROUTINE_LOOK_DAYS window


def _normal_artifact(**extra):
    """Accepted, non-blocked artifact — the ordinary completion path."""
    a = {"verdict": "VALID", "artifact_id": "d1-m5-a1"}
    a.update(extra)
    return a


# ── 1. stamp on normal completion, not on failure paths ───────────────────

def test_record_lacks_next_eligible_before_normal_completion():
    before = new_record("HELD", "D1M5")
    assert before.get("next_eligible_at") is None


def test_normal_completion_stamps_future_next_eligible_at():
    """Acceptance #1: lacks → normal completion → future value present.

    Must NOT use REJECTED / execution_language / defer to produce the stamp.
    """
    before = new_record("HELD", "D1M5")
    assert before.get("next_eligible_at") is None
    after, changed = apply_after_cycle(
        before, now=NOW, artifact=_normal_artifact(),
    )
    assert "next_eligible_at" in changed
    nxt = after["next_eligible_at"]
    assert nxt is not None
    assert nxt > NOW.isoformat()
    due = datetime.fromisoformat(nxt)
    assert round((due - NOW).total_seconds() / 86400.0) == ROUTINE_LOOK_DAYS


def test_stamp_is_not_produced_by_constructing_rejection_or_defer():
    """Pin: the acceptance path above is the normal branch, not a failure costume."""
    rejected, _ = apply_after_cycle(
        new_record("HELD", "RJ"), now=NOW,
        artifact={"verdict": "REJECTED", "artifact_id": "r"},
    )
    deferred, _ = apply_after_cycle(
        new_record("HELD", "DF"), now=NOW,
        artifact=_normal_artifact(),
        lesson={"claim": "operator defer honored, no new catalyst"},
    )
    normal, _ = apply_after_cycle(
        new_record("HELD", "OK"), now=NOW, artifact=_normal_artifact(),
    )
    r_due = datetime.fromisoformat(rejected["next_eligible_at"])
    d_due = datetime.fromisoformat(deferred["next_eligible_at"])
    n_due = datetime.fromisoformat(normal["next_eligible_at"])
    assert round((r_due - NOW).total_seconds() / 86400.0) == 1
    assert round((d_due - NOW).total_seconds() / 86400.0) == 7
    assert round((n_due - NOW).total_seconds() / 86400.0) == ROUTINE_LOOK_DAYS
    # Normal and defer share the 7d number by design (one vocabulary); they are
    # still different branches — normal does not require a defer lesson.
    assert normal.get("research_blocked") is False
    assert rejected.get("research_blocked") is True


# ── 2. later consult returns skip / cadence_not_due ───────────────────────

def test_later_consult_skips_with_decisions_changed_by_record(tmp_path: Path):
    """Acceptance #2 against a tmp IR store (no live mutation).

    Stamp via normal completion → upsert → wake consult → skip/cadence_not_due
    and summarise decisions_changed_by_record > 0.
    """
    store_path = tmp_path / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(store_path)

    before = new_record("HELD", "SCHD")
    assert before.get("next_eligible_at") is None
    after, _ = apply_after_cycle(
        before, now=NOW, artifact=_normal_artifact(artifact_id="d1-schd"),
    )
    store.upsert(after)

    loaded = store.load("HELD:SCHD")
    assert loaded is not None
    assert loaded["next_eligible_at"] > NOW.isoformat()

    wake = {
        "wake_job_id": "d1-m5-wake-1",
        "trigger_type": "OPERATOR_MESSAGE",
        "subject_key": "HELD:SCHD",
        "context": {"text": "What should I watch on SCHD this week?"},
    }
    decision = decide(wake, store=store, now=LATER, known_keys={"HELD:SCHD"})

    assert decision["without_record"] == PROCEED
    assert decision["verdict"] == SKIP_CADENCE
    assert decision["verdict"] == "skip/cadence_not_due"
    assert decision["record_used"] is True
    assert decision["record_found"] is True
    assert "defers research until" in (decision.get("reason") or "")

    summary = summarise([decision])
    assert summary["decisions_changed_by_record"] > 0
    assert summary["skipped_cadence_not_due"] == 1
    assert summary["changed"][0]["subject_key"] == "HELD:SCHD"
    assert summary["changed"][0]["with_record"] == SKIP_CADENCE


def test_end_to_end_dry_run_quoted_shape(tmp_path: Path, capsys):
    """Dry-run shape the audit doc quotes: tmp store only, --dry-run semantics.

    Prints a single JSON-ish proof block so the operator can see the before/after
    without touching the live IR store.
    """
    store = InstrumentRecordStore(tmp_path / "ir.jsonl")
    before = new_record("HELD", "NOC")
    assert before.get("next_eligible_at") is None

    after, changed = apply_after_cycle(
        before, now=NOW, artifact=_normal_artifact(artifact_id="d1-noc"),
    )
    store.upsert(after)

    d = decide(
        {"wake_job_id": "dry-1", "trigger_type": "GOAL_DUE",
         "subject_key": "HELD:NOC", "context": {}},
        store=store, now=LATER, known_keys={"HELD:NOC"},
    )
    s = summarise([d])

    proof = {
        "dry_run": True,
        "store": str(tmp_path / "ir.jsonl"),
        "before_next_eligible_at": None,
        "after_next_eligible_at": after["next_eligible_at"],
        "changed_fields": changed,
        "routine_look_days": ROUTINE_LOOK_DAYS,
        "consult_verdict": d["verdict"],
        "decisions_changed_by_record": s["decisions_changed_by_record"],
        "via": "normal_completion",  # not rejection, not defer
    }
    print("D1_M5_DRY_RUN_PROOF", proof)

    assert proof["after_next_eligible_at"] is not None
    assert proof["consult_verdict"] == SKIP_CADENCE
    assert proof["decisions_changed_by_record"] >= 1
    out = capsys.readouterr().out
    assert "D1_M5_DRY_RUN_PROOF" in out
    assert "normal_completion" in out


# ── 3. cadence constant still declared with reasoning ─────────────────────

def test_routine_look_days_declared_with_reasoning():
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_rehydrate.py").read_text(encoding="utf-8")
    block = src[:src.index("ROUTINE_LOOK_DAYS = 7")]
    assert "describes failures, not cadence" in block
    assert "NEVER_SCHEDULED" in block
    assert ROUTINE_LOOK_DAYS == 7


def test_wake_subject_documents_normal_path_writer():
    """Consult module must name the ordinary stamp source, not only failures."""
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_wake_subject.py").read_text(encoding="utf-8")
    assert "ROUTINE_LOOK_DAYS" in src
    assert "apply_after_cycle" in src


def test_no_scheduled_apply_after_cycle_caller_is_honest():
    """Guardrail for the doc claim: production scripts do not call it yet.

    If a scheduled caller is wired later, this test should be replaced with an
    assertion that names that path — not silently deleted.
    """
    root = Path(__file__).resolve().parent.parent / "scripts"
    callers = []
    for p in root.rglob("*.py"):
        if p.name in {"cio_rehydrate.py"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "apply_after_cycle" in text and "def apply_after_cycle" not in text:
            # import-only or call sites outside the defining module
            if "apply_after_cycle(" in text:
                callers.append(str(p.relative_to(root.parent)))
    # migrate path may attach_operator_turn (defer), not normal completion.
    # research_reaches_surface is a test. Production stamp callers: none.
    prod = [c for c in callers if not c.startswith("tests/")]
    assert prod == [], (
        "unexpected production apply_after_cycle caller(s): "
        f"{prod}. Update D1 audit + this test if a scheduled consumer was wired."
    )
