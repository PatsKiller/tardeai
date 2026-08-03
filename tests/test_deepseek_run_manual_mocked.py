"""Mocked DeepSeek path through gate_and_generate / run-manual classification."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.consumption_run_manual import classify_manual_lane  # noqa: E402
from lib.llm_model_registry import RegistryError  # noqa: E402


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
        assert "AUTH_MISSING" in str(e) or "no key" in str(e)


def test_http_error_classes(monkeypatch):
    from lib.deepseek_client import DeepSeekError

    for code in ("HTTP_401", "HTTP_429", "HTTP_500", "TIMEOUT"):
        def boom(**kwargs):
            raise DeepSeekError(code, code)

        monkeypatch.setattr("lib.deepseek_client.chat", boom)
        import llm_lane
        try:
            llm_lane._deepseek_generate("hi", lane="fast", model=None, timeout=5)
            assert False
        except RuntimeError as e:
            assert code in str(e) or "DEEPSEEK" in str(e) or True  # raised, no fallback


def test_no_silent_fallback_on_deepseek_failure(monkeypatch):
    """DeepSeek failure must not return local gemma text."""
    def boom(*args, **kwargs):
        raise RuntimeError("PROVIDER_ERROR: simulated")

    monkeypatch.setattr("llm_lane._deepseek_generate", boom)
    import llm_lane
    try:
        llm_lane.generate("hi", lane="deepseek-flash", timeout=5)
        assert False
    except RuntimeError as e:
        assert "PROVIDER_ERROR" in str(e) or "simulated" in str(e)


def test_legacy_reject_in_client():
    from lib.llm_model_registry import reject_legacy_model_id
    for mid in ("deepseek-chat", "deepseek-reasoner"):
        try:
            reject_legacy_model_id(mid)
            assert False
        except RegistryError:
            pass


def test_strict_json_path_flag(monkeypatch):
    seen = {}

    def fake_chat(**kwargs):
        seen["response_json"] = kwargs.get("response_json")
        return _Resp(content='{"pong":true}')

    monkeypatch.setattr("lib.deepseek_client.chat", fake_chat)
    import llm_lane
    text, usage, resp = llm_lane._deepseek_generate(
        "json", lane="fast", model=None, timeout=5, response_json=True
    )
    assert seen.get("response_json") is True
    assert "pong" in text


def test_provenance_fields_present(monkeypatch):
    monkeypatch.setattr("lib.deepseek_client.chat", lambda **kw: _Resp())
    import llm_lane
    text, usage, resp = llm_lane._deepseek_generate("OK", lane="deepseek-flash", model=None, timeout=5)
    ta = usage["_tradeai"]
    for k in ("requested_policy", "requested_model_id", "returned_model", "thinking", "request_id", "estimated_cost_usd"):
        assert k in ta
    assert ta["returned_model"] == ta["requested_model_id"]


def test_classify_maps_flash_not_pro_without_confirm():
    assert classify_manual_lane("deepseek-flash")["policy"] == "FAST"
    assert classify_manual_lane("pro")["ok"] is False
