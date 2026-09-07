"""Prove required rails fail-closed when memory load / receipts / idempotency are removed."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib import persistent_agent_wake as paw  # noqa: E402
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402

SG = "97172f54-916c-5960-aa73-f16321f1cf3e"
NOW = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
ENV = {paw.FEATURE_FLAG: "1", "PROVENANCE_PRODUCER": "test", "TRADEAI_SOURCE_SHA": "deadbeef"}


def _mem(tmp_path, content="alpha"):
    p = tmp_path / "m.jsonl"
    p.write_text(json.dumps({
        "fact_id": "f1", "subject_guid": SG, "content": content,
        "as_of": NOW.isoformat().replace("+00:00", "Z"),
    }) + "\n")
    return p


def test_suite_fails_if_memory_loader_always_empty(tmp_path, monkeypatch):
    state = tmp_path / "s"; state.mkdir()
    mem = _mem(tmp_path)

    class Broken(paw.MemoryLoader):
        def load(self, subject_guid, *, now=None):
            return paw.MemorySnapshot(
                snapshot_id="x", subject_guid=subject_guid, facts=[],
                loaded_at=NOW, empty=True,
            )

    monkeypatch.setattr(paw, "MemoryLoader", Broken)
    r = paw.run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV,
    )
    # With memory loading removed, organic commitment must not appear.
    assert r["commitments"] == []
    assert JsonlStore(state).count("commitments") == 0


def test_suite_fails_if_receipt_emit_noop(tmp_path, monkeypatch):
    state = tmp_path / "s"; state.mkdir()
    mem = _mem(tmp_path)

    def boom(*a, **k):
        raise AssertionError("receipt creation removed")

    monkeypatch.setattr(paw.WakeEngine, "_emit_receipt", boom)
    with pytest.raises(AssertionError, match="receipt creation removed"):
        paw.run_scheduled_wake(
            agent_id="cio", subject_guid=SG, state_root=state,
            memory_backend=mem, when=NOW, env=ENV,
        )


def test_suite_fails_if_idempotency_key_randomized(tmp_path, monkeypatch):
    state = tmp_path / "s"; state.mkdir()
    mem = _mem(tmp_path)
    n = {"i": 0}

    def rand_wake(agent_id, wake_reason, schedule_slot_utc, subject_guid):
        n["i"] += 1
        return f"random-wake-{n['i']}"

    monkeypatch.setattr(paw, "mint_wake_id", rand_wake)
    paw.run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV)
    paw.run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV)
    # Without deterministic ids, duplicate schedule fire creates two wakes.
    assert JsonlStore(state).count("wakes") == 2
