"""ANCHOR: JOBS_HEALTH_OFFPEAK_SKIP_LQ1408_20261109 — offpeak_skip is Skipped, never Missed.

LQ-20261107-1408 / page defect 144: /v3/ops/jobs labelled Hermes usefulness backfill
Missed while the ledger showed RUN_DONE reason=offpeak_skip (deliberate DeepSeek peak skip).
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib import jobs_health as J
from scripts.lib.cron_outage_watchdog import allowlist_gate


# INC-261109-zyskgh slot: Sun 21:20 ET = Mon 02:20 UTC (inside DeepSeek peak).
NOW = datetime(2026, 11, 9, 2, 20, tzinfo=timezone.utc)
SUCCESS_AT = datetime(2026, 11, 9, 0, 15, tzinfo=timezone.utc)  # Sun 19:15 ET last real success


def _hermes_lane(gate="scheduled"):
    row = {
        "lane_id": "hermes-usefulness-backfill",
        "display_name": "Hermes usefulness backfill",
        "state": "ACTIVE",
        "expected_cadence_hours": 1,
        "scheduler": {
            "kind": "n8n",
            "expression": "dispatcher",
            "cadence": "15 * * * *",
            "match": "scripts/hermes_external_feedback_loop.py --apply",
        },
        "dispatch": {"mode": "live", "cron": ["15 * * * *"], "tz": "America/New_York"},
        "output_signal": {
            "kind": "json_key",
            "key": "ok_at",
            "path": "data/runtime/hermes-usefulness-backfill_last.json",
        },
    }
    if gate is not None:
        row["watchdog_offpeak_gate"] = gate
    return row


def _success(*, at: datetime):
    base = {
        "run_id": f"ok-{at.isoformat()}",
        "lane_id": "hermes-usefulness-backfill",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "finished_at": at.isoformat(),
        "requested_at": at.isoformat(),
    }
    return {
        **base,
        "receipt": {
            **base,
            "schema": "RunReceipt@v3",
            "output_verdict": {"verdict": "produced"},
            "stage_clamp": {"effective_mode": "live", "requested_mode": "live", "clamped": False},
        },
    }


def test_skipped_by_policy_is_skipped_not_missed():
    result = J.build(
        {"lanes": [_hermes_lane()]},
        {"events": [], "successes": {
            "hermes-usefulness-backfill": [{"at": SUCCESS_AT.isoformat(), "validated_success": True}],
        }},
        runs=[_success(at=SUCCESS_AT)],
        watchdog={},
        now=NOW,
        trading_day=lambda d: True,
    )
    row = next(r for r in result["rows"] if r["lane_id"] == "hermes-usefulness-backfill")
    assert row["result"] == "skipped", row
    assert "miss" not in row["cause"].lower() or "not a miss" in row["cause"].lower()
    assert result["summary"]["missed"] == 0
    assert result["summary"]["skipped"] >= 1
    # Skipped is not an incident / attention-class failure
    assert all(i["id"] != "hermes-usefulness-backfill" for i in result["incidents"])


def test_without_gate_still_missed():
    result = J.build(
        {"lanes": [_hermes_lane(gate=None)]},
        {"events": [], "successes": {
            "hermes-usefulness-backfill": [{"at": SUCCESS_AT.isoformat(), "validated_success": True}],
        }},
        runs=[_success(at=SUCCESS_AT)],
        watchdog={},
        now=NOW,
        trading_day=lambda d: True,
    )
    row = next(r for r in result["rows"] if r["lane_id"] == "hermes-usefulness-backfill")
    assert row["result"] == "missed"


def test_allowlist_binds_hermes_scheduled_gate():
    allowlist = {
        "lanes": [{
            "lane_id": "hermes-usefulness-backfill",
            "command": ["python3", "scripts/hermes_external_feedback_loop.py", "--apply"],
            "offpeak_gate": "scheduled",
        }],
    }
    assert allowlist_gate(_hermes_lane(gate=None), allowlist) == "scheduled"
