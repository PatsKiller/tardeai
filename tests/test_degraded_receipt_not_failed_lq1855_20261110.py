"""LQ-20261107-1855: a downgraded subject verdict is not an empty output.

``status_consistency.reconcile`` (LQ-1803, wired into ``lane_last_receipt.build_receipt``) lowers a receipt's
``status`` from ``ok`` to ``degraded`` or ``blocked`` when the lane's own subject verdict is DEGRADED/BLOCK. The
DD07 classifier read that vocabulary as binary (``status != "ok"``), so a monitor that exited 0, produced its
rows and said DEGRADED was graded ``empty_violation`` and the executor stamped it RUN_FAILED ``empty_output`` —
``header-market-freshness-health``, 16:00-18:00 ET on 2026-11-10, breaker after 3 (LQ-20261107-1853).

The rule this file pins: ``ok``/``degraded``/``blocked`` judge against the contract's produced rule; ``failed``
(and any other or missing word) still fails, as ``receipt_status_failed``, never as ``empty_output``. No other
verdict is weakened: a fatal skip, an ``outcome: error`` and a below-minimum count all still fail.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import n8n_run_executor as X
from scripts.lib import lane_last_receipt as LR
from scripts.lib import n8n_output_verdict as V
from scripts.lib import status_consistency as SC

LANE = "fixture-degraded-lane"
RUN = "d:fixture-degraded-lane:live:20261110T2000:a1"
START = datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=30)
CODE = "c" * 40
RULE = {
    "schema": "N8nExpectedOutput@v1", "unit": "contracts", "rule": "min_produced",
    "min_produced": 1, "produced_field": "produced_count", "fatal_skip_reasons": ["no_runner"],
    "evidence": [{"kind": "receipt_field", "ref": "produced_count"}],
}


def _receipt(**change):
    doc = {
        "schema": "LaneRunReceipt@v2", "run_id": RUN, "lane_id": LANE,
        "attempt": 1, "mode": "live", "run_mode": "live", "code_sha": CODE,
        "status": "ok", "produced_count": 2, "attempted_count": 2,
        "skipped_reasons": {}, "started_at": (START + timedelta(seconds=1)).isoformat(),
        "finished_at": (END - timedelta(seconds=1)).isoformat(),
        "ok_at": (END - timedelta(seconds=1)).isoformat(),
        # exactly what the live header monitor wrote under summary
        "summary": {"verdict": "DEGRADED", "vix_stale": True},
    }
    doc.update(change)
    return doc


def _grade(tmp_path, **change):
    """The receipt as the executor grades it: written once, immutably, per attempt."""
    doc = copy.deepcopy(_receipt(**change))
    path = LR.attempt_receipt_path(LANE, RUN, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    receipt = {"run_id": RUN, "lane_id": LANE, "mode": "live", "state": "RUN_DONE", "reason": None,
               "attempt": 1, "code_sha": CODE, "started_at": START.isoformat(), "finished_at": END.isoformat()}
    return X.apply_output_verdict(receipt, {LANE: RULE}, lane_id=LANE, mode="live", state_root=tmp_path,
                                  entry={"output_receipt": "v2"})


@pytest.mark.parametrize("status", ["degraded", "blocked"])
def test_a_downgraded_receipt_that_produced_its_rows_is_not_a_failure(tmp_path, status):
    out = _grade(tmp_path, status=status)
    assert out["state"] == "RUN_DONE", out
    assert out["reason"] is None, out
    assert out["output_verdict"]["verdict"] == "produced", out
    assert out["output_verdict"]["produced_count"] == 2, out


def test_a_degraded_receipt_still_fails_its_own_produced_rule(tmp_path):
    out = _grade(tmp_path, status="degraded", produced_count=0)
    assert out["state"] == "RUN_FAILED", out
    assert out["output_verdict"]["verdict"] == "empty_violation", out
    assert out["output_verdict"]["why"] == "below_min_produced", out


def test_a_degraded_receipt_does_not_excuse_a_fatal_skip(tmp_path):
    out = _grade(tmp_path, status="degraded", skipped_reasons={"no_runner": 1})
    assert out["state"] == "RUN_FAILED", out
    assert out["output_verdict"]["why"] == "fatal_skip", out


def test_a_degraded_status_does_not_excuse_an_error_outcome(tmp_path):
    out = _grade(tmp_path, status="degraded", outcome="error", outcome_reason="dependency_unavailable")
    assert out["state"] == "RUN_FAILED", out
    assert out["output_verdict"]["verdict"] == "empty_violation", out
    assert out["output_verdict"]["why"] == "receipt_outcome_error", out
    # unchanged by this ticket: an outcome error keeps the DD07 word it always had
    assert out["reason"] == "empty_output", out


def test_a_failed_receipt_still_fails_and_no_longer_reads_as_empty_output(tmp_path):
    out = _grade(tmp_path, status="failed")
    assert out["state"] == "RUN_FAILED", out
    assert out["output_verdict"]["verdict"] == "empty_violation", out
    assert out["output_verdict"]["why"] == "receipt_status_failed", out
    assert out["output_verdict"]["status"] == "failed", out
    assert out["reason"] == "receipt_status_failed", out
    assert out["reason"] != "empty_output", out


@pytest.mark.parametrize("status", [None, "", "unknown", "OK", "ok ", "weird", 1])
def test_a_status_outside_the_closed_vocabulary_still_fails(tmp_path, status):
    out = _grade(tmp_path, status=status)
    assert out["state"] == "RUN_FAILED", out
    assert out["output_verdict"]["why"] == "receipt_status_failed", out
    assert out["reason"] == "receipt_status_failed", out


@pytest.mark.parametrize("mangle", [{"status": None}, {"status": "failed"}])
def test_the_receipt_status_branch_fires_before_the_count_rule(tmp_path, mangle):
    """A receipt that cannot say it succeeded never passes on a count it also claims."""
    out = _grade(tmp_path, produced_count=5, attempted_count=5, **mangle)
    assert out["state"] == "RUN_FAILED", out
    assert out["output_verdict"]["why"] == "receipt_status_failed", out


def test_the_non_failing_words_are_the_receipt_writers_own_downgrades():
    """Pinned against status_consistency so a new canonical word cannot silently start failing lanes."""
    written = {SC.OK} | {SC.CANONICAL[SC.WARN], SC.CANONICAL[SC.BLOCKED]}
    assert set(V.NON_FAILING_STATUSES) == written
    assert SC.CANONICAL[SC.FAILED] == "failed"
    assert SC.CANONICAL[SC.FAILED] not in V.NON_FAILING_STATUSES


def test_a_reason_override_never_applies_to_a_passing_verdict(tmp_path, monkeypatch):
    """FAILING_WHY may rename a failure; it may not turn a non-failing verdict into a RUN_FAILED."""
    assert V.FAILING_WHY == {"receipt_status_failed": "receipt_status_failed"}
    assert set(V.FAILING) == {"empty_violation", "unverifiable"}
    monkeypatch.setattr(X, "evaluate_output",
                        lambda *a, **k: {"verdict": "produced", "why": "receipt_status_failed"})
    receipt = {"run_id": RUN, "lane_id": LANE, "mode": "live", "state": "RUN_DONE", "reason": None,
               "attempt": 1, "code_sha": CODE, "started_at": START.isoformat(), "finished_at": END.isoformat()}
    out = X.apply_output_verdict(receipt, {LANE: RULE}, lane_id=LANE, mode="live", state_root=tmp_path,
                                 entry={"output_receipt": "v2"})
    assert out["state"] == "RUN_DONE", out
    assert out["reason"] is None, out
