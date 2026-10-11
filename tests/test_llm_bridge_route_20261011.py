"""Bridge route stays off by default and never falls through to a provider.

Importing scripts.llm_lane reads the repo .env. These tests parse that file
and call only llm_bridge_route, with _call_bridge replaced. They do not open
a socket.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from scripts.lib import llm_bridge_route


ROOT = Path(__file__).resolve().parents[1]


def test_bridge_is_off_unless_the_env_says_so(monkeypatch):
    monkeypatch.delenv("TRADEAI_LLM_VIA_BRIDGE", raising=False)
    assert llm_bridge_route.bridge_enabled() is False
    monkeypatch.setenv("TRADEAI_LLM_VIA_BRIDGE", "on")
    assert llm_bridge_route.bridge_enabled() is True
    monkeypatch.setenv("TRADEAI_LLM_VIA_BRIDGE", "off")
    assert llm_bridge_route.bridge_enabled() is False


def test_text_via_bridge_returns_none_on_refusal(monkeypatch):
    def fake_call(messages, *, process_id, timeout_s):
        assert process_id == "topic_curator"
        assert messages[0]["content"] == "hello"
        return {"error": "refused", "governance_pass": False}

    monkeypatch.setattr(llm_bridge_route, "_call_bridge", fake_call)
    assert llm_bridge_route.text_via_bridge("topic_curator", "hello") is None


def test_text_via_bridge_returns_the_message(monkeypatch):
    def fake_call(messages, *, process_id, timeout_s):
        return {"choices": [{"message": {"content": "advisory"}}], "governance_pass": True}

    monkeypatch.setattr(llm_bridge_route, "_call_bridge", fake_call)
    assert llm_bridge_route.text_via_bridge("topic_curator", "hello") == "advisory"


def test_llm_lane_source_routes_only_when_the_flag_is_on():
    src = (ROOT / "scripts" / "llm_lane.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    generate = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "generate"
    )
    body_src = ast.get_source_segment(src, generate) or ""
    assert body_src.index("TRADEAI_LLM_VIA_BRIDGE") < body_src.index(
        "from lib.llm_consumption import gate_and_generate"
    )
    assert "text_via_bridge" in body_src
    assert "BRIDGE_ROUTE_REFUSED" in body_src


def test_direct_caller_manifest_lists_the_wave4_thirty_seven():
    body = json.loads((ROOT / "config" / "llm_direct_callers.json").read_text(encoding="utf-8"))
    assert body["bridge_default"] == "off"
    assert body["lane_count"] == 37
    assert len(body["lanes"]) == 37
    ids = {row["lane_id"] for row in body["lanes"]}
    assert "journal-review-builder" in ids
    assert "rag-indexer" in ids
    assert "topic-curator-at-30-9-13" in ids
