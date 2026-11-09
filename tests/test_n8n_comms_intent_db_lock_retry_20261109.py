"""LQ-20261107-1383 — a ledger write lock must be retryable, not terminal on attempt 1.

``n8n-comms-intent-consumer`` was classified ``DEGRADED`` (db_integrity slice 2220) with 12 unreleased
dead letters, every one of them ``attempts 1``, ``last_reason exit_1``, ``verdict terminal``,
``max_attempts 3``, ``policy transient-2``. Each failing run lasted 5.6–8.4 s and its stdout tail
carried ``OperationalError: database is locked``: the coordination ledger has one writer at a time and
the shared ``connect_rw`` busy timeout is 5 s, so a sibling lane's write inside the same :15/:45
executor burst failed the slot. The executor then stored the bare reason ``exit_1``, and
``transient-2`` retries exit codes 69/75/111 or a matching reason pattern — not 1 — so the failure was
``terminal`` on attempt 1 of 3 and went straight to the dead-letter queue.

The wait half (30 s on this lane's own connection) is LQ-816. **This suite pins the classification
half without touching ``scripts/lib/n8n_retry_policy.py``**, which is held by another live claim: the
executor config types the reason (``DB_LOCK:``) and the lane's own policy retries it. Both files are
read as the release reads them, so a config regression fails here.

Hermetic: no live ledger, no receipt from the runtime directory, no send, no broker; the incident text
is reproduced literally from ``d:n8n-comms-intent-consumer:live:20261108T0545``.

COVERS = ["config/n8n_executor.json", "config/n8n_retry_policies.json", "scripts/lib/n8n_retry_policy.py"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import n8n_retry_policy as rp  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

LANE = "n8n-comms-intent-consumer"
EXECUTOR_CONFIG = ROOT / "config" / "n8n_executor.json"
POLICY_FILE = ROOT / "config" / "n8n_retry_policies.json"
REGISTRY = ROOT / "config" / "lane_registry.json"
#: The incident's stdout tail, verbatim from the 2026-11-08 05:45 ET receipt (426 bytes, abridged after "error").
INCIDENT_STDOUT = json.dumps(
    {
        "mode": "apply",
        "ok": False,
        "receipt": "/placeholder/n8n-comms-intent-consumer_last.json",
        "produced_count": 0,
        "empty_reason": None,
        "done": None,
        "refused": None,
        "failed_transient": None,
        "incidents_created": None,
        "incidents_updated": None,
        "refreshed": None,
        "closed": None,
        "held_undelivered": None,
        "deferred": None,
        "error": "OperationalError: database is locked",
    }
)
FINISHED_AT = datetime(2026, 11, 8, 10, 45, 16, tzinfo=timezone.utc)


def _lane_policy() -> tuple[rp.RetryPolicy, str]:
    """The policy this lane actually dispatches under, from the registry (not assumed)."""
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["lanes"]
    name = {r["lane_id"]: r for r in rows}[LANE]["dispatch"]["retry_policy"]
    return rp.load_policies(POLICY_FILE).policies[name], name


def _incident_receipt() -> dict:
    """The failed receipt's shape as the executor stores it before typing."""
    return {"state": "RUN_FAILED", "exit_code": 1, "reason": "exit_1", "stdout_tail": INCIDENT_STDOUT,
            "stderr_tail": None, "finished_at": FINISHED_AT.isoformat(), "duration_s": 5.91}


# --- the typing half, read from the release's own config ---------------------------------------


def test_the_executor_config_carries_the_db_lock_marker() -> None:
    cfg = X.load_executor_config(EXECUTOR_CONFIG)
    markers = cfg["typed_reason_markers"]
    assert "DB_LOCK" in markers, "the config replaces the code default; without the key the lane is exit_1 again"
    assert markers["COST_CAP"] == r"(?i)cost_cap|skipped_budget", "the existing markers are untouched"
    assert markers["PEAK_SKIP"] == r"(?i)peak_skip"


def test_the_incident_stdout_tail_is_typed_db_lock() -> None:
    markers = X.load_executor_config(EXECUTOR_CONFIG)["typed_reason_markers"]
    assert X.typed_reason(_incident_receipt(), markers) == "DB_LOCK:exit_1"


def test_typing_does_not_touch_a_finished_run_or_an_unmarked_failure() -> None:
    markers = X.load_executor_config(EXECUTOR_CONFIG)["typed_reason_markers"]
    done = {**_incident_receipt(), "state": "RUN_DONE", "reason": None}
    assert X.typed_reason(done, markers) is None
    other = {**_incident_receipt(), "stdout_tail": '{"error": "OperationalError: no such table"}'}
    assert X.typed_reason(other, markers) == "exit_1", "only a lock acquires the type"


# --- the classification half, on the lane's own policy -----------------------------------------


