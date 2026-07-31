"""Tests for the LAB watch provider module."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.agents.definitions import ENABLED_SHADOW_AGENT_IDS, FLEET  # noqa: E402
from agent_runtime.providers import lab_watch_provider as provider  # noqa: E402


def test_build_providers_rejects_unknown_agent():
    with pytest.raises(ValueError, match="unknown agent"):
        provider.build_providers("not_real")


def test_job_source_sentinel_uses_canonical_id_and_fixture():
    jobs = provider.job_source("sentinel", 3)
    assert jobs
    assert all(j.agent_id == "sentinel" for j in jobs)
    assert all(j.job_type == "watch_ticket_review" for j in jobs)


def test_job_source_generic_agent_seed():
    jobs = provider.job_source("darwin", 2)
    assert jobs
    assert jobs[0].agent_id == "darwin"


def test_enabled_fleet_includes_sixteen_catalog_agents():
    assert len(ENABLED_SHADOW_AGENT_IDS) == 16
    for agent_id in ("alex", "maria", "pulse", "tax_agent"):
        assert agent_id in FLEET
        assert FLEET[agent_id].is_operable_now


def test_make_processor_returns_callable(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_LAB_JOURNAL_DIR", str(tmp_path / "journal"))
    providers = provider.build_providers("darwin")
    proc = providers.make_processor(None)
    job = provider.job_source("darwin", 1)[0]
    result = proc(job)
    assert result["agent_id"] == "darwin"
    assert "run_id" in result
