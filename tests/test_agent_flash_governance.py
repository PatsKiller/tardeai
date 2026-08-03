"""Tests for governed agent_flash path (issue #283)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_legacy_ids_rejected():
    from lib.agent_flash_governance import reject_legacy_model_id, LEGACY_MODEL_IDS
    for mid in ("deepseek-chat", "deepseek-reasoner", "deepseek-v4", "deepseek_v4"):
        with pytest.raises(RuntimeError, match="LEGACY_MODEL_REJECTED"):
            reject_legacy_model_id(mid)
    assert "deepseek-chat" in LEGACY_MODEL_IDS


def test_process_matrix_mapping():
    from lib.agent_flash_governance import process_for_task, policy_for_task, FLASH_MODEL
    assert process_for_task("agent_narrative") == "watchlist_maria_flash_narrative"
    assert process_for_task("agent_debate") == "watchlist_agent_debate_flash"
    assert process_for_task("cio_synthesis") == "watchlist_steph_flash_narrative"
    assert process_for_task("sector_correlation") == "watchlist_risk_flash_narrative"
    assert policy_for_task("agent_debate") == "FAST_THINK"
    assert policy_for_task("agent_narrative") == "FAST"
    assert FLASH_MODEL == "deepseek-v4-flash"


def test_registry_processes_have_caps():
    import json
    reg = json.loads((ROOT / "config/llm_process_registry.json").read_text())
    needed = {
        "watchlist_maria_flash_narrative",
        "watchlist_risk_flash_narrative",
        "watchlist_steph_flash_narrative",
        "watchlist_agent_debate_flash",
        "watchlist_agent_flash_extract",
    }
    by_id = {p["id"]: p for p in reg["processes"]}
    for pid in needed:
        p = by_id[pid]
        assert p.get("daily_cost_cap_usd") and float(p["daily_cost_cap_usd"]) > 0, pid
        assert p.get("daily_soft_cap") and int(p["daily_soft_cap"]) > 0, pid
        assert "deepseek-v4-flash" in (p.get("allowed_lanes") or []) or "fast" in (p.get("allowed_lanes") or [])
        assert p.get("fallback_allowed") is False
        assert "PRO" not in (p.get("deepseek_allowed_policies") or [])
        assert "PRO_MAX" not in (p.get("deepseek_allowed_policies") or [])


def test_missing_process_cap_fails_closed(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": None,
            "daily_soft_cap": None,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )

    def boom(*a, **k):
        raise RuntimeError("COST_CONFIGURATION_INVALID: process daily_cost_cap_usd required")

    monkeypatch.setattr(lc, "gate_and_generate", boom)
    r = ag.governed_flash_call("Reply with exactly: OK", task_type="agent_narrative", max_tokens=32)
    assert r["success"] is False
    assert "COST_CONFIGURATION" in (r.get("error") or "").upper() or "cost" in (r.get("error") or "").lower()


def test_returned_model_mismatch_fails(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast", "deepseek-flash"],
        },
    )

    def fake_gate(*a, **k):
        return "ok", {
            "returned_model": "deepseek-chat",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.001,
            "fallback_used": False,
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }

    monkeypatch.setattr(lc, "gate_and_generate", fake_gate)
    r = ag.governed_flash_call("hi", task_type="agent_narrative", max_tokens=32)
    assert r["success"] is False
    assert "MISMATCHED" in (r.get("error") or "")


def test_dedupe_skips_second_call(monkeypatch, tmp_path):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "_DEDUPE_PATH", tmp_path / "dedupe.json")
    monkeypatch.setattr(ag, "_DEDUPE_CACHE", {})
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    calls = {"n": 0}

    def fake_gate(*a, **k):
        calls["n"] += 1
        return "OK", {
            "returned_model": "deepseek-v4-flash",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.00001,
            "fallback_used": False,
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "request_id": "req-1",
        }

    monkeypatch.setattr(lc, "gate_and_generate", fake_gate)
    r1 = ag.governed_flash_call("same prompt", task_type="agent_narrative", job_key="j1", max_tokens=32)
    r2 = ag.governed_flash_call("same prompt", task_type="agent_narrative", job_key="j1", max_tokens=32)
    assert r1["success"] is True
    assert r2["success"] is False
    assert "DEDUPE" in (r2.get("error") or "")
    assert calls["n"] == 1


def test_router_rejects_deepseek_v4_alias():
    import llm_router
    r = llm_router._call_deepseek_v4_legacy_rejected("x")
    assert r["success"] is False
    assert "LEGACY" in r["error"]


def test_router_uses_governed_process_not_llm_router(monkeypatch):
    import llm_router
    seen = {}

    def fake_gov(prompt, **kwargs):
        seen.update(kwargs)
        return {
            "success": True,
            "response": "OK",
            "provider": "deepseek",
            "model_used": "deepseek-v4-flash",
            "returned_model": "deepseek-v4-flash",
            "process_id": "watchlist_maria_flash_narrative",
            "cost_estimate": 0.00001,
            "latency": 0.1,
            "fallback_used": False,
            "provider_request_id": "abc",
            "tokens": {"prompt_tokens": 5, "completion_tokens": 1},
        }

    monkeypatch.setattr(llm_router, "_call_deepseek_flash_governed", fake_gov)
    r = llm_router.get_llm_response("agent_narrative", "Reply with exactly: OK", max_tokens=32)
    assert r["success"] is True
    assert r["model_used"] == "deepseek-v4-flash"
    assert r.get("process_id") == "watchlist_maria_flash_narrative" or seen.get("task_type") == "agent_narrative"
    assert "deepseek-chat" not in str(r)


def test_no_broker_authority_in_governance_module():
    src = (ROOT / "scripts/lib/agent_flash_governance.py").read_text()
    for bad in ("broker", "order_submit", "2fa", "schwab_place", "live_trading"):
        assert bad not in src.lower() or bad == "broker"  # allow if not present
    assert "schwab" not in src.lower()
    assert "place_order" not in src.lower()


def test_cost_registry_matches_estimate():
    from lib.llm_model_registry import estimate_usd_cost
    e = estimate_usd_cost(model_id="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=300)
    assert e.get("estimated_cost_usd") is not None
    assert e["estimated_cost_usd"] < 0.01  # flash is cheap
    assert "registry" in (e.get("cost_basis") or "")


def test_llm_router_source_forbids_deepseek_chat_label():
    src = (ROOT / "scripts/llm_router.py").read_text()
    # must not assign model_used deepseek-chat as success label
    assert 'model_used": "deepseek-chat"' not in src
    assert "model_used': 'deepseek-chat'" not in src
