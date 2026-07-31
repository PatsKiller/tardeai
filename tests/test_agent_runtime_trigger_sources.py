"""Deterministic trigger source adapter tests."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    assert "alerts:risk" in ids
    assert "alerts:proposals" in ids


def _mock_conn(rows: list[dict]):
    conn = MagicMock()
    cur = MagicMock()
    if rows:
        cur.description = [(k,) for k in rows[0].keys()]
        cur.fetchall.return_value = [tuple(r.values()) for r in rows]
    else:
        cur.description = []
        cur.fetchall.return_value = []
    conn.cursor.return_value = cur
    return conn


@patch.dict("os.environ", {"AGENT_RUNTIME_SOURCE_DSN": "postgresql://mock"}, clear=False)
@patch("agent_runtime.trigger_sources._connection_factory")
@patch("agent_runtime.trigger_sources._table_exists", return_value=True)
@patch("agent_runtime.trigger_sources._fetch_rows")
def test_incidents_alert_adapter_real_schema(mock_fetch, _tables, mock_factory):
    ts = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    mock_fetch.return_value = [{
        "incident_id": "inc-1",
        "alert_type": "stop_breach",
        "source_system": "alerts",
        "first_seen_at": ts,
        "last_seen_at": ts,
        "severity": "high",
        "status": "open",
    }]
    mock_factory.return_value = lambda: _mock_conn([])
    result = run_adapter("incidents:alert", None)
    assert result.probe.state == SourceState.READY
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.agent_id == "aegis"
    assert c.job_type == "incident_review"
    assert c.trigger_kind == "INCIDENT_OPENED"


@patch.dict("os.environ", {"AGENT_RUNTIME_SOURCE_DSN": "postgresql://mock"}, clear=False)
@patch("agent_runtime.trigger_sources._connection_factory")
@patch("agent_runtime.trigger_sources._table_exists", return_value=True)
@patch("agent_runtime.trigger_sources._fetch_rows")
def test_research_hermes_adapter_job_types(mock_fetch, _tables, mock_factory):
    ts = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    mock_fetch.return_value = [{
        "ref_id": "hd-1",
        "normalized_key": "sym:NVDA",
        "label": "NVDA hypothesis",
        "summary": "test",
        "extracted_symbols": ["NVDA"],
        "status": "READY_FOR_REVIEW",
        "created_at": ts,
    }]
    mock_factory.return_value = lambda: _mock_conn([])
    result = run_adapter("research:hermes", None)
    assert result.probe.state == SourceState.READY
    agents = {c.agent_id: c.job_type for c in result.candidates}
    assert agents["hermes"] == "hypothesis_discovery"
    assert agents["alex"] == "cio_synthesis"


@patch.dict("os.environ", {"AGENT_RUNTIME_SOURCE_DSN": "postgresql://mock"}, clear=False)
@patch("agent_runtime.trigger_sources._connection_factory")
@patch("agent_runtime.trigger_sources._table_exists", return_value=True)
@patch("agent_runtime.trigger_sources._fetch_rows")
def test_kb_candidate_lessons_adapter(mock_fetch, _tables, mock_factory):
    ts = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    mock_fetch.return_value = [{
        "lesson_id": "lesson-1",
        "title": "Test lesson",
        "lifecycle": "CANDIDATE",
        "created_at": ts,
        "statement": "Always verify stops.",
        "provenance": {"source": "reflection"},
    }]
    mock_factory.return_value = lambda: _mock_conn([])
    result = run_adapter("kb:candidate_lessons", None)
    assert result.probe.state == SourceState.READY
    assert result.candidates[0].agent_id == "iris"
    assert result.candidates[0].job_type == "lesson_review"


@patch.dict("os.environ", {"AGENT_RUNTIME_SOURCE_DSN": "postgresql://mock"}, clear=False)
@patch("agent_runtime.trigger_sources._connection_factory")
@patch("agent_runtime.trigger_sources._table_exists", return_value=True)
@patch("agent_runtime.trigger_sources._fetch_rows")
def test_alerts_risk_adapter(mock_fetch, _tables, mock_factory):
    ts = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    mock_fetch.return_value = [{
        "incident_id": "inc-r1",
        "alert_type": "stop_loss_risk",
        "source_system": "alerts",
        "first_seen_at": ts,
        "severity": "high",
        "status": "open",
        "symbol": "AAPL",
    }]
    mock_factory.return_value = lambda: _mock_conn([])
    result = run_adapter("alerts:risk", None)
    assert result.probe.state == SourceState.READY
    assert result.candidates[0].agent_id == "risk_agent"
    assert result.candidates[0].job_type == "risk_evidence_review"
