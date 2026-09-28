"""Ring 2 (01 §2): SHADOW records misses, ENFORCED refuses; the process-current context threads through."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import memory_ring2 as r2  # noqa: E402
import intelligence_client as ic  # noqa: E402


def _policy(tmp_path, default="SHADOW", surfaces=None):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"ring2": {"default": default, "surfaces": surfaces or {}}}))
    return {"TRADEAI_MEMORY_INFLUENCE_POLICY": str(p), "TRADEAI_MEMORY_CONTEXTS_PATH": str(tmp_path / "ctx.jsonl")}


def test_mode_resolution_precedence(tmp_path):
    env = _policy(tmp_path, "SHADOW", {"create_action": "ENFORCED"})
    assert r2.mode_for("gate_and_generate", env) == "SHADOW" and r2.mode_for("create_action", env) == "ENFORCED"
    assert r2.mode_for("create_action", {**env, "TRADEAI_INTELLIGENCE_MODE": "shadow"}) == "SHADOW"
    assert r2.mode_for("x", {"TRADEAI_MEMORY_INFLUENCE_POLICY": "/nonexistent"}) == "SHADOW"


def test_research_class_declared_or_by_category():
    assert r2.research_class("p", {"memory_context_required": True}) and not r2.research_class("p", {"memory_context_required": False})
    assert r2.research_class("p", {"category": "Hermes"}) and not r2.research_class("p", {"category": "Trading"})


def test_shadow_allows_and_records_miss(tmp_path):
    env = _policy(tmp_path)
    out = r2.check("gate_and_generate", "hermes_external_research", None, env=env)
    assert out["decision"] == "ALLOW_MISS"
    rows = [json.loads(l) for l in (tmp_path / "ctx.jsonl").read_text().splitlines()]
    assert rows[-1]["schema"] == "Ring2Decision@v1" and rows[-1]["event"] == "MISS" and rows[-1]["surface"] == "gate_and_generate"
    assert r2.check("gate_and_generate", "p", "ctx_abc", env=env)["decision"] == "ALLOW"
    assert r2.check("gate_and_generate", "p", None, required=False, env=env)["decision"] == "ALLOW"


def test_enforced_refuses_and_records_refusal(tmp_path):
    env = _policy(tmp_path, "ENFORCED")
    with pytest.raises(r2.MemoryContextRequired):
        r2.check("create_action", "actor:alex", None, env=env)
    rows = [json.loads(l) for l in (tmp_path / "ctx.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "REFUSED" and rows[-1]["disposition"] == "HOLD_MEMORY_CONTEXT_REQUIRED"
    assert r2.check("create_action", "actor:alex", "ctx_1", env=env)["decision"] == "ALLOW"


def test_current_context_threads_and_clears(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_MEMORY_CONTEXTS_PATH", str(tmp_path / "c.jsonl"))
    monkeypatch.setenv("TRADEAI_RETRIEVAL_RECEIPTS_PATH", str(tmp_path / "r.jsonl"))
    assert ic.current_context_id() is None
    ctx = {"context_id": "ctx_t", "retrieval_receipt": "rr_t", "actor": {"lane_id": "l"}, "subjects": [], "mode": "SHADOW"}
    ic.set_current_context(ctx)
    assert ic.current_context_id() == "ctx_t" and ic.current_retrieval_receipt_id() == "rr_t"
    ic.shadow_commit(ctx, {"kind": "RESEARCHED", "ref": "x"})
    assert ic.current_context_id() is None


def test_create_action_carries_context_and_refuses_in_enforced(tmp_path, monkeypatch):
    import cio_action_ledger as cal
    monkeypatch.setenv("TRADEAI_MEMORY_CONTEXTS_PATH", str(tmp_path / "c.jsonl"))
    led = cal.CIOActionLedger(path=tmp_path / "ledger.jsonl") if "path" in cal.CIOActionLedger.__init__.__code__.co_varnames else cal.CIOActionLedger(tmp_path / "ledger.jsonl")
    monkeypatch.setenv("TRADEAI_INTELLIGENCE_MODE", "SHADOW")
    ev = led.create_action({"cio_action_id": "act_1", "title": "t", "context_id": "ctx_9"}, "alex", "agent")
    payload = ev.get("payload") or ev
    assert payload.get("context_id") == "ctx_9" and payload.get("memory_context_miss") is False
    monkeypatch.setenv("TRADEAI_INTELLIGENCE_MODE", "ENFORCED")
    with pytest.raises(r2.MemoryContextRequired):
        led.create_action({"cio_action_id": "act_2", "title": "t"}, "alex", "agent")


def test_accept_research_result_refuses_in_enforced(tmp_path, monkeypatch):
    import research_thesis_delta as rtd
    monkeypatch.setenv("TRADEAI_INTELLIGENCE_MODE", "ENFORCED")
    monkeypatch.setenv("TRADEAI_MEMORY_CONTEXTS_PATH", str(tmp_path / "c.jsonl"))
    out = rtd.accept_research_result("V", {"summary": "x", "answers": []}, prompt_context={}, research_id="res_1", root=tmp_path)
    assert out["ok"] is False and out["refused"] is True and out["refusal_reason"] == "MEMORY_CONTEXT_MISSING"
