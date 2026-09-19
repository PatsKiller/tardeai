"""Instrument-subject wake enqueue — M5 path (subject_key on wake context)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def wake_store(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    return CIOWakeJobStore(event_store_path=tmp_path / "cio_wakes.jsonl")


@pytest.fixture
def record_store(tmp_path):
    from scripts.lib.cio_instrument_record import InstrumentRecordStore
    path = tmp_path / "instrument_records.jsonl"
    store = InstrumentRecordStore(path=path)
    # Due now
    store.upsert({
        "subject_key": "WATCH:SCHG",
        "kind": "WATCH",
        "cc_narrative": {"what": "test"},
        "next_eligible_at": (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat().replace("+00:00", "Z"),
    })
    # Not due yet
    store.upsert({
        "subject_key": "HELD:VTI",
        "kind": "HELD",
        "cc_narrative": {"what": "future"},
        "next_eligible_at": (datetime.now(timezone.utc) + timedelta(days=7))
            .isoformat().replace("+00:00", "Z"),
    })
    return store


def test_enqueue_instrument_wakes_sets_subject_key(wake_store, record_store, tmp_path):
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher

    disp = CIOWakeDispatcher(
        wake_store=wake_store,
        dispatch_ledger_path=str(tmp_path / "dispatch.jsonl"),
    )
    out = disp.enqueue_instrument_wakes(max_new=3, record_store=record_store)
    assert len(out["enqueued"]) == 1
    assert out["enqueued"][0]["subject_key"] == "WATCH:SCHG"
    assert out["skipped_cadence_count"] >= 1

    wakes = wake_store.list_wakes(status="PENDING", limit=10)
    assert len(wakes) == 1
    ctx = wakes[0].get("context") or {}
    assert ctx.get("subject_key") == "WATCH:SCHG"

    # Dedup on second call same hour
    out2 = disp.enqueue_instrument_wakes(max_new=3, record_store=record_store)
    assert out2["enqueued"] == []
    assert len(out2["skipped_dedup"]) >= 1


def test_subject_decide_resolves_instrument_wake(wake_store, record_store, tmp_path):
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
    from scripts.lib.cio_wake_subject import decide

    disp = CIOWakeDispatcher(
        wake_store=wake_store,
        dispatch_ledger_path=str(tmp_path / "dispatch.jsonl"),
    )
    disp.enqueue_instrument_wakes(max_new=1, record_store=record_store)
    wake = wake_store.list_wakes(status="PENDING", limit=1)[0]
    d = decide(wake, store=record_store)
    assert d["subject_resolved"] is True
    assert d["subject_key"] == "WATCH:SCHG"
    assert d["record_found"] is True
    assert d["verdict"] == "proceed"

