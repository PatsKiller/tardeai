"""Live SIEM episodes require shared, fresh business-output proof; fake effects only."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from scripts.lib import n8n_siem_bridge as B
from scripts.lib import recovery_validator as RV

LANE = "canary-output"
OPENED = "2026-10-18T12:00:00+00:00"


def run():
    receipt = {
        "schema": "RunReceipt@v2",
        "lane_id": LANE,
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "output_verdict": {"verdict": "produced", "contract_id": LANE},
    }
    return {
        "lane_id": LANE,
        "run_id": "d:canary-output:live:20261018T1300",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "finished_at": "2026-10-18T13:00:00+00:00",
        "receipt_json": json.dumps(receipt),
    }


def close_plan(row, *, created_at=OPENED):
    found, good = B.ledger_findings({LANE: row}, {})
    opened = {
        "id": 7,
        "component": "n8n:" + LANE,
        "event_type": "RUN_FAILED",
        "severity": "CRITICAL",
        "lifecycle_state": "active",
        "created_at": created_at,
    }
    return B.plan(B.merge(found), [opened], env="test", good_lanes=good, ledger_ok=True, fanin_ok=True)


@pytest.mark.parametrize(
    "change",
    ["dry", "clamped", "undeclared", "empty_violation", "wrong_lane", "old", "missing_time", "missing_incident_time"],
)
def test_unproven_later_run_cannot_resolve_live_episode(change):
    row = run()
    rec = json.loads(row["receipt_json"])
    if change == "dry":
        row["mode"] = rec["mode"] = "dry_run"
    elif change == "clamped":
        rec["mode"] = "dry_run"
        rec["stage_clamp"] = {"effective_mode": "dry_run"}
    elif change in ("undeclared", "empty_violation"):
        rec["output_verdict"]["verdict"] = "declared_not_enforced" if change == "undeclared" else change
    elif change == "wrong_lane":
        row["lane_id"] = rec["lane_id"] = "other-lane"
    elif change == "old":
        row["finished_at"] = "2026-10-18T11:59:59+00:00"
    elif change == "missing_time":
        row.pop("finished_at")
    row["receipt_json"] = json.dumps(rec)
    result = close_plan(row, created_at=None if change == "missing_incident_time" else OPENED)
    assert not result["resolve"], "unproven run must hold the live incident"
    assert result["hold"]


def test_fresh_same_business_output_can_resolve_live_episode():
    result = close_plan(run())
    assert [r["id"] for r in result["resolve"]] == [7]
    assert not result["hold"]


def test_siem_consumer_calls_shared_recovery_verdict(monkeypatch):
    calls = []
    original = RV.validate

    def observed(row, **kwargs):
        calls.append(copy.deepcopy(kwargs))
        return original(row, **kwargs)

    monkeypatch.setattr(RV, "validate", observed)
    close_plan(run())
    assert any(c.get("mode") == "live" and c.get("lane") == LANE for c in calls)
    assert any(c.get("since") == datetime.fromisoformat(OPENED).timestamp() for c in calls)


def test_legacy_good_lane_set_cannot_assert_recovery():
    opened = {
        "id": 7,
        "component": "n8n:" + LANE,
        "event_type": "RUN_FAILED",
        "severity": "CRITICAL",
        "created_at": OPENED,
    }
    result = B.plan({}, [opened], env="test", good_lanes={LANE}, ledger_ok=True, fanin_ok=True)
    assert not result["resolve"], "a lane name is not recovery evidence"


def test_explicit_valid_empty_work_is_business_proof():
    row = run()
    receipt = json.loads(row["receipt_json"])
    receipt["output_verdict"]["verdict"] = "empty_allowed"
    row["receipt_json"] = json.dumps(receipt)
    assert close_plan(row)["resolve"]
