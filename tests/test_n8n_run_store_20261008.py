"""Ledger `runs` table (n8n scheduler-of-record tranche N1, 2026-10-08): request / claim_next / finish / list.

claim_next moves the OLDEST REQUESTED row to RUNNING in one transaction, so a second store on the same file
can never claim the same row; finish stores the RunReceipt@v1 and is legal only from RUNNING. Hermetic."""

from __future__ import annotations

import time

import pytest

from scripts.lib import n8n_coordination_ledger as L
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerError, LedgerRunStore

T0 = 1_791_000_000.0  # fixed epoch; the clock is injected everywhere


def _receipt(run_id: str, *, state: str, exit_code: int | None = 0, duration: float = 1.5) -> dict:
    return {
        "schema": "RunReceipt@v1",
        "run_id": run_id,
        "state": state,
        "exit_code": exit_code,
        "duration_s": duration,
        "finished_at": "2026-10-08T14:00:05+00:00",
    }


def test_migration_adds_runs_table_to_an_existing_ledger_file(tmp_path):
    path = tmp_path / "old.sqlite"
    ledger = CoordinationLedger(path)
    ledger._conn.execute("DROP TABLE runs")  # a ledger created before 2026-10-08
    ledger.close()
    again = CoordinationLedger(path)  # the gateway restarted on the new code
    cols = {r["name"] for r in again._conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert cols == {
        "run_id",
        "lane_id",
        "mode",
        "state",
        "requested_by",
        "caller_id",
        "requested_at",
        "started_at",
        "finished_at",
        "exit_code",
        "duration_s",
        "receipt_json",
    }
    assert again._conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0  # older tables untouched
    again.close()


def test_request_is_idempotent_and_claim_next_takes_the_oldest_once(tmp_path):
    ledger = CoordinationLedger(tmp_path / "l.sqlite")
    store = LedgerRunStore(ledger)
    row, dup = store.request(
        run_id="run-0000000000-b",
        lane_id="maturity-remeasure",
        mode="dry_run",
        requested_by=None,
        caller_id="n8n-relay",
        now=T0 + 10,
    )
    assert dup is False and row["state"] == "REQUESTED" and row["receipt"] is None and row["started_at"] is None
    older, dup = store.request(
        run_id="run-0000000000-a",
        lane_id="n8n-lab-watchdog",
        mode="live",
        requested_by="wf",
        caller_id="n8n-relay",
        now=T0,
    )
    assert dup is False
    same, dup = store.request(
        run_id="run-0000000000-b", lane_id="other", mode="live", requested_by=None, caller_id="x", now=T0 + 99
    )
    assert dup is True and same["lane_id"] == "maturity-remeasure" and same["mode"] == "dry_run"
    assert len(store.list(state="REQUESTED")) == 2
    claimed = store.claim_next(now=T0 + 20)
    assert claimed["run_id"] == "run-0000000000-a" and claimed["state"] == "RUNNING"
    assert claimed["started_at"].startswith("2026-10-")
    second = LedgerRunStore(CoordinationLedger(tmp_path / "l.sqlite"))  # a second executor on the same file
    assert second.claim_next(now=T0 + 21)["run_id"] == "run-0000000000-b"
    assert second.claim_next(now=T0 + 22) is None and store.claim_next(now=T0 + 23) is None
    assert store.list(state="RUNNING")[0]["run_id"] == "run-0000000000-b"  # newest requested first
    second._l.close()
    ledger.close()


def test_finish_requires_running_and_a_finished_state_and_keeps_the_receipt(tmp_path):
    ledger = CoordinationLedger(tmp_path / "f.sqlite")
    store = LedgerRunStore(ledger)
    store.request(
        run_id="run-0000000000-c",
        lane_id="n8n-lab-watchdog",
        mode="dry_run",
        requested_by=None,
        caller_id="n8n-relay",
        now=T0,
    )
    with pytest.raises(LedgerError, match="illegal_transition:REQUESTED->RUN_DONE"):
        store.finish("run-0000000000-c", state="RUN_DONE", receipt=_receipt("run-0000000000-c", state="RUN_DONE"))
    store.claim_next(now=T0 + 1)
    with pytest.raises(LedgerError, match="illegal_transition"):
        store.finish("run-0000000000-c", state="REQUESTED", receipt={})
    with pytest.raises(LedgerError, match="unknown_event"):
        store.finish("run-0000000000-zz", state="RUN_DONE", receipt={})
    done = store.finish(
        "run-0000000000-c",
        state="RUN_SKIPPED_LOCK",
        receipt=_receipt("run-0000000000-c", state="RUN_SKIPPED_LOCK", exit_code=0),
    )
    assert done["state"] == "RUN_SKIPPED_LOCK" and done["exit_code"] == 0 and done["duration_s"] == 1.5
    assert done["finished_at"] == "2026-10-08T14:00:05+00:00" and done["receipt"]["schema"] == "RunReceipt@v1"
    with pytest.raises(LedgerError, match="illegal_transition:RUN_SKIPPED_LOCK->RUN_DONE"):
        store.finish("run-0000000000-c", state="RUN_DONE", receipt=_receipt("run-0000000000-c", state="RUN_DONE"))
    assert store.claim_next(now=T0 + 2) is None
    assert store.list(lane_id="n8n-lab-watchdog")[0]["state"] == "RUN_SKIPPED_LOCK"
    assert store.list(state="RUN_DONE") == []
    ledger.close()


def test_state_vocabulary_is_exactly_the_seven_states():
    assert L.RUN_STATES == {
        "REQUESTED",
        "RUNNING",
        "RUN_DONE",
        "RUN_FAILED",
        "RUN_TIMEOUT",
        "RUN_SKIPPED_LOCK",
        "RUN_REFUSED",
    }
    assert L.RUN_FINISHED_STATES == L.RUN_STATES - {"REQUESTED", "RUNNING"}


def test_request_rejects_empty_fields(tmp_path):
    ledger = CoordinationLedger(tmp_path / "e.sqlite")
    store = LedgerRunStore(ledger)
    with pytest.raises(LedgerError, match="malformed_event"):
        store.request(run_id="", lane_id="x", mode="live", requested_by=None, caller_id=None, now=time.time())
    assert store.list() == []
    ledger.close()
