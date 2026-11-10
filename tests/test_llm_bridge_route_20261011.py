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
        return {"choices": [{"message": {"content": "advisory"}}], "_tradeai": {"process_id": process_id, "governance_pass": True, "mock": True}}

    monkeypatch.setattr(llm_bridge_route, "_call_bridge", fake_call)
    assert llm_bridge_route.text_via_bridge("hermes_usefulness_score", "hello") == "advisory"


def test_text_and_provenance_via_bridge_returns_the_executor(monkeypatch):
    """LQ-1808: a caller storing `model` needs the provider that ran, not the one it asked for."""
    block = {"process_id": "hermes_external_research", "governance_pass": True, "mock": True,
             "provider": "anthropic", "model_id": "claude-haiku-5-5"}

    def fake_call(messages, *, process_id, timeout_s):
        return {"choices": [{"message": {"content": "advisory"}}], "_tradeai": block}

    monkeypatch.setattr(llm_bridge_route, "_call_bridge", fake_call)

    text, provenance = llm_bridge_route.text_and_provenance_via_bridge(
        "hermes_external_research", "hello")

    assert text == "advisory"
    assert provenance["provider"] == "anthropic"
    assert provenance["model_id"] == "claude-haiku-5-5"


def test_text_and_provenance_via_bridge_claims_nothing_when_refused(monkeypatch):
    monkeypatch.setattr(llm_bridge_route, "_call_bridge",
                        lambda *_a, **_kw: {"error": {"code": "COST_CAP_EXCEEDED"}})

    text, provenance = llm_bridge_route.text_and_provenance_via_bridge(
        "hermes_external_research", "hello")

    assert text is None
    assert provenance == {}, "a refusal must not carry a provider/model claim"


def test_llm_lane_forwards_return_provenance_to_the_gate(monkeypatch):
    """LQ-1808: the flag used to be dropped on the gate path, so callers got a bare string."""
    from scripts import llm_lane
    # llm_lane imports its dependency by the bare `lib.…` name (scripts/ is on sys.path), which is a
    # DIFFERENT module object from `scripts.lib.…`. Patch the one the code under test will import.
    import lib.llm_consumption as llm_consumption

    seen = {}

    def fake_gate(prompt, **kw):
        seen.update(kw)
        return prompt, {"_tradeai": {"provider": "deepseek"}}

    monkeypatch.delenv("TRADEAI_LLM_VIA_BRIDGE", raising=False)
    monkeypatch.setattr(llm_consumption, "gate_and_generate", fake_gate)

    out = llm_lane.generate(
        "hello",
        lane="deepseek-flash",
        process_id="hermes_external_research",
        return_provenance=True,
    )

    assert seen.get("return_provenance") is True
    assert out == ("hello", {"_tradeai": {"provider": "deepseek"}})


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
    # LQ-1808: the lane asks for the bridge's provenance too, so the helper's name gained the
    # `and_provenance` form. Either is the same route; what must not change is that it is the
    # bridge path and that a refusal is raised rather than falling through to a provider.
    assert "_via_bridge" in body_src
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
