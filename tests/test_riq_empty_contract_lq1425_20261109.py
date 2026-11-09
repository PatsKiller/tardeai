"""ANCHOR: RIQ_EMPTY_CONTRACT_LQ1425 — LQ-20261107-1425.

research-intelligence-queue had no expected_output, so an idle drain was no_rule.
The batch3 rework writes produced_count=0 and empty_reason=no_new_input only when
both counts are explicit ints equal to 0. That reason must be allowed. A missing
count is not an allowed empty. dry_run stays allowed for a harness plan.
Synthetic receipt only. The allowlist does not set output_receipt v2 in this commit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_output_verdict import evaluate  # noqa: E402

LANE = "research-intelligence-queue"
RUN_ID = "synthetic-riq-idle"
SHA = "b" * 40


def _rule():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    return next(c for c in doc["contracts"] if c["id"] == LANE)["expected_output"]


def _receipt(reason: str | None, produced: int | None) -> dict:
    doc = {
        "schema": "LaneRunReceipt@v2",
        "lane_id": LANE,
        "run_id": RUN_ID,
        "mode": "live",
        "run_mode": "live",
        "status": "ok",
        "outcome": "empty" if produced == 0 else "ok",
        "attempt": 1,
        "code_sha": SHA,
        "attempted_count": 0 if produced == 0 else produced,
        "skipped_reasons": {},
        "empty_reason": reason,
        "started_at": "2026-11-09T14:00:00+00:00",
        "finished_at": "2026-11-09T14:00:01+00:00",
        "ok_at": "2026-11-09T14:00:01+00:00",
    }
    if produced is not None:
        doc["produced_count"] = produced
    return doc


def _grade(reason: str | None, produced: int | None) -> str:
    return evaluate(
        _rule(), _receipt(reason, produced), run_id=RUN_ID, lane_id=LANE, mode="live", attempt=1, code_sha=SHA
    )["verdict"]


def test_idle_drain_is_allowed_and_a_missing_count_is_not():
    reasons = _rule()["empty_allowed_reasons"]
    assert reasons == ["no_new_input", "dry_run"]
    assert _rule()["rule"] == "empty_allowed"
    assert _grade("no_new_input", 0) == "empty_allowed"
    assert _grade("dry_run", 0) == "empty_allowed"
    assert _grade("nothing_due", 0) == "empty_violation"
    assert _grade(None, 0) == "empty_violation"
    assert _grade(None, 3) == "produced"
