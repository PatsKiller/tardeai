"""GUI is a projection of the intelligence lifecycle, never the ingestion bus."""
from __future__ import annotations

from pathlib import Path

import scripts.api_v3_cio as api

ROOT = Path(__file__).resolve().parents[1]


def test_lifecycle_panel_is_projection_only() -> None:
    brain = (ROOT / "apps/command-center-v3/src/components/cio/CioBrainPanel.tsx").read_text(encoding="utf-8")
    assert "cio-brain-intelligence-lifecycle" in brain
    assert "cio-brain-graph-context" in brain
    assert "cio-brain-curation-history" in brain
    assert "cio-brain-model-performance" in brain
    assert "cio-brain-unwired" in brain
    assert "GUI is a projection" in brain
    assert "Self-promote" in brain


def test_lifecycle_api_is_not_an_ingestion_bus() -> None:
    row = api.get_intelligence_lifecycle_v1("NVDA")
    assert row["ingestion_bus"] is False
    assert row["gui_cannot_self_promote"] is True
    assert row["memory_behavior_influence"] == 0
    assert row["projection"]["ingestion_bus"] is False
    perf = api.get_model_performance_v1()
    assert perf["automatic_promotion"] is False
    assert perf["gui_cannot_self_promote"] is True
