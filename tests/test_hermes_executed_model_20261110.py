"""LQ-20261107-1808 item 3 — ``hermes_external_research.model`` names the executor, not the request.

The BEFORE evidence: over the 24 h to 2026-11-10T18:00Z every ``hermes_external_research`` row in this lane
carried ``model='deepseek-flash'``, while the gate's own ledger shows the calls ran on ``claude-haiku-5-5``.
The column was the CLI default, written by the caller, and it could not disagree with itself. These tests pin
the replacement: the row records what the lane's provenance says RAN, and falls back to the requested model
only when the lane recorded nothing at all (never silently upgrading an unknown into a claim).

Synthetic only: no provider, no network, no database.
"""
from __future__ import annotations

import importlib

import pytest

import scripts.hermes_external_researcher as her


# ── executed_model: the precedence, one case per evidence source ───────────────────────────────────────────


def test_no_provenance_keeps_the_requested_model():
    """A call that recorded nothing is stored as requested — an unknown is not dressed up as an executor."""
    assert her.executed_model(None, "deepseek-flash") == "deepseek-flash"
    assert her.executed_model({}, "deepseek-flash") == "deepseek-flash"


def test_non_dict_provenance_is_ignored():
    assert her.executed_model("claude-haiku-5-5", "deepseek-flash") == "deepseek-flash"
    assert her.executed_model(["anthropic"], "deepseek-flash") == "deepseek-flash"


def test_bridge_provenance_names_the_provider_and_the_model():
    """The CIO-governed bridge answers with ``provider`` + ``model_id``; that is what the row must say."""
    prov = {"provider": "anthropic", "model_id": "claude-haiku-5-5",
            "requested_policy": "deepseek_only", "route_receipts": []}
    assert her.executed_model(prov, "deepseek-flash") == "anthropic:claude-haiku-5-5"


def test_a_provider_already_in_the_model_name_is_not_prefixed_twice():
    assert her.executed_model({"provider": "deepseek", "model_id": "deepseek-flash"},
                              "deepseek-flash") == "deepseek-flash"
    assert her.executed_model({"provider": "Anthropic", "model_id": "anthropic/claude-haiku-5-5"},
                              "deepseek-flash") == "anthropic/claude-haiku-5-5"


def test_gate_provenance_uses_returned_model_and_never_a_policy_as_the_provider():
    """The gate records ``returned_model`` and policy names; a policy is a routing rule, not a provider."""
    prov = {"returned_model": "claude-haiku-5-5", "requested_model_id": "deepseek-v4-flash",
            "requested_policy": "deepseek_only", "executed_policy": "deepseek_only"}
    assert her.executed_model(prov, "deepseek-flash") == "claude-haiku-5-5"


def test_requested_model_id_is_the_last_recorded_evidence():
    """The gate asked the provider for this model and recorded it, even when it did not record a return."""
    assert her.executed_model({"requested_model_id": "deepseek-v4-flash"},
                              "deepseek-flash") == "deepseek-v4-flash"


def test_a_provenance_block_with_no_model_falls_back_to_the_request():
    assert her.executed_model({"usage": {}, "executed_policy": "deepseek_only"},
                              "deepseek-flash") == "deepseek-flash"


# ── call_governed_deepseek: the flag reaches the gate and the pair comes back ───────────────────────────────


def _fake_generate(monkeypatch, result):
    seen = {}

    def generate(prompt, **kwargs):
        seen["prompt"] = prompt
        seen.update(kwargs)
        return result

    monkeypatch.setattr(her, "_import_llm_generate", lambda: generate)
    monkeypatch.setattr(her, "_account_from_env", lambda *a, **k: None)
    return seen


def test_call_governed_deepseek_returns_the_gates_provenance_when_asked(monkeypatch):
    gate_prov = {"returned_model": "claude-haiku-5-5", "requested_policy": "deepseek_only"}
    seen = _fake_generate(monkeypatch, ("  the answer  ", gate_prov))
    text, prov = her.call_governed_deepseek("deepseek-flash", "prompt", return_provenance=True)
    assert text == "the answer"
    assert prov == gate_prov
    assert seen["return_provenance"] is True
    assert seen["lane"] == "deepseek-flash" and seen["process_id"] == "hermes_external_research"


def test_call_governed_deepseek_stays_a_string_by_default(monkeypatch):
    """Every existing caller (DDQ, inference_hermes_query) unpacks one value; that contract cannot move."""
    seen = _fake_generate(monkeypatch, "  the answer  ")
    assert her.call_governed_deepseek("deepseek-flash", "prompt") == "the answer"
    assert seen["return_provenance"] is False


def test_call_governed_deepseek_degrades_a_pair_to_text_by_default(monkeypatch):
    """A lane that answers with a pair anyway must not turn the default path into a triple."""
    _fake_generate(monkeypatch, ("the answer", {"returned_model": "x"}))
    assert her.call_governed_deepseek("deepseek-flash", "prompt") == "the answer"


