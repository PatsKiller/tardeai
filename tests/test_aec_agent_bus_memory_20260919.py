"""Hermetic tests for AEC agent bus + memory spines + cycle entrypoint."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses needs the module registered before exec (AGENTS.md trap).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_bus_refuses_behavior_fields(tmp_path):
    bus = _load("aec_agent_bus", "scripts/lib/aec_agent_bus.py")
    path = tmp_path / "bus.jsonl"
    try:
        bus.publish(
            agent_id="cio_agent",
            topic="t",
            summary="x",
            payload={"size_usd": 100},
            path=path,
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "MBI_BEHAVIOR=0" in str(e)


def test_bus_publish_and_cross_agent_visibility(tmp_path):
    bus = _load("aec_agent_bus", "scripts/lib/aec_agent_bus.py")
    path = tmp_path / "bus.jsonl"
    bus.publish(agent_id="cio_agent", topic="a", summary="cio", path=path)
    bus.publish(agent_id="advisor_agent", topic="b", summary="adv", path=path)
    rows = bus.read_recent(path, limit=10)
    assert len(rows) == 2
    seen = bus.topics_for("narrator_agent", rows)
    assert len(seen) == 2


def test_memory_retrieve_and_anti_repeat(tmp_path):
    mem = _load("aec_memory_spines", "scripts/lib/aec_memory_spines.py")
    path = tmp_path / "mem.json"
    mem.append_fact("learning", {"claim_fp": "abc", "text": "buy thesis"}, path=path)
    snap = mem.load(path)
    assert mem.seen_claim(snap, "abc") is True
    assert mem.seen_claim(snap, "zzz") is False
    rel = mem.retrieve_relevant(snap, subject_key=None, limit_per_spine=3)
    assert len(rel["learning"]) == 1


def test_cycle_dry_run_no_write(tmp_path, monkeypatch):
    bus = _load("aec_agent_bus", "scripts/lib/aec_agent_bus.py")
    mem = _load("aec_memory_spines", "scripts/lib/aec_memory_spines.py")
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    # Reload cycle with env
    import importlib

    sys.path.insert(0, str(ROOT / "scripts"))
    # Import via file path to pick up lib
    cycle = _load("aec_command_center_cycle", "scripts/aec_command_center_cycle.py")
    out = cycle.run_cycle(subject_key="WATCH:SCHG", apply=False)
    assert out["apply"] is False
    assert len(out["events"]) == 3
    assert not (tmp_path / "bus.jsonl").exists()
