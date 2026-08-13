#!/usr/bin/env python3
"""Loop-break guard for the topic_ingestion <-> topic_curator feedback loop.

2026-08-13: an unbounded loop (ingest auto-spawns curator, curator re-runs ingest)
produced the 8/3 110-message Telegram burst. These tests pin the two fixes:
(1) the curator's re-ingest passes --no-auto-curate so it cannot re-spawn another
curator, and (2) the global min-interval guard rejects sub-interval re-entry.

Source-inspection based (no DB/network), plus a functional check of the guard.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

TOPIC_INGESTION_SRC = (SCRIPTS / "topic_ingestion.py").read_text(encoding="utf-8")
TOPIC_CURATOR_SRC = (SCRIPTS / "topic_curator.py").read_text(encoding="utf-8")


def test_ingestion_registers_no_auto_curate_flag():
    assert 'parser.add_argument("--no-auto-curate"' in TOPIC_INGESTION_SRC
    assert "args.no_auto_curate" in TOPIC_INGESTION_SRC


def test_ingestion_curator_spawn_is_gated_by_flag():
    # The post-ingestion curator spawn must be conditioned on `not args.no_auto_curate`.
    assert "not args.no_auto_curate" in TOPIC_INGESTION_SRC


def test_curator_reenige_passes_no_auto_curate():
    # Step 3b must add --no-auto-curate to the topic_ingestion invocation so a
    # re-ingest run cannot trigger yet another curator.
    assert '"--use-llm-queries", "--no-auto-curate"' in TOPIC_CURATOR_SRC


def test_min_interval_gate_rejects_rapid_reeentry(tmp_path, monkeypatch):
    ti = importlib.import_module("topic_ingestion")
    monkeypatch.setattr(ti, "_INGESTION_GATE_PATH", str(tmp_path / "gate.stamp"))
    monkeypatch.setattr(ti, "_INGESTION_MIN_INTERVAL_S", 30.0)
    # First call records the stamp and passes.
    assert ti._interval_gate_ok() is True
    # Second call within the interval must be rejected.
    assert ti._interval_gate_ok() is False


def test_min_interval_gate_recovers_after_interval(tmp_path, monkeypatch):
    ti = importlib.import_module("topic_ingestion")
    gate = tmp_path / "gate.stamp"
    monkeypatch.setattr(ti, "_INGESTION_GATE_PATH", str(gate))
    monkeypatch.setattr(ti, "_INGESTION_MIN_INTERVAL_S", 30.0)
    assert ti._interval_gate_ok() is True
    # Simulate the interval elapsing by backdating the stamp.
    gate.write_text("0", encoding="utf-8")
    assert ti._interval_gate_ok() is True


if __name__ == "__main__":
    import traceback
    failed = 0
    for name in sorted(n for n in globals() if n.startswith("test_")):
        fn = globals()[name]
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
