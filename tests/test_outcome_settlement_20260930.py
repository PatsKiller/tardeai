"""Outcome settlement defects measured 2026-09-30 (read-only).

1. cio_run goal wakes declared entity_type GOAL; the checkpoint subject dropped it and stamped
   UNRESOLVED, so 7,171 checkpoints in 7 days were headed for NOT_PRICE_RESOLVABLE /
   no_security_subject — the label for a real identity gap.
2. enrich_checkpoint never passed plan_id, so every row was plan_binding "unbound".
3. AEC hourly commitments were due at mint+1h; the next timer fire landed a second early,
   the commitment stayed INSUFFICIENT and was then orphaned (131 of 257 never settled)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import r17_checkpoint_binding as r17  # noqa: E402
from scripts.lib import outcome_resolution as orz  # noqa: E402

NOW = datetime(2026, 9, 30, 14, 0, 2, 138000, tzinfo=timezone.utc)


def test_goal_wake_checkpoint_keeps_its_type_and_the_resolver_labels_it_honestly():
    decision = {"decision_id": "d-goal-1", "entity_type": "GOAL", "subject_id": "freshness:BOOK",
                "symbol": None, "recommendation": "REVIEW", "producer_id": "cio_run"}
    subj = r17.canonical_checkpoint_subject(decision)
    assert subj["entity_type"] == "GOAL" and subj["subject_guid"] is None and subj["subject_id"] == "GOAL:freshness:BOOK"
    ck = r17.enrich_checkpoint(decision, "event-relative", source_sha="t", now=NOW)
    assert ck["entity_type"] == "GOAL"
    ok, why = orz.price_resolvable(ck)
    assert ok is False and why == "entity_type_goal"


def test_security_and_unresolved_decisions_are_unchanged():
    subj = r17.canonical_checkpoint_subject({"decision_id": "d2", "symbol": None, "recommendation": "HOLD"})
    assert subj["entity_type"] == "UNRESOLVED"


def test_plan_id_is_bound_when_the_decision_carries_one():
    ck = r17.enrich_checkpoint({"decision_id": "d3", "plan_id": "plan_e2cdd9c8c1a8", "symbol": None},
                               "event-relative", source_sha="t", now=NOW)
    assert ck["plan_id"] == "plan_e2cdd9c8c1a8" and ck["plan_binding"] == "bound"
    ck2 = r17.enrich_checkpoint({"decision_id": "d4", "symbol": None}, "event-relative", source_sha="t", now=NOW)
    assert ck2["plan_id"] is None and ck2["plan_binding"] == "unbound"


def test_aec_commitment_is_due_at_the_top_of_the_next_hour():
    src = (ROOT / "scripts" / "aec_command_center_cycle.py").read_text(encoding="utf-8")
    assert "due = when.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)" in src
    assert "due = when + timedelta(hours=1)" not in src
    from datetime import timedelta
    due = NOW.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    next_fire = datetime(2026, 9, 30, 15, 0, 0, 531000, tzinfo=timezone.utc)
    assert next_fire >= due            # the 15:00:00.5 fire now settles the 14:00:02 commitment
