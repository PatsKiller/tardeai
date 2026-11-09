"""ANCHOR: EXIT_ADVISORY_NOTHING_DUE_CONTRACT_LQ1424 — LQ-20261107-1424.

reconcile-exit-advisory-outcomes may exit 0 with empty_reason nothing_due when
Gain Guardian is published and nothing is due (LQ-1416). The contract must allow
that reason or the enforced grader returns empty_reason_not_allowed. up_to_date
and all_skipped stay allowed. dependency_unavailable stays a violation.
Synthetic receipt only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_output_verdict import evaluate  # noqa: E402

LANE = "reconcile-exit-advisory-outcomes"
RUN_ID = "synthetic-exit-nothing-due"
SHA = "b" * 40


def _rule():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    contract = next(c for c in doc["contracts"] if c["id"] == LANE)
    return contract["expected_output"]


def _receipt(reason: str) -> dict:
    return {
        "schema": "LaneRunReceipt@v2",
        "lane_id": LANE,
        "run_id": RUN_ID,
        "mode": "live",
        "run_mode": "live",
        "status": "ok",
        "outcome": "empty",
        "attempt": 1,
        "code_sha": SHA,
        "produced_count": 0,
        "attempted_count": 0,
        "skipped_reasons": {},
        "empty_reason": reason,
        "started_at": "2026-11-09T14:00:00+00:00",
        "finished_at": "2026-11-09T14:00:01+00:00",
        "ok_at": "2026-11-09T14:00:01+00:00",
    }


def _grade(reason: str) -> str:
    return evaluate(
        _rule(), _receipt(reason), run_id=RUN_ID, lane_id=LANE, mode="live", attempt=1, code_sha=SHA
    )["verdict"]


def test_nothing_due_is_allowed_and_the_old_reasons_stay():
    reasons = _rule()["empty_allowed_reasons"]
    assert reasons == ["nothing_due", "up_to_date", "all_skipped"]
    assert "dependency_unavailable" in _rule()["fatal_skip_reasons"]
    assert _grade("nothing_due") == "empty_allowed"
    assert _grade("up_to_date") == "empty_allowed"
    assert _grade("all_skipped") == "empty_allowed"
    assert _grade("dependency_unavailable") == "empty_violation"
