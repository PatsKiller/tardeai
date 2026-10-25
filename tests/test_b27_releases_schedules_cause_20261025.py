"""[shared-infra] Releases & Schedules view: real failure causes and failed deploy attempts survive (AGENTS.md 28.9).

Moved out of batch 27 (W4, tests/test_w4_jobs_health_20261024.py) because scripts/lib/releases_schedules_view.py is
shared infrastructure and ships alone. Disposable roots only.
"""
import json
from datetime import datetime, timedelta, timezone

from scripts.lib import releases_schedules_view as RS

NOW = datetime(2026, 10, 23, 16, 20, tzinfo=timezone.utc)


def test_stderr_cause_replaces_generic_exit_code_on_releases_projection():
    receipt = {"reason": "exit_1", "stderr_tail": "Permission denied for wrapper"}
    bits = RS._receipt_bits(json.dumps(receipt))
    assert bits["reason"] == bits["cause"] == receipt["stderr_tail"]
    assert RS._receipt_bits(json.dumps({"reason": "exit_1"}))["reason"] == "Failure recorded; stderr diagnostic was not retained"
    assert RS._receipt_bits(json.dumps({"reason": "lock busy"}))["reason"] == "lock busy"


def test_release_failures_survive_a_later_successful_receipt(tmp_path):
    deploy, windows = tmp_path / "deploy", tmp_path / "windows"
    deploy.mkdir()
    (deploy / "deploy_receipt.json").write_text(json.dumps({"at": NOW.isoformat(), "mode": "promote", "ok": True}))
    attempts = [{"at": (NOW - timedelta(minutes=i + 1)).isoformat(), "mode": "promote", "ok": False,
                 "extra": "wrapper refusal"} for i in range(5)]
    (deploy / "deploy_receipt_history.jsonl").write_text("".join(json.dumps(a) + "\n" for a in attempts))
    value = RS.read_release_errors(deploy, windows, NOW)["value"]
    assert len(value["rows"]) == 5 and all(r["detail"] == "wrapper refusal" for r in value["rows"])
    assert value["coverage_gaps"] == []


def test_missing_history_is_a_named_gap_not_a_clean_result(tmp_path):
    deploy, windows = tmp_path / "deploy", tmp_path / "windows"
    deploy.mkdir()
    value = RS.read_release_errors(deploy, windows, NOW)["value"]
    assert value["coverage_gaps"] == ["Deploy attempt history is not available; latest receipt only"]
