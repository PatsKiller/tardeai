"""G-IR-01 — InstrumentRecord wake load + last_artifact_id stamp."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_instrument_record import (
    InstrumentRecordStore,
    load_instrument_record_for_wake,
    new_record,
    stamp_last_artifact_id,
)
from scripts.lib import cio_s0_operator_loop as s0
from scripts.lib import cio_specialist_artifact as sa


def test_wake_load_missing(tmp_path: Path):
    root = tmp_path
    (root / "data" / "cio").mkdir(parents=True)
    wake = load_instrument_record_for_wake(symbol="SCHD", root=root)
    assert wake["status"] == "IR_MISSING"
    assert wake["ok"] is False
    assert wake["record"] is None
    assert wake["memory_behavior_influence"] == 0


def test_wake_load_loaded(tmp_path: Path):
    root = tmp_path
    store = InstrumentRecordStore(root / "data/cio/cio_instrument_records.jsonl")
    store.upsert(new_record("HELD", "SCHD", last_artifact_id="art_prior"))
    wake = load_instrument_record_for_wake(symbol="SCHD", root=root)
    assert wake["status"] == "LOADED"
    assert wake["ok"] is True
    assert wake["record"]["subject_key"] == "HELD:SCHD"
    assert wake["record"]["last_artifact_id"] == "art_prior"


def test_s0_rehydrate_includes_ir_wake(tmp_path: Path):
    root = tmp_path
    store = InstrumentRecordStore(root / "data/cio/cio_instrument_records.jsonl")
    store.upsert(new_record("HELD", "AAPL", last_outcome="attached"))
    bundle = s0.rehydrate("AAPL", root=root, plans=[])
    wake = bundle.get("instrument_record_wake") or {}
    assert wake.get("status") == "LOADED"
    assert (bundle.get("research") or {}).get("prior_outcome") == "attached"


def test_stamp_last_artifact_id(tmp_path: Path):
    root = tmp_path
    store = InstrumentRecordStore(root / "data/cio/cio_instrument_records.jsonl")
    store.upsert(new_record("HELD", "MSFT"))
    out = stamp_last_artifact_id("HELD:MSFT", "art_new", root=root)
    assert out["ok"] and out["wrote"]
    # New store instance — upsert went through a different cache.
    tip = InstrumentRecordStore(root / "data/cio/cio_instrument_records.jsonl").load(
        "HELD:MSFT"
    )
    assert tip and tip.get("last_artifact_id") == "art_new"
    assert tip.get("memory_behavior_influence") == 0


def test_specialist_append_stamps_ir(tmp_path: Path):
    root = tmp_path
    store = InstrumentRecordStore(root / "data/cio/cio_instrument_records.jsonl")
    store.upsert(new_record("HELD", "NVDA"))
    row = sa.build(
        workflow_id="wf_test_1",
        plan_id="plan_1",
        artifact_id="art_nvda_1",
        provider="stub",
        outcome="VALID",
    )
    row["subject_key"] = "HELD:NVDA"
    row["symbols"] = ["NVDA"]
    result = sa.append(root, row)
    assert result.get("wrote") is True
    stamp = result.get("instrument_record_stamp") or {}
    assert stamp.get("ok") is True
    tip = InstrumentRecordStore(root / "data/cio/cio_instrument_records.jsonl").load(
        "HELD:NVDA"
    )
    assert tip and tip.get("last_artifact_id") == "art_nvda_1"


def test_no_subject_status():
    wake = load_instrument_record_for_wake("")
    assert wake["status"] == "NO_SUBJECT"
