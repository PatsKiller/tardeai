"""Deterministic trigger source adapter tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.trigger_sources import SourceState, probe_all_sources, run_adapter  # noqa: E402


def test_event_adapter_without_dsn_is_blocked():
    result = run_adapter("watch:artifacts", None)
    assert result.probe.state == SourceState.NOT_CONFIGURED
    assert result.candidates == ()


def test_sweep_adapter_emits_one_candidate():
    result = run_adapter("sweep:darwin", None)
    assert result.probe.state == SourceState.READY
    assert len(result.candidates) == 1
    assert result.candidates[0].agent_id == "darwin"
    assert result.candidates[0].trigger_kind == "SCHEDULED_SWEEP"


def test_nightly_reflection_adapter():
    result = run_adapter("nightly:reflection", None)
    assert result.candidates[0].agent_id == "reflection"
    assert result.candidates[0].trigger_kind == "NIGHTLY_BATCH"


def test_probe_all_sources_includes_sweeps():
    probes = probe_all_sources()
    ids = {row.source_id for row in probes}
    assert "sweep:darwin" in ids
    assert "nightly:reflection" in ids
