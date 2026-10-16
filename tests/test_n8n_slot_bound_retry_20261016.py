"""Slot-bound live retry for the n8n self-healing tier (operator-approved #1819 follow-up 1, 2026-10-16).

``rerun_live_once`` carries ``parent_run_id`` (the FAILED ``d:``/``e:`` run) through ``host_run_request``. The gateway
validates the parent before queueing, and the executor derives the effect slot from the parent, so the retry claims
the SAME ``fx:<process>:<slot>:<ver>`` key. The effect ledger then decides: a FAILED pre-effect claim is re-claimed
(attempt + 1), while DONE, CLAIMED, UNKNOWN or an unproven FAILED is refused (``effect_already_claimed``). The result
is one effect per slot.

Pins: the duplicate refusal (parent slot DONE), a parent that is not FAILED, a parent from another lane, a missing
parent, a non-slot parent, the happy re-claim, and the executor refusing a parent that names another lane.
Hermetic: tmp sqlite ledger, no spawn, no network.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import n8n_run_executor as X
from scripts.lib import effect_claim as E
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc).timestamp()
LANE, OTHER, PROCESS, SLOT = "fake-lane", "other-lane", "fake-process", "20261016T0815"
PARENT = f"d:{LANE}:live:{SLOT}"
RETRY = "rem-siem7-abcdef012345-live"
KEY = E.effect_key(PROCESS, SLOT, "v1")


@pytest.fixture
def led(tmp_path: Path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    fx = E.EffectClaimStore(ledger)
    fx.set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0)
    yield ledger, LedgerRunStore(ledger), fx
    ledger.close()


def _finished(runs, run_id, lane=LANE, state="RUN_FAILED", mode="live"):
    runs.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="n8n", caller_id="n8n-relay", now=T0 + 10)
    runs.claim_next(now=T0 + 11)
    runs.finish(run_id, state=state, now=T0 + 12, receipt={"schema": "RunReceipt@v1", "state": state})


def _req(runs, parent, lane=LANE):
    return G.host_run_request(lane_id=lane, mode="live", run_id=RETRY, requested_by="host:n8n-failure-diagnosis",
                              caller_id="n8n-failure-diagnosis", run_store=runs,
                              run_allowlist=frozenset({LANE, OTHER}), now=T0 + 100, parent_run_id=parent)


def _gate(fx):
    return X.EffectGate(fx, {LANE: {"process": PROCESS, "input_version": "v1"}}, clock=lambda: T0 + 200)


# ---------------------------------------------------------------- gateway validation


def test_missing_parent_is_refused(led):
    _, runs, _ = led
    out = _req(runs, PARENT)
    assert out["state"] == "REFUSED" and out["retry_parent_state"] == "retry_parent_missing"
    assert runs.get(RETRY) is None


def test_parent_not_failed_is_refused(led):
    _, runs, _ = led
    _finished(runs, PARENT, state="RUN_DONE")
    out = _req(runs, PARENT)
    assert out["state"] == "REFUSED" and out["retry_parent_state"] == "retry_parent_not_failed"


def test_parent_from_another_lane_is_refused(led):
    _, runs, _ = led
    other_parent = f"d:{OTHER}:live:{SLOT}"
    _finished(runs, other_parent, lane=OTHER)
    out = _req(runs, other_parent)
    assert out["state"] == "REFUSED" and out["retry_parent_state"] == "retry_parent_lane_mismatch"


def test_free_form_or_dry_parent_is_refused(led):
    _, runs, _ = led
    assert _req(runs, "n8n-wf-abc-42")["retry_parent_state"] == "retry_parent_not_slot_key"
    dry = f"d:{LANE}:dry_run:{SLOT}"
    _finished(runs, dry, mode="dry_run")
    assert _req(runs, dry)["retry_parent_state"] == "retry_parent_mode_mismatch"


def test_valid_parent_is_queued_with_parent_run_id(led):
    _, runs, _ = led
    _finished(runs, PARENT)
    out = _req(runs, PARENT)
    assert out["state"] != "REFUSED"
    assert runs.get(RETRY)["parent_run_id"] == PARENT


def test_without_parent_host_run_request_is_unchanged(led):
    _, runs, _ = led
    out = G.host_run_request(lane_id=LANE, mode="dry_run", run_id="rem-siem7-abcdef012345-dry_run",
                             requested_by="h", caller_id="c", run_store=runs, run_allowlist=frozenset({LANE}),
                             now=T0 + 100)
    assert out["state"] != "REFUSED" and runs.get("rem-siem7-abcdef012345-dry_run")["parent_run_id"] is None


# ---------------------------------------------------------------- executor: one effect per slot


def _retry_row(runs):
    _finished(runs, PARENT)
    assert _req(runs, PARENT)["state"] != "REFUSED"
    return runs.get(RETRY)


def test_retry_reclaims_a_failed_pre_effect_slot_at_attempt_two(led):
    _, runs, fx = led
    assert fx.claim(KEY, scheduler="n8n", now=T0 + 11, run_id=PARENT, admitted_at=T0 + 10).ok
    fx.finish(KEY, state=E.STATE_FAILED, now=T0 + 12, run_id=PARENT, pre_effect=True)
    block, refusal = _gate(fx).begin(_retry_row(runs), LANE, "live")
    assert refusal is None and block["key"] == KEY and block["slot"] == SLOT and block["attempt"] == 2


def test_retry_of_a_done_slot_is_refused_as_duplicate(led):
    _, runs, fx = led
    assert fx.claim(KEY, scheduler="n8n", now=T0 + 11, run_id=PARENT, admitted_at=T0 + 10).ok
    fx.finish(KEY, state=E.STATE_DONE, now=T0 + 12, run_id=PARENT)
    block, refusal = _gate(fx).begin(_retry_row(runs), LANE, "live")
    assert refusal == "effect:effect_already_claimed" and block["holder"]["state"] == "DONE"


def test_retry_of_an_unproven_failure_is_refused(led):
    _, runs, fx = led
    assert fx.claim(KEY, scheduler="n8n", now=T0 + 11, run_id=PARENT, admitted_at=T0 + 10).ok
    fx.finish(KEY, state=E.STATE_FAILED, now=T0 + 12, run_id=PARENT, pre_effect=False)
    _, refusal = _gate(fx).begin(_retry_row(runs), LANE, "live")
    assert refusal == "effect:effect_already_claimed"


def test_second_retry_of_the_same_slot_is_refused(led):
    _, runs, fx = led
    assert fx.claim(KEY, scheduler="n8n", now=T0 + 11, run_id=PARENT, admitted_at=T0 + 10).ok
    fx.finish(KEY, state=E.STATE_FAILED, now=T0 + 12, run_id=PARENT, pre_effect=True)
    row = _retry_row(runs)
    assert _gate(fx).begin(row, LANE, "live")[1] is None          # first retry holds the key (CLAIMED)
    twin = {**row, "run_id": "rem-siem8-abcdef012345-live"}
    assert _gate(fx).begin(twin, LANE, "live")[1] == "effect:effect_already_claimed"


def test_executor_refuses_a_parent_naming_another_lane(led):
    _, _, fx = led
    row = {"run_id": RETRY, "lane_id": LANE, "mode": "live", "requested_at": "2026-10-16T12:01:40+00:00",
           "parent_run_id": f"d:{OTHER}:live:{SLOT}"}
    _, refusal = _gate(fx).begin(row, LANE, "live")
    assert refusal == "effect:effect_retry_parent_invalid"


def test_a_model_choosing_rerun_live_once_never_executes_it():
    from scripts.lib import n8n_failure_diagnosis as D
    from scripts.lib import n8n_self_heal as H

    assert D.LIVE_HEAL_ACTION_ID == H.LIVE_HEAL_ACTION
    entry = {"severity": "Low", "actions": [{"action_id": "rerun_live_once", "auto": True, "max_per_lane_per_day": 1,
                                              "handler": "ledger_request_run", "mode_sequence": ["live"]}]}
    verdict = {"action_id": "rerun_live_once", "confidence": 0.99, "grounded": True, "problems": []}
    dec = D.decide(verdict, entry, lane_remediations_today=0, lane_recent_remediation=False)
    assert dec["kind"] == "escalate" and dec["reason"] == "live_heal_not_model_selectable"


def test_executor_without_parent_still_fails_closed(led):
    _, _, fx = led
    row = {"run_id": RETRY, "lane_id": LANE, "mode": "live", "requested_at": "2026-10-16T12:01:40+00:00"}
    assert _gate(fx).begin(row, LANE, "live")[1] == "effect:effect_slot_unknown"
