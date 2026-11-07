"""LQ-20261107-279 (decision on LQ-268): the dispatcher stops planning the llm-spend daily event.

Synthetic observations and a synthetic receipt only. No real spend, account or broker data.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.n8n_pilot_dispatch import dispatch_lane, plan_lane

LLM = "llm-spend-report-daily"
NOW = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)


def _llm_obs():
    return {"artifact_status": "OBSERVED", "report_key": "daily:2026-01-01", "ran_at": "2026-01-01T12:05:00+00:00",
            "period": "daily", "amount_usd": 1.23}


def test_llm_daily_observed_report_no_longer_fires():
    plan = plan_lane(LLM, _llm_obs(), Path("."))
    assert plan["fired"] is False
    assert "Telegram" in plan["why"]
    assert "idempotency_key" not in plan


def test_llm_daily_dispatch_end_to_end_plans_nothing(tmp_path):
    # synthetic receipt under a temp state root; dispatch_lane with no gateway client (dry run)
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "llm_spend_report_last_daily.json").write_text(json.dumps({
        "cadence": "daily", "key": "daily:2026-01-01", "usd": 1.23, "sent": True,
        "ran_at": "2026-01-01T12:05:00+00:00", "schema": "LlmSpendReportRun@v1"}), encoding="utf-8")
    row = dispatch_lane(LLM, client=None, root=tmp_path, sha="", now=NOW, db_query=None)
    assert row["fired"] is False
    assert row["outcome"] == "NO_FIRE"
    assert "event_id" not in row


def test_other_pilot_lanes_still_fire_with_their_observations():
    morning = {"artifact_status": "OBSERVED", "session_date": "2026-01-01", "claimed_at": "2026-01-01T07:30:00+00:00"}
    assert plan_lane("morning-brief-0730", morning, Path("."))["fired"] is True
    holdings = {"hermes_run_id": "hrun-synthetic-1"}
    assert plan_lane("research-scheduler-holdings", holdings, Path("."))["fired"] is True
    digest = {"detector_event_id": "evt-synthetic-1", "symbol": "SYN", "detector_status": "OK",
              "notified_at": "2026-01-01T12:00:00+00:00"}
    assert plan_lane("material-change-digest", digest, Path("."))["fired"] is True
    reminder = {"run_receipt": {"run_id": "run-synthetic-1", "outcome": "SENT", "action_count": 2,
                                "delivery_status": "DELIVERY_OBSERVED"}}
    assert plan_lane("approval-package-reminder", reminder, Path("."))["fired"] is True


def test_other_lanes_keep_their_fire_keys_and_paths():
    morning = {"artifact_status": "OBSERVED", "session_date": "2026-01-01", "claimed_at": "2026-01-01T07:30:00+00:00"}
    plan = plan_lane("morning-brief-0730", morning, Path("."))
    assert plan["idempotency_key"].startswith("mb-")
    assert plan["artifact_rel"] == "data/cio/morning_brief_semantic_state.json"
