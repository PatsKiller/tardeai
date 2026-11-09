"""ANCHOR: LQ1537_CIO_ACTION_WRITE_ONCE_20261109. LQ-20261107-1537 / defect #110.

``cio_run_worker._write_actions`` used to call ``run_store.transition(..., ACTION_WRITE)``
inside the per-recommendation loop. The first rec moved CIO_SYNTHESIS → ACTION_WRITE;
every later rec tried ACTION_WRITE → ACTION_WRITE (invalid), logged
``Action write failed for rec N: Invalid transition: ACTION_WRITE -> ACTION_WRITE``,
and re-scanned ``cio_runs.jsonl`` (~2 s each). Transition once after the batch.
"""
from __future__ import annotations

import logging

import pytest

from scripts.lib.cio_action_ledger import CIOActionLedger
from scripts.lib.cio_run import CIORunStore
from scripts.lib.cio_run_worker import CIORunWorker


def _run_at_synthesis(store: CIORunStore) -> str:
    created = store.create_run(trigger_type="MANUAL", trigger_ref="lq1537", actor="test")
    run_id = created["payload"]["run_id"]
    store.transition(run_id, "HEALTH_CHECK", actor="test")
    store.transition(run_id, "EVIDENCE_BUILD", actor="test")
    store.transition(run_id, "CIO_SYNTHESIS", actor="test")
    assert store.get_run(run_id)["status"] == "CIO_SYNTHESIS"
    return run_id


def test_multi_rec_action_write_transitions_once_and_does_not_log_self_transition(
    tmp_path, caplog,
):
    store = CIORunStore(str(tmp_path / "cio_runs.jsonl"))
    run_id = _run_at_synthesis(store)
    ledger = CIOActionLedger(str(tmp_path / "cio_actions.jsonl"))
    worker = CIORunWorker(
        run_store=store,
        action_ledger=ledger,
        notification_outbox=None,
        mode="shadow",
    )
    worker._run_id = run_id
    worker._snapshot_result = {
        "domain_states": {
            "portfolio": "OK",
            "risk": "OK",
            "account_constraints": "OK",
        }
    }

    recs = [
        {"title": f"Hold name {i}", "action": "HOLD", "rationale": f"r{i}"}
        for i in range(5)
    ]
    synthesis = {"result": {"recommendations": recs, "summary": "batch"}}

    with caplog.at_level(logging.WARNING, logger="tradeai.cio_run_worker"):
        out = worker._write_actions(synthesis)

    assert len(out["action_ids"]) == 5, out
    assert len(out["blocked_recommendations"]) == 0, out
    run = store.get_run(run_id)
    assert run["status"] == "ACTION_WRITE"
    assert run["created_action_ids"] == out["action_ids"]

    spam = [r for r in caplog.records if "ACTION_WRITE -> ACTION_WRITE" in r.getMessage()]
    assert spam == [], [r.getMessage() for r in spam]
    failed = [r for r in caplog.records if "Action write failed" in r.getMessage()]
    assert failed == [], [r.getMessage() for r in failed]

    # Exactly one CIO_RUN_ACTION_CREATED event for the batch (plus prior lifecycle events).
    action_created = [
        line for line in (tmp_path / "cio_runs.jsonl").read_text(encoding="utf-8").splitlines()
        if '"CIO_RUN_ACTION_CREATED"' in line or '"event_type": "CIO_RUN_ACTION_CREATED"' in line
        or "CIO_RUN_ACTION_CREATED" in line
    ]
    assert len(action_created) == 1, action_created


def test_fail_before_shape_still_writes_all_actions_when_transition_spammed(tmp_path, monkeypatch):
    """Document the pre-fix loop: N transitions for N recs → N-1 invalid self-transitions."""
    store = CIORunStore(str(tmp_path / "cio_runs.jsonl"))
    run_id = _run_at_synthesis(store)
    ledger = CIOActionLedger(str(tmp_path / "cio_actions.jsonl"))
    worker = CIORunWorker(
        run_store=store,
        action_ledger=ledger,
        notification_outbox=None,
        mode="shadow",
    )
    worker._run_id = run_id
    worker._snapshot_result = {
        "domain_states": {"portfolio": "OK", "risk": "OK", "account_constraints": "OK"}
    }

    calls: list[str] = []
    real = store.transition

    def counting(run_id_arg, to_status, **kwargs):
        calls.append(to_status)
        return real(run_id_arg, to_status, **kwargs)

    monkeypatch.setattr(store, "transition", counting)
    recs = [{"title": f"Hold {i}", "action": "HOLD"} for i in range(3)]
    out = worker._write_actions({"result": {"recommendations": recs}})
    assert len(out["action_ids"]) == 3
    assert calls.count("ACTION_WRITE") == 1, calls
