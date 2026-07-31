"""Tests for FLEET critic LLM lane helper."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime import critic_llm as cl  # noqa: E402


@pytest.mark.parametrize(
    "severity,confidence,doc_count,expected",
    [
        ("high", None, 0, True),
        ("critical", None, 1, True),
        ("info", 0.5, 0, True),
        ("info", 0.3, 0, False),
        ("info", None, 4, True),
        ("warning", 0.7, 1, False),
    ],
)
def test_should_escalate_truth_table(severity, confidence, doc_count, expected):
    assert cl.should_escalate(severity=severity, confidence=confidence, doc_count=doc_count) is expected


def test_lanes_enabled_default_off(monkeypatch):
    monkeypatch.delenv("AGENT_RUNTIME_CRITIC_LANES", raising=False)
    assert cl.lanes_enabled() is False


def test_lanes_enabled_on(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_CRITIC_LANES", "1")
    assert cl.lanes_enabled() is True


def test_redact_or_refuse_redacts_currency():
    out = cl.redact_or_refuse("Portfolio total $1,234,567.89")
    assert out is not None
    assert "$1" not in out
    assert "1,234" not in out


def test_redact_or_refuse_allows_clean_text():
    out = cl.redact_or_refuse("Lesson: do not add to the largest holding.")
    assert out is not None
    assert "largest holding" in out


def test_generate_for_critic_default_off_is_deterministic(monkeypatch):
    monkeypatch.delenv("AGENT_RUNTIME_CRITIC_LANES", raising=False)
    result = cl.generate_for_critic(
        agent_id="iris",
        prompt="classify",
        egress=cl.EgressClass.TEXT_ONLY,
        severity="high",
        force=False,
    )
    assert result.provider_family == "deterministic"
    assert result.model == "none"
    assert result.cost_usd == 0.0
    assert result.escalated is False


@patch.object(cl, "_oauth_generate", return_value="ok")
@patch.object(cl, "lanes_enabled", return_value=True)
def test_generate_for_critic_text_only_uses_oauth(_lanes, _oauth, monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_CRITIC_LANES", "1")
    result = cl.generate_for_critic(
        agent_id="iris",
        prompt="Lesson text only",
        egress=cl.EgressClass.TEXT_ONLY,
        severity="high",
        force=True,
    )
    assert result.provider_family == "cloud_free/grok"
    assert result.lane_used == "grok"
    assert result.cost_usd == 0.0


@patch.object(cl, "_local_generate", return_value="local answer")
@patch.object(cl, "_oauth_generate", return_value=None)
@patch.object(cl, "lanes_enabled", return_value=True)
def test_generate_for_critic_falls_back_local(_lanes, _oauth, _local, monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_CRITIC_LANES", "1")
    result = cl.generate_for_critic(
        agent_id="alex",
        prompt="clean text",
        egress=cl.EgressClass.TEXT_ONLY,
        severity="high",
        force=True,
    )
    assert result.provider_family == "local/ollama"
    assert result.lane_used == "local"


@patch.object(cl, "_local_generate", return_value="local only")
@patch.object(cl, "lanes_enabled", return_value=True)
def test_generate_for_critic_local_only_never_oauth(_lanes, _local, monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_CRITIC_LANES", "1")
    with patch.object(cl, "_oauth_generate") as oauth:
        result = cl.generate_for_critic(
            agent_id="reflection",
            prompt="payload",
            egress=cl.EgressClass.LOCAL_ONLY,
            severity="info",
            force=True,
        )
        oauth.assert_not_called()
    assert result.provider_family == "local/ollama"


def test_finding_from_lesson_verdict_contradiction_is_high():
    finding = cl.finding_from_lesson_verdict(lesson_id="C1", verdict="CONTRADICTION", ref="R1")
    assert finding["severity"] == "high"
    assert finding["code"] == "contradiction_confirmed"


@patch.object(cl, "generate_for_critic")
def test_classify_lesson_verdict_parses_json(mock_gen):
    mock_gen.return_value = cl.CriticLlmResult(
        text='{"verdict":"CONTRADICTION","ref":"R1"}',
        provider_family="cloud_free/grok",
        model="grok-3-mini",
        lane_used="grok",
        escalated=True,
    )
    verdict, result = cl.classify_lesson_verdict(
        candidate_id="C1",
        candidate_statement="Adding to largest position is fine.",
        ratified=[{"lesson_id": "R1", "statement": "Do not add to largest holding."}],
    )
    assert verdict == "CONTRADICTION"
    assert result.lane_used == "grok"
