"""Independent SIEM recovery assertions; no DB/network/effect."""

import json, copy
from datetime import datetime, timezone
import pytest
from scripts.lib import n8n_siem_bridge as B

LANE = "fixture-output"
OPENED = "2026-10-18T12:00:00+00:00"


def run():
    rec = {
        "schema": "RunReceipt@v2",
        "lane_id": LANE,
        "run_id": "d:fixture-output:live:20261018T1300",
        "attempt": 1,
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "output_verdict": {"verdict": "produced", "contract_id": LANE},
    }
    return {
        "lane_id": LANE,
        "run_id": rec["run_id"],
        "attempt": 1,
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "finished_at": "2026-10-18T13:00:00+00:00",
        "receipt_json": json.dumps(rec),
    }


def close(row, created_at=OPENED):
    found, good = B.ledger_findings({LANE: row}, {})
    opened = {
        "id": 7,
        "component": "n8n:" + LANE,
        "event_type": "RUN_FAILED",
        "severity": "CRITICAL",
        "lifecycle_state": "active",
        "created_at": created_at,
    }
    return B.plan(B.merge(found), [opened], env="fixture", good_lanes=good, ledger_ok=True, fanin_ok=True)


@pytest.mark.parametrize(
    "field,value", [("lane_id", "other-lane"), ("run_id", "other-attempt-run"), ("attempt", 2), ("state", "RUN_FAILED")]
)
def test_mismatched_inner_receipt_cannot_close_business_episode(field, value):
    row = run()
    rec = json.loads(row["receipt_json"])
    rec[field] = value
    row["receipt_json"] = json.dumps(rec)
    assert not close(row)["resolve"]


@pytest.mark.parametrize("finished_at", [float("nan"), float("inf"), "2099-01-01T00:00:00+00:00"])
def test_nonfinite_or_future_output_time_cannot_close_episode(finished_at):
    row = run()
    rec = json.loads(row["receipt_json"])
    rec["finished_at"] = finished_at
    row["finished_at"] = None
    row["receipt_json"] = json.dumps(rec)
    assert not close(row)["resolve"]


def test_fanin_own_failed_live_run_needs_generation_bound_business_proof():
    opened = {
        "id": 7,
        "component": "n8n:" + B.FANIN_LANE,
        "event_type": "RUN_FAILED",
        "severity": "CRITICAL",
        "lifecycle_state": "active",
        "created_at": OPENED,
    }
    result = B.plan({}, [opened], env="fixture", good_lanes={}, ledger_ok=True, fanin_ok=True)
    assert not result["resolve"], "a fresh fan-in bool is not newer attempt-bound useful-output proof"


def test_duplicate_episodes_use_each_open_time():
    row = run()
    found, good = B.ledger_findings({LANE: row}, {})
    older = {
        "id": 7,
        "component": "n8n:" + LANE,
        "event_type": "RUN_FAILED",
        "severity": "CRITICAL",
        "created_at": OPENED,
    }
    newer = {**older, "id": 8, "created_at": "2026-10-18T14:00:00+00:00"}
    result = B.plan({}, [older, newer], env="fixture", good_lanes=good, ledger_ok=True, fanin_ok=True)
    assert [r["id"] for r in result["resolve"]] == [7]
    assert [r["id"] for r in result["hold"]] == [8]
