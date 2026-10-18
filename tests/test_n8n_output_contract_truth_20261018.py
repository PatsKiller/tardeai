"""Output proof fails closed on unavailable contracts and mismatched attempt evidence.

Real executor post-spawn validator and immutable receipt paths; fake external work only.
The baseline failures are the expected business assertions, never harness failures.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import n8n_run_executor as X
from scripts.lib import lane_last_receipt as LR

LANE = "fixture-output-lane"
RUN = "d:fixture-output-lane:live:20261018T1200:a2"
START = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=30)
CODE = "a" * 40
RULE = {
    "schema": "N8nExpectedOutput@v1", "unit": "rows", "rule": "min_produced",
    "min_produced": 1, "produced_field": "produced_count", "fatal_skip_reasons": ["no_runner"],
    "evidence": [{"kind": "receipt_field", "ref": "produced_count"}],
}


def _receipt():
    return {
        "schema": "LaneRunReceipt@v2", "run_id": RUN, "lane_id": LANE,
        "attempt": 2, "mode": "live", "run_mode": "live", "code_sha": CODE,
        "status": "ok", "produced_count": 1, "attempted_count": 1,
        "skipped_reasons": {}, "started_at": (START + timedelta(seconds=1)).isoformat(),
        "finished_at": (END - timedelta(seconds=1)).isoformat(),
        "ok_at": (END - timedelta(seconds=1)).isoformat(),
    }


def _apply(tmp_path, *, doc=None, outputs=None, opted_in=True, mode="live", executor_change=None):
    doc = copy.deepcopy(_receipt() if doc is None else doc)
    path = LR.attempt_receipt_path(LANE, RUN, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    receipt = {"run_id": RUN, "lane_id": LANE, "mode": mode, "state": "RUN_DONE", "reason": None,
               "attempt": 2, "code_sha": CODE, "started_at": START.isoformat(), "finished_at": END.isoformat()}
    receipt.update(executor_change or {})
    return X.apply_output_verdict(receipt, {LANE: RULE} if outputs is None else outputs,
                                  lane_id=LANE, mode=mode, state_root=tmp_path,
                                  entry={"output_receipt": "v2"} if opted_in else {})


def test_executor_unavailable_output_contract_cannot_remain_done(tmp_path):
    out = _apply(tmp_path, outputs=lambda: None)
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "output_unverifiable", out


def test_opted_in_live_lane_requires_its_output_rule(tmp_path):
    out = _apply(tmp_path, outputs={})
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "output_unverifiable", out


@pytest.mark.parametrize("change", [{"attempt": None}, {"attempt": True}, {"started_at": None}, {"finished_at": None}])
def test_executor_unknown_attempt_context_cannot_establish_output(tmp_path, change):
    out = _apply(tmp_path, executor_change=change)
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "output_unverifiable", out


@pytest.mark.parametrize("unknown", [None, "", "not-a-full-version", "A" * 40, "a" * 39, "g" * 40])
def test_live_output_needs_full_lowercase_served_code_sha(tmp_path, unknown):
    out = _apply(tmp_path, doc={**_receipt(), "code_sha": unknown}, executor_change={"code_sha": unknown})
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "output_unverifiable", out
    assert out["output_verdict"]["why"] == "executor_code_sha_invalid", out


def test_release_identity_loader_has_no_unknown_or_git_fallback(tmp_path):
    assert X._code_sha(tmp_path) is None
    (tmp_path / "GIT_SHA").write_text("not-a-served-release")
    assert X._code_sha(tmp_path) is None
    (tmp_path / "GIT_SHA").write_text(CODE + "\n")
    assert X._code_sha(tmp_path) == CODE


@pytest.mark.parametrize("change", [
    {"mode": "dry_run"}, {"run_mode": "dry_run"}, {"attempt": 1}, {"attempt": True},
    {"attempt": None}, {"lane_id": "another-lane"}, {"run_id": "another-run"}, {"code_sha": "b" * 40},
])
def test_executor_refuses_receipt_outside_exact_attempt_identity(tmp_path, change):
    out = _apply(tmp_path, doc={**_receipt(), **change})
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "output_unverifiable", out


@pytest.mark.parametrize("change", [
    {"finished_at": (START - timedelta(days=1)).isoformat()},
    {"ok_at": (START - timedelta(days=1)).isoformat()},
    {"finished_at": (END + timedelta(seconds=1)).isoformat()},
    {"ok_at": (END + timedelta(seconds=1)).isoformat()},
    {"started_at": (START - timedelta(seconds=1)).isoformat()},
    {"finished_at": "not-a-time"}, {"finished_at": "2026-10-18T16:00:10"},
    {"finished_at": None}, {"ok_at": None},
])
def test_executor_refuses_stale_future_or_invalid_output_time(tmp_path, change):
    out = _apply(tmp_path, doc={**_receipt(), **change})
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "output_unverifiable", out


@pytest.mark.parametrize("skip", ["no_runner", "skipped_lock"])
def test_shared_output_verdict_fatal_skip_does_not_pass_positive_count(tmp_path, skip):
    out = _apply(tmp_path, doc={**_receipt(), "attempted_count": 2, "skipped_reasons": {skip: 1}})
    assert out["state"] == "RUN_FAILED", out
    assert out["reason"] == "empty_output", out


def test_valid_fresh_same_attempt_output_passes(tmp_path):
    out = _apply(tmp_path)
    assert out["state"] == "RUN_DONE", out
    assert out["output_verdict"]["verdict"] == "produced", out


def test_explicit_allowed_empty_work_passes_with_bound_receipt(tmp_path):
    rule = {**RULE, "rule": "empty_allowed", "empty_allowed_reasons": ["no_new_items"]}
    doc = {**_receipt(), "produced_count": 0, "attempted_count": 0, "empty_reason": "no_new_items"}
    out = _apply(tmp_path, doc=doc, outputs={LANE: rule})
    assert out["state"] == "RUN_DONE", out
    assert out["output_verdict"]["verdict"] == "empty_allowed", out


@pytest.mark.parametrize("mode,opted_in", [("dry_run", True), ("live", False)])
def test_unavailable_rules_do_not_change_non_applicable_work(tmp_path, mode, opted_in):
    out = _apply(tmp_path, outputs=lambda: None, mode=mode, opted_in=opted_in)
    assert out["state"] == "RUN_DONE", out


def test_non_migrated_lane_without_rule_stays_explicit_no_rule(tmp_path):
    out = _apply(tmp_path, outputs={}, opted_in=False)
    assert out["state"] == "RUN_DONE" and out["output_verdict"] == {"verdict": "no_rule"}
