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


def test_bus_resolves_specialist_aliases(tmp_path):
    bus = _load("aec_agent_bus", "scripts/lib/aec_agent_bus.py")
    path = tmp_path / "bus.jsonl"
    ev = bus.publish(
        agent_id="cio_agent",
        topic="id",
        summary="alias check",
        payload={"specialist_agent_id": "risk_agent", "mentioned_agents": ["tax_agent"]},
        path=path,
        dry_run=True,
    )
    assert ev.payload["specialist_agent_id"] == "guardian"
    assert ev.payload["specialist_display"] == "Guardian Risk"
    assert ev.payload["mentioned_agents_canonical"] == ["ledger"]


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
    assert out.get("agent_view", {}).get("schema_version") == "AgentView@v1"
    assert out.get("commitment", {}).get("schema_version") == "AGENT_COMMITMENT@v1"
    assert out.get("commitment", {}).get("decision_key", "").startswith("decision:")
    assert out.get("commitment", {}).get("decision_key_parsed", {}).get("kind") == "decision"
    assert out.get("outcome", {}).get("schema_version") == "CommitmentOutcome@v1"
    assert out["outcome"]["outcome"] == "INSUFFICIENT_EVIDENCE"
    # Observation path closes the OUTCOME edge.
    out2 = cycle.run_cycle(subject_key="WATCH:SCHG", apply=False, observe={"confirmed": True})
    assert out2["outcome"]["outcome"] == "CONFIRMED"
    assert not (tmp_path / "bus.jsonl").exists()


def test_cycle_day_bucket_and_suppressed_reeval(tmp_path, monkeypatch):
    """Anti-repeat must not freeze OUTCOME for the life of the spine.

    After an applied cycle, same-day repeats re-evaluate the prior commitment
    so CONFIRMED/REFUTED can land from the scheduled timer.
    """
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    cycle = _load("aec_command_center_cycle_reeval", "scripts/aec_command_center_cycle.py")

    def _fake_integrate(envelope, *, apply=False):
        return {
            "schema": "CIOEnvelopeIntegration@v1",
            "dry_run": not apply,
            "authority": "READ_ONLY_ADVISORY",
            "mbi_behavior": 0,
        }

    monkeypatch.setattr(cycle, "integrate_wake_envelope", _fake_integrate)
    first = cycle.run_cycle(subject_key="WATCH:SCHG", apply=True)
    assert first.get("agent_view")
    assert first.get("commitment", {}).get("commitment_id")
    assert first["outcome"]["outcome"] == "INSUFFICIENT_EVIDENCE"
    cmt_id = first["commitment"]["commitment_id"]

    second = cycle.run_cycle(
        subject_key="WATCH:SCHG", apply=True, observe={"confirmed": True}
    )
    assert second["events"][1]["payload"]["suppressed"] is True
    assert second["outcome"]["outcome"] == "CONFIRMED"
    assert second["outcome"]["commitment_id"] == cmt_id
    assert second.get("agent_view") in (None, {})


def test_cycle_suppressed_reeval_expires_after_horizon(tmp_path, monkeypatch):
    """Hourly timer can settle OUTCOME as EXPIRED without a hand observation."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    cycle = _load("aec_command_center_cycle_expire", "scripts/aec_command_center_cycle.py")

    def _fake_integrate(envelope, *, apply=False):
        return {
            "schema": "CIOEnvelopeIntegration@v1",
            "dry_run": not apply,
            "authority": "READ_ONLY_ADVISORY",
            "mbi_behavior": 0,
        }

    monkeypatch.setattr(cycle, "integrate_wake_envelope", _fake_integrate)
    t0 = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    first = cycle.run_cycle(subject_key="WATCH:SCHG", apply=True, now=t0)
    assert first["outcome"]["outcome"] == "INSUFFICIENT_EVIDENCE"
    cmt_id = first["commitment"]["commitment_id"]
    # Horizon is 1h for AEC cycle commitments — next timer after due → EXPIRED.
    second = cycle.run_cycle(
        subject_key="WATCH:SCHG", apply=True, now=t0 + timedelta(hours=2)
    )
    assert second["events"][1]["payload"]["suppressed"] is True
    assert second["outcome"]["outcome"] == "EXPIRED"
    assert second["outcome"]["commitment_id"] == cmt_id


def test_cycle_apply_propagates_to_bitemporal_integrator(tmp_path, monkeypatch):
    """--apply must not hardcode bitemporal dry-run (isolated :55432 only)."""
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    seen: dict = {}

    def _fake_integrate(envelope, *, apply=False):
        seen["apply"] = apply
        return {
            "schema": "CIOEnvelopeIntegration@v1",
            "dry_run": not apply,
            "authority": "READ_ONLY_ADVISORY",
            "mbi_behavior": 0,
        }

    cycle = _load("aec_command_center_cycle_apply_prop", "scripts/aec_command_center_cycle.py")
    monkeypatch.setattr(cycle, "integrate_wake_envelope", _fake_integrate)
    out = cycle.run_cycle(subject_key="WATCH:SCHG", apply=True)
    assert out["apply"] is True
    assert seen.get("apply") is True
    assert out["bitemporal"]["dry_run"] is False
    assert (tmp_path / "bus.jsonl").exists()


def test_wake_loads_aec_spines_fail_soft(tmp_path, monkeypatch):
    """Wake helper reads four spines; spine errors never raise into the wake."""
    wake = _load("persistent_agent_wake_spines", "scripts/lib/persistent_agent_wake.py")
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "missing_mem.json"))
    out = wake.load_aec_spines_for_wake(selection_meta={"subject_key": "WATCH:SCHG"})
    # Missing file → empty snapshot, still loaded (not an exception path).
    assert out["loaded"] is True
    assert out["counts"]["strategic"] == 0
    receipt = (tmp_path / "aec_wake_spine_receipts.jsonl")
    assert receipt.is_file()
    assert "aec_spines_loaded" in receipt.read_text(encoding="utf-8")

    mem = _load("aec_memory_spines_for_wake", "scripts/lib/aec_memory_spines.py")
    path = tmp_path / "mem.json"
    mem.append_fact(
        "strategic",
        {"kind": "thesis_touch", "subject_key": "WATCH:SCHG", "note": "x"},
        path=path,
    )
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(path))
    out2 = wake.load_aec_spines_for_wake(
        selection_meta={"subject_key": "WATCH:SCHG"},
    )
    assert out2["loaded"] is True
    assert out2["counts"]["strategic"] >= 1

    # Corrupt JSON → fail-soft, never raises.
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(bad))
    out3 = wake.load_aec_spines_for_wake(selection_meta={"subject_key": "WATCH:SCHG"})
    assert out3["loaded"] is False
    assert out3.get("error")
    assert "aec_spines_unavailable" in receipt.read_text(encoding="utf-8")
