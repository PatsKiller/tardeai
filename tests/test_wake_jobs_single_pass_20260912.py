"""list_wakes() must read the event store once, and return the same answer.

Measured 2026-09-12 against the live store (16,306 events / 5,145 streams):
the old implementation made one pass to collect stream ids and then one more
full pass per stream inside get_wake_job(), for 83.9 million json.loads and
14.1 minutes of parsing against a 900s timeout. cio_wake_dispatch_entrypoint
and every tradeai-agent-runtime@ unit spun a full core and were killed at 15
minutes; the dispatcher log shows the same five wake_job_ids being re-dispatched
cycle after cycle, never consumed.

Speed is not the contract being protected here -- correctness is. Grouping the
events changes the ORDER in which streams are replayed, so this asserts the new
result equals the old algorithm's result exactly, on a store built to be hostile:
interleaved streams, several statuses and priorities, and a genesis record that
must stay excluded.

These tests build their own store in tmp_path and never read production data.
"""

from __future__ import annotations

import json

import pytest

from scripts.lib.cio_wake_jobs import CIOWakeJobStore


def _old_list_wakes(store, status=None, priority=None, limit=50):
    """The pre-2026-09-12 algorithm, kept verbatim as the equivalence oracle."""
    stream_ids = set()
    if store.event_store_path.exists():
        with open(store.event_store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                event = json.loads(stripped)
                sid = event["stream_id"]
                if sid != "wake-store-genesis":
                    stream_ids.add(sid)
    wakes = []
    for sid in stream_ids:
        wake = store.get_wake_job(sid)
        if wake is None:
            continue
        if status is not None and wake.get("current_status") != status:
            continue
        if priority is not None and wake.get("priority") != priority:
            continue
        wakes.append(wake)
    wakes.sort(key=lambda w: str(w.get("created_at", "")), reverse=True)
    return wakes[:limit]


@pytest.fixture()
def store(tmp_path):
    s = CIOWakeJobStore(event_store_path=tmp_path / "wake_jobs.jsonl")
    return s


def _seed(store, n_streams=12):
    """Interleave streams so grouping cannot accidentally match file order."""
    created = []
    for i in range(n_streams):
        wid = f"wake_test_{i:03d}"
        store.enqueue(
            {
                "wake_job_id": wid,
                "trigger_type": "SCHEDULE_DUE",
                "priority": "HIGH" if i % 3 == 0 else "NORMAL",
                "subject": f"SUBJ{i}",
                "reason": f"reason {i}",
            }
        )
        created.append(wid)
    # A second round of events in a DIFFERENT order, so streams interleave in the
    # file and per-stream order is not the same as file order.
    for i, wid in enumerate(reversed(created)):
        if i % 3 == 0:
            store.claim(wid, claim_token=f"tok-{wid}")
    return created


def test_single_pass_matches_old_algorithm(store):
    _seed(store)
    assert _old_list_wakes(store) == store.list_wakes()


@pytest.mark.parametrize("status", [None, "PENDING", "DISPATCHED"])
def test_matches_under_status_filter(store, status):
    _seed(store)
    assert _old_list_wakes(store, status=status) == store.list_wakes(status=status)


@pytest.mark.parametrize("priority", [None, "HIGH", "NORMAL"])
def test_matches_under_priority_filter(store, priority):
    _seed(store)
    assert _old_list_wakes(store, priority=priority) == store.list_wakes(
        priority=priority
    )


def test_genesis_stream_still_excluded(store):
    _seed(store)
    assert all(w.get("wake_job_id") != "wake-store-genesis" for w in store.list_wakes())


def test_reads_the_store_exactly_once(store, monkeypatch):
    """NEGATIVE CONTROL: fails on the old code, which parsed 1+N times."""
    _seed(store, n_streams=12)

    calls = {"n": 0}
    real = json.loads

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(json, "loads", counting)
    store.list_wakes()
    n_events = sum(1 for line in open(store.event_store_path) if line.strip())

    assert calls["n"] == n_events, (
        f"parsed {calls['n']} times for {n_events} events; list_wakes must make "
        "exactly one pass over the store"
    )
