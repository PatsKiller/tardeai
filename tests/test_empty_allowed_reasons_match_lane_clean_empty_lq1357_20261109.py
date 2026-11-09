"""LQ-20261107-1357 / FINDING 20261109T0255Z: a contract must allow the lane's own clean empty.

Template ``empty_allowed_reasons`` (``nothing_due`` / ``no_new_input``) forbade the literals the scripts
actually emit on a healthy zero-work run. For ``output_receipt: v2`` lanes that becomes
``empty_violation`` → ``RUN_FAILED empty_output`` on the first quiet day.

Pins the three rows named in the finding, the closed enum that accepts those literals, and the
executor's ``n8n_output_verdict.evaluate`` on synthetic LaneRunReceipt@v2 docs (no DB, no host run).
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.check_n8n_workflow_framework import EMPTY_ALLOWED_REASONS
from scripts.lib import n8n_output_verdict as V

ROOT = Path(__file__).resolve().parents[1]

#: lane_id -> clean-empty literals the script emits with status ok (finding §1–§2).
LANE_CLEAN_EMPTY = {
    "reconcile-exit-advisory-outcomes": ("up_to_date", "all_skipped"),
    "build-symbol-profiles-at-0-19": ("no_stale_symbols", "all_skipped"),
    "daily-incubator-refresh": ("no_new_input", "already_refreshed"),
}

#: Template reasons that must NOT be the only allowance for these lanes (they never emit them).
TEMPLATE_ONLY = {
    "reconcile-exit-advisory-outcomes": ("nothing_due", "no_new_input"),
    "build-symbol-profiles-at-0-19": ("nothing_due",),
}


def _contracts() -> dict[str, dict]:
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
    want = set(LANE_CLEAN_EMPTY)
    return {c["id"]: c for c in doc["contracts"] if c.get("id") in want}


def _rule(lane_id: str) -> dict:
    eo = _contracts()[lane_id]["expected_output"]
    # evaluate() takes the expected_output object as ``rule``.
    return eo


def _receipt(lane_id: str, *, empty_reason: str, status: str = "ok", produced: int = 0) -> dict:
    return {
        "schema": "LaneRunReceipt@v2",
        "lane_id": lane_id,
        "run_id": f"test-{lane_id}-{empty_reason}",
        "mode": "live",
        "run_mode": "live",
        "status": status,
        "produced_count": produced,
        "attempted_count": 0 if produced == 0 else produced,
        "skipped_reasons": {},
        "empty_reason": empty_reason,
        "started_at": "2026-11-09T02:00:00Z",
        "finished_at": "2026-11-09T02:00:01Z",
        "ok_at": "2026-11-09T02:00:01Z",
    }


def test_contracts_list_the_lanes_own_clean_empty_literals():
    contracts = _contracts()
    assert set(contracts) == set(LANE_CLEAN_EMPTY)
    for lane_id, reasons in LANE_CLEAN_EMPTY.items():
        allowed = set(contracts[lane_id]["expected_output"]["empty_allowed_reasons"])
        assert set(reasons) <= allowed, (lane_id, reasons, allowed)


def test_enum_admits_the_new_lane_owned_literals():
    for reasons in LANE_CLEAN_EMPTY.values():
        missing = sorted(set(reasons) - EMPTY_ALLOWED_REASONS)
        assert missing == [], missing


def test_evaluate_accepts_each_script_clean_empty():
    for lane_id, reasons in LANE_CLEAN_EMPTY.items():
        rule = _rule(lane_id)
        for reason in reasons:
            doc = _receipt(lane_id, empty_reason=reason)
            out = V.evaluate(rule, doc, run_id=doc["run_id"], lane_id=lane_id, mode="live")
            assert out["verdict"] == "empty_allowed", (lane_id, reason, out)
            assert out["empty_reason"] == reason


def test_template_reasons_that_the_script_never_emits_are_no_longer_required():
    """Regression of the finding: those template literals alone graded the real empties as violations."""
    for lane_id, template in TEMPLATE_ONLY.items():
        rule = dict(_rule(lane_id))
        # Reconstruct the pre-fix allow-list and show the script's own empty would violate.
        rule["empty_allowed_reasons"] = list(template)
        for reason in LANE_CLEAN_EMPTY[lane_id]:
            if reason in template:
                continue
            doc = _receipt(lane_id, empty_reason=reason)
            out = V.evaluate(rule, doc, run_id=doc["run_id"], lane_id=lane_id, mode="live")
            assert out["verdict"] == "empty_violation", (lane_id, reason, out)
            assert out["why"] == "empty_reason_not_allowed"


def test_failed_receipt_still_violates():
    lane_id = "reconcile-exit-advisory-outcomes"
    doc = _receipt(lane_id, empty_reason="dependency_unavailable", status="failed")
    out = V.evaluate(_rule(lane_id), doc, run_id=doc["run_id"], lane_id=lane_id, mode="live")
    assert out["verdict"] == "empty_violation"
    assert out["why"] == "receipt_status_failed"


def test_enforced_lanes_still_carry_output_receipt_v2():
    """The two live traps stay opted in; fixing the contract must not drop enforcement."""
    allow = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
    by = {e["lane_id"]: e for e in allow["lanes"]}
    assert by["build-symbol-profiles-at-0-19"].get("output_receipt") == "v2"
    assert by["daily-incubator-refresh"].get("output_receipt") == "v2"
