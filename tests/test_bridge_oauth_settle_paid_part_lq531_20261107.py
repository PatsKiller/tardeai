"""LQ-20261107-531 (anchor BRIDGE_OAUTH_SETTLE_PAID_PART_LQ531): the bridge settles an OAuth-served call at $0.

Before: Step 9 settled every OAuth-served call at its DeepSeek projection (actual cost None -> projected_fallback),
so free grok/chatgpt answers were charged against the per-process daily caps as paid calls. On 2026-11-07
due_diligence_questions hit its $0.25 cap on 65 such reservations while the consumption log billed them $0.

After: the reservation still holds the projection while the call is in flight; it settles at the real paid part:
  * OAuth served, nothing paid before it                    -> 0.0
  * OAuth served after a rejected, metered paid answer      -> that metered amount
  * OAuth served after a paid attempt of unknown cost
    (timeout / network error, or an unpriced rejected answer) -> None (the projection, as before)
  * DeepSeek served                                          -> the registry estimate
  * DeepSeek served with no estimate                         -> None (the projection)
No cap value changes. Hermetic: the fixtures of tests/test_bridge_oauth_llm_step_20261014.py and
tests/test_n8n_oauth_first_routing_20261015.py (fake transports, patched ledger). No network, DB or key.
"""

from __future__ import annotations

import json

from tests.test_bridge_oauth_llm_step_20261014 import (  # noqa: F401 — `hermetic` is autouse: it must be in scope
    VALID,
    FakeDeepSeek,
    FakeResp,
    Proxy,
    StalledDeepSeek,
    hermetic,
    json_call,
    ok_body,
    wire,
)
from tests.test_n8n_oauth_first_routing_20261015 import call, grok_ok, ledger, outcomes, receipts

DEEP = dict(VALID, confidence=0.95, cause="reasoned cause")


def _settled(led):
    assert led["settle"].call_count == 1
    return led["settle"].call_args.args[1], led["settle"].call_args.kwargs


def test_oauth_served_settles_at_zero(monkeypatch):
    wire(monkeypatch, grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek("unused"))
    with ledger(monkeypatch) as led:
        out = call()
    assert "error" not in out, out.get("error")
    assert outcomes(out) == [("grok", "ok")]
    amount, kw = _settled(led)
    assert amount == 0.0 and kw["ok"] is True and kw["projected_fallback"] == 0.002
    # the reservation still held the projection while the call was in flight
    assert led["reserve"].call_count == 1
    # receipts are unchanged: OAuth stays "unknown" / free_oauth_unmetered
    assert receipts(out)[0]["cost_usd"] == "unknown" and receipts(out)[0]["cost_basis"] == "free_oauth_unmetered"


def test_chatgpt_served_after_grok_failure_settles_at_zero(monkeypatch):
    chat = Proxy("chatgpt", FakeResp(200, ok_body(json.dumps(VALID), "gpt-6.1-sol")))
    wire(monkeypatch, Proxy("grok", FakeResp(502)), chat, FakeDeepSeek("unused"))
    with ledger(monkeypatch) as led:
        out = call()
    assert outcomes(out) == [("grok", "serving_failure"), ("chatgpt", "ok")]
    assert _settled(led)[0] == 0.0


def test_oauth_after_a_rejected_paid_answer_settles_at_the_metered_amount(monkeypatch):
    # reasoning_tier high walks DeepSeek first; its schema-invalid answer was billed, then grok serves
    ds = FakeDeepSeek(json.dumps({"cause": "x"}))
    wire(monkeypatch, grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch, reg_override={"reasoning_tier": "high"}) as led:
        out = call()
    assert outcomes(out)[:2] == [("deepseek", "output_invalid"), ("grok", "ok")]
    assert receipts(out)[0]["cost_usd"] == 0.0005
    assert _settled(led)[0] == 0.0005


def test_oauth_after_an_unpriced_rejected_paid_answer_keeps_the_projection(monkeypatch):
    ds = FakeDeepSeek(json.dumps({"cause": "x"}))
    wire(monkeypatch, grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch, reg_override={"reasoning_tier": "high"}) as led:
        monkeypatch.setattr("lib.llm_model_registry.estimate_usd_cost", lambda *_a, **_k: {"estimated_cost_usd": None})
        out = call()
    assert outcomes(out)[:2] == [("deepseek", "output_invalid"), ("grok", "ok")]
    assert receipts(out)[0]["cost_usd"] == "unknown"
    assert _settled(led)[0] is None  # a billed attempt of unknown cost is never settled as free


def test_oauth_after_a_possibly_billable_paid_timeout_keeps_the_projection(monkeypatch, hermetic):
    grok = Proxy("grok", FakeResp(200, ok_body(json.dumps({"summary": "g"}), "grok-3-mini")))
    wire(monkeypatch, grok, Proxy("chatgpt", FakeResp(500)), StalledDeepSeek(hermetic["clock"]))
    with ledger(monkeypatch) as led:
        out = json_call("hermes_cloud_json")
    assert outcomes(out) == [("deepseek", "timeout"), ("grok", "ok")]
    assert receipts(out)[0]["possibly_billable"] is True
    assert _settled(led)[0] is None


def test_deepseek_served_settles_at_the_registry_estimate(monkeypatch):
    wire(monkeypatch, Proxy("grok", FakeResp(502)), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek(json.dumps(VALID)))
    with ledger(monkeypatch) as led:
        out = call()
    assert outcomes(out)[-1] == ("deepseek", "ok")
    assert _settled(led)[0] == 0.0005


def test_deepseek_served_with_unknown_usage_settles_at_the_projection(monkeypatch):
    wire(monkeypatch, Proxy("grok", FakeResp(502)), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek(json.dumps(VALID)))
    with ledger(monkeypatch) as led:
        monkeypatch.setattr("lib.llm_model_registry.estimate_usd_cost", lambda *_a, **_k: {"estimated_cost_usd": None})
        out = call()
    assert outcomes(out)[-1] == ("deepseek", "ok")
    amount, kw = _settled(led)
    assert amount is None and kw["projected_fallback"] == 0.002


def test_deepseek_first_healthy_serve_is_unchanged(monkeypatch):
    wire(
        monkeypatch,
        Proxy("grok", FakeResp(500)),
        Proxy("chatgpt", FakeResp(500)),
        FakeDeepSeek(json.dumps({"summary": "ok"})),
    )
    with ledger(monkeypatch) as led:
        out = json_call("cio_plan_enrichment")
    assert outcomes(out) == [("deepseek", "ok")]
    assert _settled(led)[0] == 0.0005
