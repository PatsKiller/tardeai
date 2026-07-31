"""Tests for real FLEET critic pipelines (deterministic paths)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.agents.dispatcher import JobRequest  # noqa: E402
from agent_runtime.argus_pipeline import run_argus  # noqa: E402
from agent_runtime.iris_critic_pipeline import _exact_duplicate, _review_lessons  # noqa: E402
from agent_runtime.pipeline_common import advisory_payload, holdings_total_drift  # noqa: E402
from agent_runtime.providers import shadow_fleet_provider as provider  # noqa: E402


def test_advisory_payload_severity_from_findings():
    body = advisory_payload(
        agent_id="argus",
        job_type="population_integrity_scan",
        source="test",
        findings=[{"severity": "high", "message": "x"}],
        artifact_kind="integrity_review",
    )
    assert body["severity"] == "high"
    assert body["authority"] == "ADVISORY_ONLY"


def test_holdings_total_drift_computed():
    holdings = {
        "portfolio_total": 1000.0,
        "holdings": [{"symbol": "A", "market_value": 600}, {"symbol": "B", "market_value": 350}],
    }
    declared, computed, drift = holdings_total_drift(holdings)
    assert declared == 1000.0
    assert computed == 950.0
    assert drift is not None and drift > 0


@patch.object(provider, "_ollama_available", return_value=False)
def test_argus_pipeline_writes_real_findings(_mock, tmp_path, monkeypatch):
    holdings_path = ROOT / "data" / "portfolios" / "state" / "holdings.json"
    holdings_path.parent.mkdir(parents=True, exist_ok=True)
    backup = holdings_path.read_text(encoding="utf-8") if holdings_path.is_file() else None
    holdings_path.write_text(
        json.dumps(
            {
                "portfolio_total": 1000.0,
                "holdings": [{"symbol": "A", "market_value": 500}, {"symbol": "B", "market_value": 300}],
            }
        ),
        encoding="utf-8",
    )
    try:
        result = run_argus("population_integrity_scan", {"source": "test"}, None, tmp_path)
        assert result["agent_id"] == "argus"
        assert result["severity"] in {"warning", "high", "info"}
    finally:
        if backup is None:
            holdings_path.unlink(missing_ok=True)
        else:
            holdings_path.write_text(backup, encoding="utf-8")


def test_shadow_provider_routes_argus(monkeypatch, tmp_path):
    from agent_runtime.trigger_intake import InMemoryTriggerIntakeStore, TriggerCandidate

    store = InMemoryTriggerIntakeStore()
    store.enqueue(
        TriggerCandidate(
            agent_id="argus",
            trigger_kind="SCHEDULED_SWEEP",
            dedup_key="sweep:argus:1",
            job_type="population_integrity_scan",
            payload={"source": "test"},
            source_ref="sweep:argus:1",
            source_hash="a" * 64,
            source_timestamp="2026-07-31T12:00:00+00:00",
        )
    )
    monkeypatch.setattr(provider, "_store", store)
    monkeypatch.setattr(provider, "_build_store", lambda: store)
    providers = provider.build_providers("argus")
    processor = providers.make_processor(None)
    job = provider.job_source("argus", 1)[0]
    out = processor(job)
    assert out["agent_id"] == "argus"
    assert out.get("severity")


def test_iris_exact_duplicate_detection():
    ratified = [{"lesson_id": "R2", "statement": "Positions entered during earnings week must have a stop defined prior to order submission."}]
    dup = _exact_duplicate(
        "Positions entered during earnings week must have a stop defined prior to order submission.",
        ratified,
    )
    assert dup == "R2"


@patch("agent_runtime.iris_critic_pipeline.lanes_enabled", return_value=False)
def test_iris_review_without_lanes_defers_classification(_mock):
    ratified = [
        {"lesson_id": "R1", "statement": "Do not add to a position that is already the largest holding by market value."},
    ]
    candidates = [
        {"lesson_id": "C1", "statement": "Adding to the largest position is acceptable when conviction is high."},
    ]
    findings, provider_family, model = _review_lessons(candidates, ratified)
    assert provider_family == "deterministic"
    assert model == "none"
    assert findings[0]["severity"] != "high"
    assert findings[0]["code"] == "classification_deferred"


@patch("agent_runtime.iris_critic_pipeline.classify_lesson_verdict")
@patch("agent_runtime.iris_critic_pipeline.lanes_enabled", return_value=True)
def test_iris_contradiction_maps_to_high(_lanes, mock_classify):
    mock_classify.return_value = (
        "CONTRADICTION",
        type("R", (), {"escalated": True, "provider_family": "cloud_free/grok", "model": "grok-3-mini", "text": "{}"})(),
    )
    ratified = [{"lesson_id": "R1", "statement": "Do not add to largest holding."}]
    candidates = [{"lesson_id": "C1", "statement": "Adding to the largest position is acceptable when conviction is high."}]
    findings, provider_family, model = _review_lessons(candidates, ratified)
    assert findings[0]["severity"] == "high"
    assert findings[0]["code"] == "contradiction_confirmed"
    assert provider_family == "cloud_free/grok"
    assert model == "grok-3-mini"
