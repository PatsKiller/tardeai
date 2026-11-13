"""LQ-20261107-2617: LedgerRunStore.request() answers with the row it INSERTED (state REQUESTED), never a post-commit
re-read. The executor's claim_next can flip the row to RUNNING between COMMIT and the re-read; the relay maps every
gateway state other than REQUESTED to HTTP 403, so a run that was queued (and ran RUN_DONE) read as a refusal
(n8n-incident-fanin executions 192191 / 192249, 2026-11-12). Hermetic."""
from __future__ import annotations

import threading

from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

KW = dict(lane_id="lane-a", mode="live", requested_by="n8n:workflow:w1", caller_id="n8n-relay")


class _RaceConn:
    """Delegates to the real sqlite connection; right after the INSERT's COMMIT the executor claims the row."""

    def __init__(self, real, on_commit):
        self._real, self._on_commit = real, on_commit

    def execute(self, sql, *a, **k):
        out = self._real.execute(sql, *a, **k)
        if str(sql).strip().upper() == "COMMIT":
            self._on_commit()
        return out

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_request_returns_requested_even_if_the_executor_claims_it_right_after_commit(tmp_path):
    path = tmp_path / "l.sqlite"
    ledger = CoordinationLedger(path)
    store = LedgerRunStore(ledger)
    executor = LedgerRunStore(CoordinationLedger(path))
    claimed = []
    ledger._conn = _RaceConn(ledger._conn, lambda: claimed.append(executor.claim_next(now=1000.0)))
    row, dup = store.request(run_id="n8n-wf-w1-1", now=1000.0, **KW)
    assert claimed and claimed[0]["state"] == "RUNNING"        # the executor really won the race
    assert dup is False
    assert row["state"] == "REQUESTED"                          # what was written, not what it became since


def test_request_row_carries_the_inserted_fields(tmp_path):
    store = LedgerRunStore(CoordinationLedger(tmp_path / "l.sqlite"))
    row, dup = store.request(run_id="n8n-wf-w1-2", now=1000.0, slot_key="s", attempt=1, klass="report", priority=3, **KW)
    assert dup is False
    assert (row["run_id"], row["lane_id"], row["mode"], row["state"]) == ("n8n-wf-w1-2", "lane-a", "live", "REQUESTED")
    assert row["requested_by"] == "n8n:workflow:w1" and row["caller_id"] == "n8n-relay"
    assert row["slot_key"] == "s" and row["attempt"] == 1 and row["class"] == "report" and row["priority"] == 3


def test_duplicate_still_returns_the_existing_row_in_its_current_state(tmp_path):
    path = tmp_path / "l.sqlite"
    store = LedgerRunStore(CoordinationLedger(path))
    store.request(run_id="n8n-wf-w1-3", now=1000.0, **KW)
    LedgerRunStore(CoordinationLedger(path)).claim_next(now=1001.0)
    row, dup = store.request(run_id="n8n-wf-w1-3", now=1002.0, **KW)
    assert dup is True and row["state"] == "RUNNING"


def test_concurrent_claimer_never_makes_a_fresh_request_read_back_running(tmp_path):
    path = tmp_path / "l.sqlite"
    store = LedgerRunStore(CoordinationLedger(path))
    stop = threading.Event()

    def claimer():
        ex = LedgerRunStore(CoordinationLedger(path))
        while not stop.is_set():
            ex.claim_next(now=2000.0)

    t = threading.Thread(target=claimer, daemon=True)
    t.start()
    try:
        states = [store.request(run_id=f"n8n-wf-w1-{i}", now=1000.0 + i, **KW)[0]["state"] for i in range(100, 220)]
    finally:
        stop.set()
        t.join(5)
    assert set(states) == {"REQUESTED"}
