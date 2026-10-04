"""Decisions card is DEGRADED only for open plans overdue under the expiry rule.

2026-10-03: after the operator-approved expiry sweep 322 plans stayed open, all
inside their revisit grace, yet the card read DEGRADED for any open plan.
"Overdue" now reuses cio_plan_expiry's rule rather than a second definition.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_command_center import _overdue_plan_count, build_cio_now  # noqa: E402
from scripts.lib.cio_observability import build_observability  # noqa: E402

NOW = datetime.now(timezone.utc)


def _plan(pid: str, status: str, revisit_days_ago: int, idle_days: int) -> dict:
    return {
        "plan_id": pid, "status": status, "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["SCHD"],
        "revisit_at": (NOW - timedelta(days=revisit_days_ago)).isoformat(),
        "updated_ts": (NOW - timedelta(days=idle_days)).isoformat(),
    }


def _decisions(cio_now: dict) -> tuple[str, list[str]]:
    out = build_observability(home={"ok": True, "cio_now": cio_now}, brain={}, research_ops={}, data_health={})
    status = next(s["status"] for s in out["scorecards"] if s["name"] == "Decisions")
    return status, [f["issue_id"] for f in out["findings"]]


def test_overdue_count_uses_the_expiry_rule():
    rows = [
        _plan("a", "draft", 40, 40),       # overdue
        _plan("b", "proposed", 20, 20),    # overdue
        _plan("c", "draft", 3, 3),         # inside the window
        _plan("d", "draft", 40, 2),        # touched recently: not overdue
        _plan("e", "accepted", 60, 60),    # accepted plans are the operator's, never overdue here
    ]
    assert _overdue_plan_count(rows) == 2


def test_rows_without_dates_are_unknown_not_zero():
    assert _overdue_plan_count([{"plan_id": "x", "status": "draft"}]) is None
    assert _overdue_plan_count([]) == 0


def test_cio_now_carries_the_overdue_count_from_the_store_rows():
    store = [_plan("a", "draft", 40, 40), _plan("c", "draft", 3, 3)]
    got = build_cio_now(plans=[], all_open_plans=store)
    assert got["open_plans_count"] == 2
    assert got["overdue_open_plans_count"] == 1


def test_open_plans_inside_their_window_are_not_degraded():
    status, findings = _decisions({"decision_count": 5, "open_plans_count": 322, "overdue_open_plans_count": 0})
    assert status == "WORKING"
    assert "CIO-DECISIONS-001" not in findings


def test_overdue_plans_degrade_and_raise_the_finding():
    status, findings = _decisions({"decision_count": 5, "open_plans_count": 322, "overdue_open_plans_count": 7})
    assert status == "DEGRADED"
    assert "CIO-DECISIONS-001" in findings


def test_payload_without_the_overdue_measure_keeps_the_old_strict_rule():
    status, findings = _decisions({"decision_count": 5, "open_plans_count": 3})
    assert status == "DEGRADED"
    assert "CIO-DECISIONS-001" in findings
