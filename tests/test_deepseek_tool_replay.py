"""Tool-call reasoning_content replay tests (mocked)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deepseek_client as dc  # noqa: E402


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: ("k", "deepseek_tradeai", False))


def test_continue_preserves_reasoning_content(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        r = MagicMock()
        r.status_code = 200
        r.headers = {}
        body = {
            "model": "deepseek-v4-pro",
            "choices": [{"message": {"content": "final answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 4},
        }
        r.content = json_mod.dumps(body).encode()
        r.json.return_value = body
        return r

    import json as json_mod
    monkeypatch.setattr(dc.requests, "post", fake_post)

    asst = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "internal-reason-not-for-user",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":\"x\"}"}}],
    }
    tools = [{"role": "tool", "tool_call_id": "c1", "content": "{\"ok\":true}"}]
    resp = dc.continue_with_tool_results(
        policy="PRO_THINK",
        prior_messages=[{"role": "user", "content": "look up x"}],
        assistant_message=asst,
        tool_results=tools,
    )
    assert resp.ok
    msgs = captured["json"]["messages"]
    # user + assistant(with reasoning) + tool
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["reasoning_content"] == "internal-reason-not-for-user"
    assert msgs[1]["tool_calls"][0]["id"] == "c1"
    assert msgs[2]["role"] == "tool"
    # multi-tool
    assert captured["json"]["model"] == "deepseek-v4-pro"
    assert captured["json"]["thinking"]["type"] == "enabled"


def test_multiple_tool_results(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        r = MagicMock()
        r.status_code = 200
        r.headers = {}
        body = {
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
            "usage": {},
        }
        r.content = json_mod.dumps(body).encode()
        r.json.return_value = body
        return r

    import json as json_mod
    monkeypatch.setattr(dc.requests, "post", fake_post)
    asst = {
        "role": "assistant",
        "content": "",
        "reasoning_content": "r",
        "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "t1", "arguments": "{}"}},
            {"id": "b", "type": "function", "function": {"name": "t2", "arguments": "{}"}},
        ],
    }
    tools = [
        {"role": "tool", "tool_call_id": "a", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "content": "2"},
    ]
    dc.continue_with_tool_results(
        policy="FAST_THINK",
        prior_messages=[{"role": "user", "content": "q"}],
        assistant_message=asst,
        tool_results=tools,
    )
    assert len([m for m in captured["json"]["messages"] if m["role"] == "tool"]) == 2


def test_tool_loop_model_mismatch(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        r = MagicMock()
        r.status_code = 200
        r.headers = {}
        body = {
            "model": "deepseek-v4-flash",  # mismatch for PRO_THINK
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {},
        }
        r.content = json_mod.dumps(body).encode()
        r.json.return_value = body
        return r

    import json as json_mod
    monkeypatch.setattr(dc.requests, "post", fake_post)
    resp = dc.continue_with_tool_results(
        policy="PRO_THINK",
        prior_messages=[{"role": "user", "content": "q"}],
        assistant_message={"role": "assistant", "content": None, "reasoning_content": "r", "tool_calls": []},
        tool_results=[{"role": "tool", "tool_call_id": "c", "content": "ok"}],
    )
    assert resp.ok is False
    assert resp.error_class == dc.MISMATCHED_RETURNED_MODEL


def test_tool_timeout(monkeypatch):
    monkeypatch.setattr(dc.requests, "post", MagicMock(side_effect=dc.requests.Timeout()))
    resp = dc.continue_with_tool_results(
        policy="FAST_THINK",
        prior_messages=[{"role": "user", "content": "q"}],
        assistant_message={"role": "assistant", "reasoning_content": "r", "content": None, "tool_calls": []},
        tool_results=[{"role": "tool", "tool_call_id": "c", "content": "x"}],
    )
    assert resp.error_class == dc.TIMEOUT