def test_executed_model_of_the_gate_pair_records_the_fallback_provider(monkeypatch):
    """End to end through the governed path: requested deepseek-flash, executed claude-haiku-5-5."""
    gate_prov = {"returned_model": "claude-haiku-5-5", "requested_model_id": "deepseek-flash",
                 "requested_policy": "deepseek_only", "fallback_used": True}
    _fake_generate(monkeypatch, ("the answer", gate_prov))
    monkeypatch.setattr(her, "via_bridge", lambda: False)
    text, prov = her.call_external("deepseek", "deepseek-flash", "prompt", return_provenance=True)
    assert text == "the answer"
    assert her.executed_model(prov, "deepseek-flash") == "claude-haiku-5-5"


# ── call_external: every route answers with the same pair shape ────────────────────────────────────────────


def test_a_direct_provider_client_claims_no_provenance(monkeypatch):
    monkeypatch.setattr(her, "via_bridge", lambda: False)
    monkeypatch.setattr(her, "_call_direct", lambda cfg, model, prompt, max_tokens: "text")
    model, prov = her.call_external("claude", "claude-haiku-5-5", "prompt", return_provenance=True)
    assert (model, prov) == ("text", None)


def test_a_direct_provider_client_still_returns_bare_text_by_default(monkeypatch):
    monkeypatch.setattr(her, "via_bridge", lambda: False)
    monkeypatch.setattr(her, "_call_direct", lambda cfg, model, prompt, max_tokens: "text")
    assert her.call_external("claude", "claude-haiku-5-5", "prompt") == "text"


def test_the_bridge_route_returns_the_bridge_block(monkeypatch):
    monkeypatch.setattr(her, "via_bridge", lambda: True)
    monkeypatch.setattr(her, "_account_from_env", lambda *a, **k: None)
    block = {"provider": "anthropic", "model_id": "claude-haiku-5-5", "requested_policy": "deepseek_only"}
    route = importlib.import_module("lib.llm_bridge_route")
    monkeypatch.setattr(route, "text_and_provenance_via_bridge",
                        lambda process_id, prompt, **kw: ("{}", block))
    text, prov = her.call_external("grok", "m", "prompt", max_tokens=1234, return_provenance=True)
    assert text == "{}" and prov == block
    assert her.executed_model(prov, "deepseek-flash") == "anthropic:claude-haiku-5-5"


def test_a_bridge_refusal_raises_rather_than_storing_the_requested_model(monkeypatch):
    """No text means no claim: the row must not be written as if a model produced it."""
    monkeypatch.setattr(her, "via_bridge", lambda: True)
    monkeypatch.setattr(her, "_account_from_env", lambda *a, **k: None)
    route = importlib.import_module("lib.llm_bridge_route")
    monkeypatch.setattr(route, "text_and_provenance_via_bridge", lambda *a, **k: (None, {}))
    with pytest.raises(RuntimeError, match="BRIDGE_ROUTE_REFUSED"):
        her.call_external("grok", "m", "prompt", return_provenance=True)


# ── reconcile_accepted_research: the downstream payload repeats the same truth ─────────────────────────────


def _fake_reconcile_imports(monkeypatch):
    """Stand in for the two write-side modules so the payload can be inspected without touching a store."""
    import sys
    import types

    captured = {}

    def reassess_on_research_completed(payload, result, **kwargs):
        captured["result"] = result
        return {"ok": True}

    fake = types.ModuleType("lib.cio_product_reassessment")
    fake.reassess_on_research_completed = reassess_on_research_completed
    monkeypatch.setitem(sys.modules, "lib.cio_product_reassessment", fake)
    for name in ("research_write_path", "lib.research_write_path"):
        writer = types.ModuleType(name)
        writer.record_passthrough = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, name, writer)
    return captured


def test_reconcile_payload_names_the_executed_model(monkeypatch):
    import types

    captured = _fake_reconcile_imports(monkeypatch)
    args = types.SimpleNamespace(lane="deepseek", model="deepseek-flash", question="q")
    her.reconcile_accepted_research("AAPL", 7, {"classification": "CONFIRMS"},
                                    {"memberships": ["HELD"]}, args, "claude-haiku-5-5")
    assert captured["result"]["model"] == "claude-haiku-5-5"


def test_reconcile_payload_falls_back_to_the_request_when_nothing_recorded(monkeypatch):
    import types

    captured = _fake_reconcile_imports(monkeypatch)
    args = types.SimpleNamespace(lane="deepseek", model="deepseek-flash", question="q")
    her.reconcile_accepted_research("AAPL", 7, {"classification": "CONFIRMS"},
                                    {"memberships": ["HELD"]}, args)
    assert captured["result"]["model"] == "deepseek-flash"
