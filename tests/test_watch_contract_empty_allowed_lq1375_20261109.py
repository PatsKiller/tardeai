"""ANCHOR: WATCH_CONTRACT_EMPTY_ALLOWED_LQ1375_20261109 — a declared-dead watch feed may say no_new_input.

LQ-20261107-1375, reviewed MERGE by grok-b (LQ-1385). The served reconcile-watch-outcomes contract
allowed only nothing_due. The script's clean empty on the declared dead feed is no_new_input, so the
first output_receipt v2 slot graded empty_violation. The allow-list now includes both reasons.
Synthetic receipt only. No database and no gateway.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_output_verdict import evaluate  # noqa: E402

LANE = "reconcile-watch-outcomes"
RUN_ID = "synthetic-watch-empty"


def _contract():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    return next(c for c in doc["contracts"] if c["id"] == LANE)


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
        "code_sha": "b" * 40,
        "produced_count": 0,
        "attempted_count": 0,
        "skipped_reasons": {},
        "empty_reason": reason,
        "started_at": "2026-11-09T14:00:00+00:00",
        "finished_at": "2026-11-09T14:00:01+00:00",
        "ok_at": "2026-11-09T14:00:01+00:00",
    }


def test_watch_contract_allows_nothing_due_and_no_new_input():
    contract = _contract()
    reasons = contract["expected_output"]["empty_allowed_reasons"]
    assert reasons == ["nothing_due", "no_new_input"]
    text = next(row["text"] for row in contract["healthy"] if row["check"] == "output_produced")
    assert "nothing_due" in text and "no_new_input" in text
    rule = contract["expected_output"]
    allowed = evaluate(rule, _receipt("no_new_input"), run_id=RUN_ID, lane_id=LANE, mode="live",
                       attempt=1, code_sha="b" * 40)
    still = evaluate(rule, _receipt("nothing_due"), run_id=RUN_ID, lane_id=LANE, mode="live",
                     attempt=1, code_sha="b" * 40)
    refused = evaluate(rule, _receipt("quiet_day"), run_id=RUN_ID, lane_id=LANE, mode="live",
                       attempt=1, code_sha="b" * 40)
    assert allowed["verdict"] == "empty_allowed"
    assert still["verdict"] == "empty_allowed"
    assert refused["verdict"] == "empty_violation"
