"""Failure evidence stays actionable without inventing facts or exposing secrets."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("failure_diagnostics_under_test", ROOT / "scripts/lib/job_failure_diagnostics.py")
D = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = D
SPEC.loader.exec_module(D)

START = "2026-11-02T18:00:00Z"
END = "2026-11-02T18:00:05Z"


def run_receipt(**over):
    receipt = {"schema": "RunReceipt@v3", "run_id": "fixture-run-1", "lane_id": "fixture-lane",
               "state": "RUN_FAILED", "exit_code": 1, "started_at": START, "finished_at": END,
               "duration_s": 5.0, "reason": "exit_1", "stderr_tail": None}
    receipt.update(over)
    return {"run_id": "fixture-run-1", "lane_id": "fixture-lane", "state": receipt["state"],
            "worker_id": "private-fixture-host:123:worker", "receipt": receipt}


@pytest.mark.parametrize(("why", "key"), [
    ("attempt_receipt_missing", "receipt_attempt_missing"),
    ("rule_missing", "output_contract_rule_missing"),
    ("counts_inconsistent", "output_contract_count_units"),
])
def test_output_contract_subreason_is_actionable_and_exit_zero_is_preserved(why, key):
    run = run_receipt(exit_code=0, reason="output_unverifiable",
                      output_verdict={"verdict": "unverifiable", "why": why})
    result = D.diagnostics_for_run(run, last_success=START, host_role="n8n_executor")
    assert result["failure_kind"] == "output_contract"
    assert result["failure_reason"] == f"output_unverifiable: {why}"
    assert result["execution"]["exit_code"] == 0
    assert result["output_contract"]["reason"] == why
    assert result["remediation"]["key"] == key


def test_missing_stderr_and_traceback_are_gaps_not_a_fabricated_exception():
    result = D.diagnostics_for_run(run_receipt())
    assert result["failure_reason"] == "Failure recorded; stderr diagnostic was not retained"
    assert result["traceback"] == {"available": False, "text": None, "reason": "not_retained", "source": None}
    assert result["exception_type"] is None
    assert "stderr_not_retained" in result["gaps"]
    assert "traceback_not_retained" in result["gaps"]


def test_executor_lost_is_synthetic_and_never_claims_a_child_exit_or_traceback():
    result = D.diagnostics_for_run(run_receipt(
        state="RUN_TIMEOUT", reason="executor_lost", exit_code=0,
        stderr_tail="Traceback (most recent call last):\nRuntimeError: unrelated",
        lost={"heartbeat_at": START, "pid": 123, "overdue": False},
    ), host_role="n8n_executor")
    assert result["evidence"]["synthetic"] is True
    assert result["evidence"]["source"] == "executor_reaper"
    assert result["execution"]["exit_code"] is None
    assert result["traceback"]["available"] is False
    assert result["traceback"]["reason"] == "executor_reaper_did_not_observe_child_output"
    assert result["executor_loss"] == {"heartbeat_at": START, "overdue": False, "pid_recorded": True}
    assert "exit_code_not_observed" in result["gaps"]


def test_python_traceback_is_redacted_before_truncation_and_input_is_unchanged():
    secret = "synthetic-private-value"
    trace = 'Traceback (most recent call last):\n  File "worker.py", line 1\nRuntimeError: password=' + secret
    run = run_receipt(stderr_tail=trace)
    original = copy.deepcopy(run)
    result = D.diagnostics_for_run(run, host_role="host_cron")
    assert result["exception_type"] == "RuntimeError"
    assert result["traceback"]["available"] is True
    assert secret not in json.dumps(result)
    assert "[REDACTED]" in result["traceback"]["text"]
    assert run == original


def test_a_real_python_traceback_on_stdout_is_labelled_as_stdout_evidence():
    run = run_receipt(stdout_tail='Traceback (most recent call last):\nValueError: fixture failure')
    result = D.diagnostics_for_run(run)
    assert result["failure_kind"] == "process_exception"
    assert result["exception_type"] == "ValueError"
    assert result["traceback"]["source"] == "stdout_python_traceback"
    assert "ValueError" in result["failure_reason"]
    assert "stderr_not_retained" in result["gaps"]


def test_an_ordinary_stdout_summary_does_not_become_an_exception():
    result = D.diagnostics_for_run(run_receipt(stdout_tail='{"failed": 2, "message": "Error count"}'))
    assert result["exception_type"] is None
    assert result["traceback"]["available"] is False
    assert result["failure_reason"] == "Failure recorded; stderr diagnostic was not retained"


def test_private_host_identifiers_do_not_escape_the_projection():
    result = D.diagnostics_for_run(run_receipt(), host_role="private-fixture-host")
    assert result["execution"]["host_role"] == "unknown"
    assert result["execution"]["host_identity_status"] == "recorded_privately"
    assert "private-fixture-host" not in json.dumps(result)


def test_duration_can_be_derived_from_explicit_execution_timestamps_and_is_labelled():
    result = D.diagnostics_for_run(run_receipt(duration_s=None))
    assert result["execution"]["duration_s"] == 5
    assert result["execution"]["duration_source"] == "execution_timestamps"


@pytest.mark.parametrize("duration", [True, float("nan"), float("inf"), -5])
def test_invalid_duration_is_not_displayed_as_a_measured_number(duration):
    result = D.diagnostics_for_run(run_receipt(duration_s=duration, started_at=None, finished_at=None))
    assert result["execution"]["duration_s"] is None
    assert "duration_not_retained" in result["gaps"]


def test_naive_last_success_is_unknown_rather_than_guessing_a_timezone():
    result = D.diagnostics_for_run(run_receipt(), last_success="2026-11-02T12:00:00")
    assert result["last_success_at"] is None
    assert "last_success_not_measured" in result["gaps"]


def test_mismatched_embedded_receipt_is_not_attached_to_this_run():
    run = run_receipt(stderr_tail="RuntimeError: another run")
    run["receipt"]["run_id"] = "other-run"
    result = D.diagnostics_for_run(run)
    assert result["exception_type"] is None
    assert "receipt_identity_mismatch" in result["gaps"]


def test_json_receipts_and_invalid_json_have_deterministic_results():
    run = run_receipt()
    run["receipt_json"] = json.dumps(run.pop("receipt"))
    assert D.diagnostics_for_run(run)["execution"]["exit_code"] == 1
    run["receipt_json"] = "{torn"
    assert "receipt_invalid_json" in D.diagnostics_for_run(run)["gaps"]


def test_projection_does_no_io(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("failure diagnostic projection must be pure")
    monkeypatch.setattr(Path, "open", refused)
    result = D.diagnostics_for_run(run_receipt(), remediation_key="CCOPS-fixture")
    assert result["remediation"]["key"] == "CCOPS-fixture"


def test_contract_subreason_is_redacted_and_stderr_remains_the_primary_cause():
    run = run_receipt(reason="output_unverifiable",
                      output_verdict={"verdict": "unverifiable", "why": "rule_missing password=synthetic-private-value"})
    result = D.diagnostics_for_run(run)
    assert "synthetic-private-value" not in json.dumps(result)
    run["receipt"]["stderr_tail"] = "ValueError: fixture exception"
    assert D.diagnostics_for_run(run)["failure_reason"] == "ValueError: fixture exception"


def test_lock_contention_is_not_described_as_an_unknown_process_failure():
    result = D.diagnostics_for_run(run_receipt(state="RUN_SKIPPED_LOCK", reason="flock_held", exit_code=75))
    assert result["failure_kind"] == "lock_contention"
    assert result["remediation"]["key"] == "execution_lock_contention"
