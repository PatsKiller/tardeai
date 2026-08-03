"""Mocked DeepSeek V4 provider matrix — exact request bodies and fail-closed behavior.

No live network. No secrets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deepseek_client as dc  # noqa: E402
from lib.llm_model_registry import (  # noqa: E402
    AmbiguousLegacyLane,
    RegistryError,
    reject_legacy_model_id,
    resolve_lane_alias,
    resolve_logical_policy,
)


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: ("test-key-not-real", "DEEPSEEK_API_KEY", False))


def _ok_payload(model: str, content: str = "ok", reasoning: str | None = None, finish: str = "stop", usage=None):
    msg = {"role": "assistant", "content": content}
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return {
        "model": model,
        "choices": [{"message": msg, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _capture_post(monkeypatch, *, status=200, payload=None, raise_exc=None, text_body=None):
    import json as json_mod
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        if raise_exc:
            raise raise_exc
        r = MagicMock()
        r.status_code = status
        r.headers = {"x-request-id": "req-test-1"}
        if text_body is not None:
            r.content = text_body.encode() if isinstance(text_body, str) else text_body
            r.json.side_effect = json_mod.JSONDecodeError("x", "d", 0)
        else:
            body = payload if payload is not None else _ok_payload(json["model"])
            raw = json_mod.dumps(body).encode()
            r.content = raw
            r.json.return_value = body
        return r

    monkeypatch.setattr(dc.requests, "post", fake_post)
    return captured


# ── Policy → request body ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "policy,model,thinking_type,effort,has_temp",
    [
        ("FAST", "deepseek-v4-flash", "disabled", None, True),
        ("FAST_THINK", "deepseek-v4-flash", "enabled", "high", False),
        ("PRO", "deepseek-v4-pro", "disabled", None, True),
        ("PRO_THINK", "deepseek-v4-pro", "enabled", "high", False),
        ("PRO_MAX", "deepseek-v4-pro", "enabled", "max", False),
    ],
)
def test_policy_request_body(monkeypatch, policy, model, thinking_type, effort, has_temp):
    captured = _capture_post(monkeypatch, payload=_ok_payload(model))
    conf = policy == "PRO_MAX"
    resp = dc.chat(policy=policy, prompt="hello", operator_confirmed=conf)
    assert resp.ok is True
    body = captured["json"]
    assert body["model"] == model
    assert body["thinking"] == {"type": thinking_type}
    if effort:
        assert body.get("reasoning_effort") == effort
    else:
        assert "reasoning_effort" not in body
    if has_temp:
        assert "temperature" in body
    else:
        assert "temperature" not in body
    assert resp.requested_model_id == model
    assert resp.returned_model == model
    assert resp.requested_policy == policy
    assert resp.executed_policy == policy


def test_pro_max_blocked_without_confirmation():
    with pytest.raises(RegistryError, match="operator"):
        resolve_logical_policy("PRO_MAX", operator_confirmed=False)


def test_pro_max_allowed_with_confirmation(monkeypatch):
    captured = _capture_post(monkeypatch, payload=_ok_payload("deepseek-v4-pro"))
    resp = dc.chat(policy="PRO_MAX", prompt="x", operator_confirmed=True)
    assert resp.ok
    assert captured["json"]["reasoning_effort"] == "max"


def test_ambiguous_deepseek_v4():
    with pytest.raises(AmbiguousLegacyLane):
        resolve_lane_alias("deepseek-v4")


def test_legacy_model_ids_rejected():
    for mid in ("deepseek-chat", "deepseek-reasoner"):
        with pytest.raises(RegistryError):
            reject_legacy_model_id(mid)


def test_returned_model_mismatch(monkeypatch):
    _capture_post(monkeypatch, payload=_ok_payload("deepseek-v4-flash"))  # wrong for PRO
    resp = dc.chat(policy="PRO", prompt="x")
    assert resp.ok is False
    assert resp.error_class == dc.MISMATCHED_RETURNED_MODEL


def test_unknown_lane_no_gemma():
    import llm_lane
    with pytest.raises(RuntimeError, match="UNKNOWN_LANE"):
        llm_lane.generate("hi", lane="not-a-provider", _skip_consumption=True)


def test_deepseek_failure_not_another_provider(monkeypatch):
    """DeepSeek 500 must not return Grok/ChatGPT text."""
    import llm_lane

    def boom(*a, **k):
        raise RuntimeError("PROVIDER_5XX: boom")

    monkeypatch.setattr(llm_lane, "_deepseek_generate", boom)
    with pytest.raises(RuntimeError, match="PROVIDER_5XX|boom"):
        llm_lane.generate("hi", lane="fast", _skip_consumption=True)


# ── HTTP error classes ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status,code",
    [(401, dc.AUTH_INVALID), (403, dc.AUTH_INVALID), (404, dc.MODEL_NOT_FOUND),
     (429, dc.RATE_LIMITED), (500, dc.PROVIDER_5XX), (502, dc.PROVIDER_5XX)],
)
def test_http_error_classes(monkeypatch, status, code):
    _capture_post(monkeypatch, status=status, payload={"error": "x"})
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.ok is False
    assert resp.error_class == code
    assert resp.http_status == status


def test_timeout(monkeypatch):
    _capture_post(monkeypatch, raise_exc=dc.requests.Timeout())
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.TIMEOUT


def test_network_error(monkeypatch):
    _capture_post(monkeypatch, raise_exc=dc.requests.ConnectionError("down"))
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.NETWORK_ERROR


def test_invalid_response_json(monkeypatch):
    _capture_post(monkeypatch, text_body="not-json{")
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.JSON_INVALID


def test_empty_content(monkeypatch):
    _capture_post(monkeypatch, payload=_ok_payload("deepseek-v4-flash", content=""))
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.ok is False
    assert resp.error_class == dc.EMPTY_CONTENT


def test_finish_reason_length(monkeypatch):
    _capture_post(
        monkeypatch,
        payload=_ok_payload("deepseek-v4-flash", content="partial", finish="length"),
    )
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.OUTPUT_TRUNCATED


def test_missing_usage_still_ok_when_content(monkeypatch):
    payload = _ok_payload("deepseek-v4-flash", content="hello")
    payload["usage"] = {}
    _capture_post(monkeypatch, payload=payload)
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.ok is True
    assert resp.usage == {}


def test_auth_missing(monkeypatch):
    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: (None, None, False))
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.AUTH_MISSING


def test_json_mode_sets_response_format(monkeypatch):
    captured = _capture_post(monkeypatch, payload=_ok_payload("deepseek-v4-flash", content='{"ok":true}'))
    dc.chat(policy="FAST", prompt="return json", response_json=True)
    assert captured["json"].get("response_format") == {"type": "json_object"}


def test_non_thinking_has_no_reasoning_effort(monkeypatch):
    captured = _capture_post(monkeypatch, payload=_ok_payload("deepseek-v4-flash"))
    dc.chat(policy="FAST", prompt="x")
    assert "reasoning_effort" not in captured["json"]
    assert captured["json"]["thinking"]["type"] == "disabled"
