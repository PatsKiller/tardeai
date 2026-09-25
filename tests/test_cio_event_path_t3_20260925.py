"""Tranche 3 (2026-09-25): prompt event-driven cognition on the existing lane.

Fail→pass controls for the defects measured on the served release 1c60ecb42:

* D-CURSOR   `bus.poll` is newest-first; the reactive cycle set the consumer
             cursor to the OLDEST event of a batch, so every later cycle
             re-read the newer ones (hourly duplicate wakes).
* D-SUBJECT  `thesis.changed` / `watch.new_signal` carry a singular `symbol`;
             the cycle read only `symbols`, so 110/228 event wakes in 24h were
             subject-less and the record consult had nothing to load by.
* D-LIFO     `list_wakes` default order is newest-first; with 5 dispatch slots
             per cycle older PENDING wakes starved until the 24h expiry.
* D-RECOVER  lease recovery scanned only the 50 newest streams, re-released
             without limit, and could never move a stranded IN_FLIGHT wake.
* D-OUT      `CIOActionLedger.list_events` indexed `stream_id` on legacy rows
             (88/108 live rows) and raised KeyError from every create_action.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _bus_and_store(tmp_path):
    from scripts.lib.cio_event_bus import CIOEventBus
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    bus = CIOEventBus(bus_path=str(tmp_path / "events.jsonl"),
                      cursor_path=str(tmp_path / "cursors.jsonl"))
    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    return bus, store


def _out():
    return {"event_enqueued": [], "event_skipped": [], "event_stale": [],
            "cursor_advanced": [], "errors": []}


# ── D-CURSOR + D-SUBJECT ───────────────────────────────────────────────────

def test_cursor_lands_on_newest_processed_event_and_second_cycle_is_quiet(tmp_path):
    import cio_reactive_cycle as rc

    bus, store = _bus_and_store(tmp_path)
    ids = [bus.emit("thesis.changed", {"symbol": s, "thesis_id": f"t-{s}"}).event_id
           for s in ("NOC", "MCD", "RTX")]
    out = _out()
    n, _ = rc.process_event_bus(bus, store, out=out, max_wakes=12,
                                routing={"alex": ["thesis.changed"]})
    assert n == 3, out
    # The cursor must name the NEWEST event handled, not the oldest.
    assert out["cursor_advanced"] == [{"consumer": "reactive:alex", "event_id": ids[-1]}]
    assert bus.poll(consumer="reactive:alex", event_types=["thesis.changed"]) == []

    # A second cycle in a later hour sees nothing and enqueues nothing: no
    # duplicate wake for the same event.
    out2 = _out()
    n2, _ = rc.process_event_bus(bus, store, out=out2, max_wakes=12,
                                 routing={"alex": ["thesis.changed"]})
    assert n2 == 0 and out2["event_enqueued"] == [] and out2["event_skipped"] == []


def test_partial_batch_advances_cursor_only_through_what_was_handled(tmp_path):
    import cio_reactive_cycle as rc

    bus, store = _bus_and_store(tmp_path)
    ids = [bus.emit("thesis.changed", {"symbol": s}).event_id for s in ("A", "B", "C", "D")]
    out = _out()
    n, _ = rc.process_event_bus(bus, store, out=out, max_wakes=2,
                                routing={"alex": ["thesis.changed"]})
    assert n == 2
    # Oldest two handled; cursor sits on the second-oldest; the newer two remain.
    assert out["cursor_advanced"][0]["event_id"] == ids[1]
    remaining = {e.event_id for e in bus.poll(consumer="reactive:alex",
                                              event_types=["thesis.changed"])}
    assert remaining == {ids[2], ids[3]}


def test_singular_symbol_becomes_the_wake_subject(tmp_path):
    import cio_reactive_cycle as rc

    bus, store = _bus_and_store(tmp_path)
    ev = bus.emit("thesis.changed", {"symbol": "noc", "thesis_id": "t1"})
    out = _out()
    rc.process_event_bus(bus, store, out=out, routing={"alex": ["thesis.changed"]})
    wake = store.get_wake_job(out["event_enqueued"][0]["wake_job_id"])
    ctx = wake["context"]
    assert ctx["symbol"] == "NOC" and ctx["symbols"] == ["NOC"]
    # Correlation: the wake carries the originating event id and timestamp.
    assert ctx["correlation_id"] == ev.event_id
    assert ctx["event_ts"] == ev.timestamp
    assert wake["trigger_ref"] == ev.event_id


def test_payload_symbols_accepts_both_shapes():
    import cio_reactive_cycle as rc

    assert rc._payload_symbols({"symbols": ["MCD", "noc"]}) == ["MCD", "NOC"]
    assert rc._payload_symbols({"symbol": "rtx"}) == ["RTX"]
    assert rc._payload_symbols({"symbols": ["MCD"], "symbol": "MCD"}) == ["MCD"]
    assert rc._payload_symbols({}) == []


def test_high_priority_event_is_stored_as_high(tmp_path):
    import cio_reactive_cycle as rc

    bus, store = _bus_and_store(tmp_path)
    bus.emit("portfolio.material_change", {"pct": 3.1, "direction": "down"})
    out = _out()
    rc.process_event_bus(bus, store, out=out,
                         routing={"alex": ["portfolio.material_change"]})
    wake = store.get_wake_job(out["event_enqueued"][0]["wake_job_id"])
    assert wake["priority"] == "high"


# ── D-LIFO ─────────────────────────────────────────────────────────────────

def _enqueue(store, wid, created_at, priority=None):
    payload = {"wake_job_id": wid, "trigger_type": "EVENT_BUS", "trigger_ref": wid,
               "reason_codes": ["EVENT_BUS"], "created_at": created_at,
               "idempotency_key": wid}
    if priority:
        payload["priority"] = priority
    store.enqueue(payload)


def test_priority_fifo_order_serves_high_then_oldest(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    _enqueue(store, "w_old_normal", "2026-09-25T10:00:00+00:00")
    _enqueue(store, "w_mid_normal", "2026-09-25T11:00:00+00:00")
    _enqueue(store, "w_new_high", "2026-09-25T12:00:00+00:00", priority="high")
    _enqueue(store, "w_new_normal", "2026-09-25T13:00:00+00:00")

    default = [w["wake_job_id"] for w in store.list_wakes(status="PENDING")]
    assert default[0] == "w_new_normal"  # unchanged default: newest first

    fifo = [w["wake_job_id"] for w in store.list_wakes(status="PENDING", order="priority_fifo")]
    assert fifo == ["w_new_high", "w_old_normal", "w_mid_normal", "w_new_normal"]


def test_dispatcher_claims_oldest_pending_first(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher

    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    for i in range(8):
        _enqueue(store, f"w{i}", f"2026-09-25T0{i}:00:00+00:00")
    # Hermetic: the dispatcher's idempotency ledger defaults to data/cio in the
    # working tree; without this the control polluted that file and a second
    # run read its own ids back as "already dispatched" (D-TEST-POLLUTION).
    disp = CIOWakeDispatcher(wake_store=store, run_store=None,
                             dispatch_ledger_path=str(tmp_path / "dispatches.jsonl"))
    disp._goal_store_or_default = lambda: None  # no goal side path in this control
    disp.enqueue_instrument_wakes = lambda max_new=5: {"enqueued": []}
    res = disp.poll_and_dispatch(max_dispatches=3)
    claimed = {w["wake_job_id"] for w in store.list_wakes(limit=100)
               if w["current_status"] != "PENDING"}
    assert claimed == {"w0", "w1", "w2"}, (claimed, res)


# ── D-RECOVER ──────────────────────────────────────────────────────────────

def test_lease_recovery_dead_letters_after_max_recoveries(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    _enqueue(store, "w_crashy", "2026-09-25T10:00:00+00:00")
    for i in range(3):
        store.claim("w_crashy", claim_token=f"t{i}", lease_seconds=0)
        recovered = store.recover_expired_leases(stale_seconds=0, max_recoveries=3)
        assert recovered == ["w_crashy"], (i, recovered)
        assert store.get_wake_job("w_crashy")["current_status"] == "PENDING"
    assert store.get_wake_job("w_crashy")["release_count"] == 3

    store.claim("w_crashy", claim_token="t3", lease_seconds=0)
    recovered = store.recover_expired_leases(stale_seconds=0, max_recoveries=3)
    assert recovered == []
    w = store.get_wake_job("w_crashy")
    assert w["current_status"] == "EXPIRED"
    assert w["expiration_reason"].startswith("dead_letter:")
    assert store.last_dead_lettered[0]["wake_job_id"] == "w_crashy"


def test_lease_recovery_scans_beyond_fifty_newest_streams(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    _enqueue(store, "w_stuck", "2026-09-20T00:00:00+00:00")
    store.claim("w_stuck", claim_token="t", lease_seconds=0)
    for i in range(60):
        _enqueue(store, f"w_new{i}", f"2026-09-25T10:{i:02d}:00+00:00")
    recovered = store.recover_expired_leases(stale_seconds=0)
    assert recovered == ["w_stuck"]


def test_stale_in_flight_wake_is_expired_with_reason(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    _enqueue(store, "w_flight", "2026-09-25T10:00:00+00:00")
    store.claim("w_flight", claim_token="t", lease_seconds=300)
    store.dispatch("w_flight", linked_run_id="run-1")
    store.set_in_flight("w_flight")
    # Fresh in-flight: untouched.
    store.recover_expired_leases(stale_seconds=0)
    assert store.get_wake_job("w_flight")["current_status"] == "IN_FLIGHT"
    # Past the stale window: expired, never re-run, reason on the stream.
    store.recover_expired_leases(stale_seconds=0, stale_in_flight_seconds=0)
    w = store.get_wake_job("w_flight")
    assert w["current_status"] == "EXPIRED"
    assert w["expiration_reason"].startswith("stale_in_flight:")


# ── D-OUT ──────────────────────────────────────────────────────────────────

def test_action_ledger_tolerates_legacy_rows_without_stream_id(tmp_path):
    from scripts.lib.cio_action_ledger import CIOActionLedger

    path = tmp_path / "ledger.jsonl"
    legacy = {"event_type": "CIO_ACTION_LEGACY", "event_id": "legacy-1",
              "timestamp": "2026-08-27T00:00:00+00:00", "actor": "alex",
              "authority": "advisory", "payload": {"note": "pre-stream row"}}
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    ledger = CIOActionLedger(event_store_path=path)
    assert ledger.list_events("anything") == []
    assert ledger.list_actions() == []
    created = ledger.create_action({
        "cio_action_id": "act-t3-1", "domain": "portfolio", "title": "t3 control",
        "kind": "ADVISORY", "summary": "control action", "status": "PROPOSED",
    })
    assert created["stream_id"] == "act-t3-1"
    assert ledger.get_action("act-t3-1") is not None


def test_process_event_bus_stamps_source_sha_and_is_pure_of_clock(tmp_path):
    import cio_reactive_cycle as rc

    bus, store = _bus_and_store(tmp_path)
    bus.emit("thesis.changed", {"symbol": "NOC"})
    out = _out()
    fixed = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
    rc.process_event_bus(bus, store, out=out, now=fixed,
                         routing={"alex": ["thesis.changed"]})
    wid = out["event_enqueued"][0]["wake_job_id"]
    assert wid.endswith("_2026092515")
    ctx = store.get_wake_job(wid)["context"]
    assert "source_sha" in ctx
