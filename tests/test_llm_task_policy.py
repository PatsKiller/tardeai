"""Local LLM is math-only unless an operator rollback flag is set."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.llm_task_policy import (  # noqa: E402
    KIND_EMBED,
    KIND_JUDGMENT,
    KIND_MATH,
    POLICY_LOCAL_JUDGMENT_FORBIDDEN,
    allow_local_llm,
    classify_task,
    filter_local_providers,
)


def test_classify_math_judgment_embed():
    assert classify_task("math") == KIND_MATH
    assert classify_task("numeric_score") == KIND_MATH
    assert classify_task("math_rank") == KIND_MATH
    assert classify_task("embed") == KIND_EMBED
    assert classify_task("nomic-embed-text") == KIND_EMBED
    assert classify_task("agent_narrative") == KIND_JUDGMENT
    assert classify_task("research") == KIND_JUDGMENT
    assert classify_task("cio_synthesis") == KIND_JUDGMENT
    assert classify_task("") == KIND_JUDGMENT
    assert classify_task("default") == KIND_JUDGMENT


def test_allow_local_math_always(monkeypatch):
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    monkeypatch.delenv("LLM_ALLOW_LOCAL_JUDGMENT", raising=False)
    assert allow_local_llm("math") is True
    assert allow_local_llm("numeric") is True


def test_allow_local_embed_only_nomic(monkeypatch):
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    monkeypatch.delenv("LLM_ALLOW_LOCAL_JUDGMENT", raising=False)
    monkeypatch.delenv("LLM_EMBEDDING", raising=False)
    assert allow_local_llm("embed") is True
    assert allow_local_llm("embed", local_model="nomic-embed-text:latest") is True
    assert allow_local_llm("embed", local_model="qwen3-embedding:8b") is False


def test_judgment_local_forbidden_by_default(monkeypatch):
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    monkeypatch.delenv("LLM_ALLOW_LOCAL_JUDGMENT", raising=False)
    assert allow_local_llm("agent_narrative") is False
    assert allow_local_llm("research") is False
    chain, reason = filter_local_providers("agent_narrative", ["local", "deepseek-flash"])
    assert chain == ["deepseek-flash"]
    assert reason and "POLICY_LOCAL_JUDGMENT_FORBIDDEN" in reason
    assert POLICY_LOCAL_JUDGMENT_FORBIDDEN.split()[0] in reason


def test_judgment_rollback_flags(monkeypatch):
    monkeypatch.setenv("LLM_ALLOW_LOCAL_JUDGMENT", "1")
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    assert allow_local_llm("agent_narrative") is True
    chain, reason = filter_local_providers("agent_narrative", ["local", "deepseek-flash"])
    assert chain == ["local", "deepseek-flash"]
    assert reason is None
    monkeypatch.delenv("LLM_ALLOW_LOCAL_JUDGMENT", raising=False)
    monkeypatch.setenv("RESEARCH_ALLOW_LOCAL_LLM", "1")
    assert allow_local_llm("cio_synthesis") is True


def test_filter_does_not_drop_deepseek():
    chain, reason = filter_local_providers("agent_narrative", ["deepseek-flash"])
    assert chain == ["deepseek-flash"]
    assert reason is None


def test_router_live_tables_never_include_local_for_agent_tasks():
    """Live routing already never uses local for agent_narrative (Flash-only)."""
    import llm_router

    for table in (
        llm_router._TASK_ROUTING_PRE_GPU,
        llm_router._TASK_ROUTING_POST_GPU,
        llm_router._HIGH_IMPACT_ROUTING,
    ):
        for task, chain in table.items():
            if task in (
                "agent_narrative",
                "agent_debate",
                "cio_synthesis",
                "sector_correlation",
                "default",
            ):
                assert chain == ["deepseek-flash"], (task, chain)
                assert "local" not in chain


def test_router_skips_local_for_judgment_if_table_changes(monkeypatch):
    import llm_router

    called = []
    monkeypatch.setattr(
        llm_router,
        "_TASK_ROUTING",
        {"agent_narrative": ["local", "deepseek-flash"], "default": ["deepseek-flash"]},
    )
    monkeypatch.setattr(
        llm_router,
        "_call_local",
        lambda *a, **k: called.append("local") or {
            "success": True, "provider": "local", "model_used": "gemma3:4b",
            "response": "x" * 40, "cost_estimate": 0.0, "latency": 0.01,
        },
    )
    monkeypatch.setattr(
        llm_router,
        "_call_deepseek_flash_governed",
        lambda *a, **k: {
            "success": True, "provider": "deepseek", "model_used": "deepseek-v4-flash",
            "response": "flash-ok", "cost_estimate": 0.0, "latency": 0.01,
        },
    )
    monkeypatch.setattr(llm_router, "_log_call", lambda *a, **k: None)
    monkeypatch.delenv("LLM_ALLOW_LOCAL_JUDGMENT", raising=False)
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    r = llm_router.get_llm_response("agent_narrative", "Should we trim SCHD?")
    assert "local" not in called
    assert r.get("provider") == "deepseek"
    assert r.get("success") is True
    reasons = " ".join(r.get("fallback_reasons") or [])
    assert "POLICY_LOCAL_JUDGMENT_FORBIDDEN" in reasons


def test_router_allows_local_for_math(monkeypatch):
    import llm_router

    def _fake_local(*a, **k):
        return {
            "success": True, "provider": "local", "model_used": "gemma3:4b",
            "response": "42 " * 20, "cost_estimate": 0.0, "latency": 0.01,
        }

    monkeypatch.setattr(
        llm_router,
        "_TASK_ROUTING",
        {"math": ["local"], "default": ["deepseek-flash"]},
    )
    providers = dict(llm_router._PROVIDERS)
    providers["local"] = _fake_local
    monkeypatch.setattr(llm_router, "_PROVIDERS", providers)
    monkeypatch.setattr(llm_router, "_log_call", lambda *a, **k: None)
    monkeypatch.delenv("LLM_ALLOW_LOCAL_JUDGMENT", raising=False)
    r = llm_router.get_llm_response("math", "What is 6*7?")
    assert r.get("provider") == "local"
    assert r.get("success") is True
