"""P0.2 — research ops Flash-first visibility + failure-class honesty."""
from __future__ import annotations

from scripts.api_v3_cio import (
    classify_research_failure_message,
    summarize_flash_first_attempts,
)


def test_classify_cap_missing():
    assert classify_research_failure_message(
        "LLM error: COST_CONFIGURATION_INVALID: global daily USD cap required"
    ) == "LLM_GLOBAL_DAILY_USD_CAP_MISSING"


def test_classify_circuit_open():
    assert classify_research_failure_message(
        "LLM error: CIRCUIT_OPEN: agent_flash circuit breaker open until 1 last=COST_CONFIGURATION_INVALID"
    ) == "AGENT_FLASH_CIRCUIT_OPEN"


def test_classify_exhausted():
    assert classify_research_failure_message(
        "LLM error: BUDGET_EXHAUSTED global_cap exhausted"
    ) == "LLM_GLOBAL_DAILY_USD_CAP_EXHAUSTED"


def test_summarize_flash_first_attempt_vs_actual():
    rows = [
        {
            "model_used": "gemma3:4b",
            "full_result": {
                "first_provider_attempted": "deepseek-v4-flash",
                "actual_provider": "ollama",
                "model": "gemma3:4b",
                "fallback_reason": "FLASH_SOFT_FAILURE",
                "requested_provider_policy": "FLASH_FIRST_AUTO_QUEUE",
            },
        },
        {
            "model_used": "deepseek-v4-flash",
            "full_result": {
                "first_provider_attempted": "deepseek-v4-flash",
                "actual_provider": "deepseek",
                "model": "deepseek-v4-flash",
                "requested_provider_policy": "FLASH_FIRST_AUTO_QUEUE",
            },
        },
    ]
    out = summarize_flash_first_attempts(rows)
    assert out["flash_attempted"] is True
    assert out["provider_attempted_today"]["deepseek-v4-flash"] == 2
    assert out["provider_actual_today"]["ollama"] == 1
    assert out["provider_actual_today"]["deepseek"] == 1
    assert out["fallback_reason_today"]["FLASH_SOFT_FAILURE"] == 1
    assert out["requested_provider_policy_today"]["FLASH_FIRST_AUTO_QUEUE"] == 2


def test_summarize_handles_string_full_result():
    import json
    rows = [{
        "model_used": "gemma3:4b",
        "full_result": json.dumps({
            "first_provider_attempted": "deepseek-v4-flash",
            "actual_provider": "ollama",
        }),
    }]
    out = summarize_flash_first_attempts(rows)
    assert out["provider_attempted_today"]["deepseek-v4-flash"] == 1