def test_the_lane_still_runs_the_two_retry_policy() -> None:
    policy, name = _lane_policy()
    assert name == "transient-2" and policy.max_attempts == 3, "the incident's policy and budget"


def test_the_typed_lock_reason_is_retryable_where_the_raw_one_is_not() -> None:
    """The type is load-bearing: the policy retries ``DB_LOCK:exit_1``, not the message or the bare exit code."""
    policy, _ = _lane_policy()
    assert rp.verdict("RUN_FAILED", 1, "DB_LOCK:exit_1", policy) == rp.VERDICT_RETRYABLE
    assert rp.verdict("RUN_FAILED", 1, "exit_1", policy) == rp.VERDICT_TERMINAL
    assert rp.verdict("RUN_FAILED", 1, "OperationalError: database is locked", policy) == rp.VERDICT_TERMINAL


def test_the_class_rails_still_hold_over_the_typed_reason() -> None:
    """A retryable reason never overrides the class rails: send/learn stay single-attempt."""
    policy, _ = _lane_policy()
    assert rp.class_verdict("RUN_FAILED", 1, "DB_LOCK:exit_1", policy, "monitor") == rp.VERDICT_RETRYABLE
    assert rp.class_verdict("RUN_FAILED", 1, "DB_LOCK:exit_1", policy, "send") == rp.VERDICT_TERMINAL
    assert rp.class_verdict("RUN_FAILED", 1, "DB_LOCK:exit_1", policy, "learn") == rp.VERDICT_TERMINAL


def test_the_retry_contract_schedules_the_second_attempt() -> None:
    policy, _ = _lane_policy()
    row = {"run_id": f"d:{LANE}:live:20261108T0545", "slot_key": f"d:{LANE}:live:20261108T0545",
           "lane_id": LANE, "mode": "live", "attempt": 1}
    receipt = {**_incident_receipt(), "reason": "DB_LOCK:exit_1"}
    v = rp.class_verdict("RUN_FAILED", 1, receipt["reason"], policy, "monitor")
    contract = X.retry_contract(row, receipt, v, policy=policy, klass="monitor", code_root=ROOT)
    assert contract["retryable"] is True and contract["verdict"] == "retryable"
    assert (contract["attempt"], contract["max_attempts"], contract["attempts_remaining"]) == (1, 3, 2)
    assert contract["terminal_reason"] is None and contract["dlq_ref"] is None
    assert contract["next_attempt_at"] == (FINISHED_AT + timedelta(seconds=policy.backoff_s[0])).isoformat()


def test_finalize_outcome_does_not_dead_letter_attempt_one(tmp_path: Path) -> None:
    """The incident's exact row: attempt 1 of 3, RUN_FAILED exit 1, typed lock reason → no dead letter."""
    policy, _ = _lane_policy()
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    try:
        store = LedgerRunStore(ledger)
        slot = f"d:{LANE}:live:20261108T0545"
        t0 = FINISHED_AT.timestamp() - 10
        store.request(run_id=slot, lane_id=LANE, mode="live", requested_by="n8n", caller_id="n8n-relay",
                      now=t0, slot_key=slot, attempt=1, klass="monitor", priority=5)
        assert store.claim_next(now=t0 + 1)["run_id"] == slot
        row = store.finish(slot, state="RUN_FAILED", now=t0 + 7,
                           receipt={**_incident_receipt(), "reason": "DB_LOCK:exit_1"})
        out = rp.finalize_outcome(store, row, policy, breaker_threshold=3, now=t0 + 8, klass="monitor")
        assert out.verdict == rp.VERDICT_RETRYABLE
        assert out.dead_letter is None, "attempt 1 of 3 must not reach the dead-letter queue"
        assert out.findings == []
        assert store.get(slot)["verdict"] == "retryable"
        assert store.list_dead_letters() == [], "no dead letter row for a retryable first attempt"
    finally:
        ledger.close()


def test_the_opposite_is_still_true_for_a_bare_failure(tmp_path: Path) -> None:
    """Control: without the type the same row dead-letters on attempt 1 — the defect this fix removes."""
    policy, _ = _lane_policy()
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    try:
        store = LedgerRunStore(ledger)
        slot = f"d:{LANE}:live:20261108T0545"
        t0 = FINISHED_AT.timestamp() - 10
        store.request(run_id=slot, lane_id=LANE, mode="live", requested_by="n8n", caller_id="n8n-relay",
                      now=t0, slot_key=slot, attempt=1, klass="monitor", priority=5)
        assert store.claim_next(now=t0 + 1)["run_id"] == slot
        row = store.finish(slot, state="RUN_FAILED", now=t0 + 7, receipt=_incident_receipt())
        out = rp.finalize_outcome(store, row, policy, breaker_threshold=3, now=t0 + 8, klass="monitor")
        assert out.verdict == rp.VERDICT_TERMINAL
        assert out.dead_letter is not None and out.dead_letter["attempts"] == 1
    finally:
        ledger.close()
