"""Mocked DeepSeek manual path + cost enforcement."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.consumption_run_manual import classify_manual_lane, SMOKE_PROCESS_ID  # noqa: E402
from lib.llm_model_registry import RegistryError, reject_legacy_model_id  # noqa: E402


class _Resp:
    def __init__(self, **kw):
        self.ok = kw.get("ok", True)
        self.content = kw.get("content", "OK")
        self.requested_policy = kw.get("requested_policy", "FAST")
        self.executed_policy = kw.get("executed_policy", "FAST")
        self.requested_model_id = kw.get("requested_model_id", "deepseek-v4-flash")
        self.returned_model = kw.get("returned_model", "deepseek-v4-flash")
        self.thinking = kw.get("thinking", "disabled")
        self.reasoning_effort = kw.get("reasoning_effort")
        self.request_id = kw.get("request_id", "req-test")
        self.client_request_id = "client-test"
        self.latency_ms = 12
        self.estimated_cost_usd = 0.00001
        self.cost_basis = "provider_usage_x_registry_snapshot"
        self.finish_reason = "stop"
        self.raw_response_hash = "abc"
        self.fallback_used = False
        self.error_class = kw.get("error_class")
        self.error_message = kw.get("error_message")
        self.usage = kw.get("usage") or {"prompt_tokens": 5, "completion_tokens": 1}


def test_exact_model_match_via_llm_lane(monkeypatch):
    import llm_lane

    def fake_chat(**kwargs):
        assert kwargs.get("policy") == "FAST"
        return _Resp()

    monkeypatch.setattr("lib.deepseek_client.chat", fake_chat)
    text, usage, resp = llm_lane._deepseek_generate("Reply OK", lane="deepseek-flash", model=None, timeout=10)
    assert text == "OK"
    assert resp.returned_model == "deepseek-v4-flash"
    assert resp.requested_model_id == "deepseek-v4-flash"
    assert usage["_tradeai"]["fallback_used"] is False


def test_auth_missing_surfaces(monkeypatch):
    from lib.deepseek_client import DeepSeekError, AUTH_MISSING

    def boom(**kwargs):
        raise DeepSeekError(AUTH_MISSING, "no key")

    monkeypatch.setattr("lib.deepseek_client.chat", boom)
    import llm_lane
    try:
        llm_lane._deepseek_generate("hi", lane="fast", model=None, timeout=5)
        assert False, "expected raise"
    except RuntimeError as e:
        assert "AUTH_MISSING" in str(e)


def test_no_silent_fallback_on_deepseek_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("PROVIDER_ERROR: simulated")

    monkeypatch.setattr("llm_lane._deepseek_generate", boom)
    import llm_lane
    try:
        llm_lane.generate("hi", lane="deepseek-flash", timeout=5)
        assert False
    except RuntimeError as e:
        assert "PROVIDER_ERROR" in str(e) or "simulated" in str(e)


def test_legacy_reject():
    for mid in ("deepseek-chat", "deepseek-reasoner"):
        try:
            reject_legacy_model_id(mid)
            assert False
        except RegistryError:
            pass


def test_projected_cost_blocks_before_execution(monkeypatch):
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})
    monkeypatch.setattr(lc, "get_process_config", lambda pid: {
        "registered": True, "max_input_tokens": 64, "max_output_tokens": 32,
        "mode": "manual", "allowed_lanes": ["fast", "deepseek-flash"],
    })

    def block_cap(process_id, *, projected_usd=0.0, global_cap=None):
        assert projected_usd > 0
        return {"allow": False, "reason": "COST_CAP_EXCEEDED", "scope": "process"}

    monkeypatch.setattr(lc, "check_cost_cap", block_cap)
    called = {"gen": False}

    def no_gen(*a, **k):
        called["gen"] = True
        raise AssertionError("must not call provider")

    monkeypatch.setattr("llm_lane.generate", no_gen)
    try:
        lc.gate_and_generate(
            "hi", lane="deepseek-flash", process_id=SMOKE_PROCESS_ID,
            manual_trigger=True, policy="FAST",
        )
        assert False
    except RuntimeError as e:
        assert "COST_CAP" in str(e).upper()
    assert called["gen"] is False


def test_cost_persistence_failure_blocks_paid(monkeypatch):
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})
    monkeypatch.setattr(lc, "get_process_config", lambda pid: {
        "registered": True, "max_input_tokens": 64, "max_output_tokens": 32,
        "mode": "manual", "allowed_lanes": ["deepseek-flash"],
    })
    monkeypatch.setattr(lc, "cost_persistence_available", lambda: False)
    try:
        lc.gate_and_generate(
            "hi", lane="deepseek-flash", process_id=SMOKE_PROCESS_ID,
            manual_trigger=True, policy="FAST",
        )
        assert False
    except RuntimeError as e:
        assert "COST_PERSISTENCE" in str(e).upper() or "paid" in str(e).lower()


def test_classify_never_allows_pro_with_body_true():
    assert classify_manual_lane("deepseek-v4-pro", operator_confirmed=True)["ok"] is False
    assert classify_manual_lane("pro_max", operator_confirmed="true")["ok"] is False
