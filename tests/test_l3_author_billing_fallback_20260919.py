"""L3 author free-OAuth fallback when DeepSeek returns HTTP 402 / billing refuse."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.l3_judgment_author import (  # noqa: E402
    _is_billing_refused,
    run_author,
)
from scripts.lib.material_residual_gate import evaluate_material_residual_gate  # noqa: E402
from tests.helpers.l3_fixtures import (  # noqa: E402
    OFFPEAK_SUMMER_ET,
    SUBJECT_A,
    make_author_call_fn,
    make_author_json,
    make_grounded_input,
)


def _gate_and_grounded(**kwargs):
    raw = make_grounded_input(**kwargs)
    gate = evaluate_material_residual_gate(raw, now=OFFPEAK_SUMMER_ET)
    assert gate.proceed
    return raw, gate.to_dict()


def test_is_billing_refused_detects_http_402():
    assert _is_billing_refused({"error_class": "HTTP_402", "error_message": "Payment Required"})
    assert _is_billing_refused({"error_class": "PAYMENT_REQUIRED", "error_message": ""})
    assert not _is_billing_refused({"error_class": "RATE_LIMITED", "error_message": "429"})


def test_author_falls_back_to_chatgpt_on_deepseek_402():
    """M2 must not stay dark solely because DeepSeek billing refused."""
    primary = make_author_call_fn(ok=False, error_class="HTTP_402")
    fb_payload = make_author_json(subject_guid=SUBJECT_A)
    calls = {"n": 0}

    def _fb(**_kwargs):
        calls["n"] += 1
        class Resp:
            pass

        import json

        resp = Resp()
        resp.ok = True
        resp.content = json.dumps(fb_payload)
        resp.requested_model_id = "chatgpt"
        resp.returned_model = "chatgpt"
        resp.error_class = None
        resp.error_message = None
        resp.latency_ms = 9
        resp.estimated_cost_usd = 0.0
        resp.cost_basis = "free_oauth"
        resp.pricing_tier = "oauth"
        resp.cache_hit = False
        resp.request_id = None
        resp.usage = None
        return resp

    grounded, gate = _gate_and_grounded(subject_guid=SUBJECT_A)
    out = run_author(
        grounded=grounded,
        gate=gate,
        call_fn=primary,
        fallback_call_fn=_fb,
        now=OFFPEAK_SUMMER_ET,
    )
    assert out.get("ok") is True, out
    assert out.get("author_fallback_used") is True
    assert out.get("provider") == "chatgpt"
    assert out.get("provider_calls") == 2
    assert calls["n"] == 1


def test_author_does_not_fallback_on_non_billing_error():
    primary = make_author_call_fn(ok=False, error_class="RATE_LIMITED")
    fb_calls: list[int] = []

    def _fb(**_k):
        fb_calls.append(1)
        raise AssertionError("fallback must not run for non-billing errors")

    grounded, gate = _gate_and_grounded(subject_guid=SUBJECT_A)
    out = run_author(
        grounded=grounded,
        gate=gate,
        call_fn=primary,
        fallback_call_fn=_fb,
        now=OFFPEAK_SUMMER_ET,
    )
    assert out.get("ok") is False
    assert out.get("author_fallback_used") is not True
    assert fb_calls == []


def test_default_free_oauth_chain_tries_grok_after_chatgpt_fails(monkeypatch):
    """Measured: ChatGPT CODEX_HEADLESS_UNAVAILABLE while DeepSeek is 402."""
    from scripts.lib import l3_judgment_author as author_mod

    calls: list[str] = []

    def _fake_lane(lane: str, **_kwargs):
        calls.append(lane)
        if lane == "chatgpt":
            return {
                "ok": False,
                "content": None,
                "requested_model_id": "chatgpt",
                "returned_model": None,
                "error_class": "FREE_AUTHOR_FALLBACK_FAILED",
                "error_message": "RuntimeError: CODEX_HEADLESS_UNAVAILABLE",
                "latency_ms": None,
                "cost_usd": 0.0,
            }
        import json

        payload = make_author_json(subject_guid=SUBJECT_A)
        return {
            "ok": True,
            "content": json.dumps(payload),
            "requested_model_id": "grok",
            "returned_model": "grok",
            "error_class": None,
            "error_message": None,
            "latency_ms": 11,
            "cost_usd": 0.0,
            "cost_basis": "free_oauth",
            "pricing_tier": "oauth",
        }

    monkeypatch.setattr(author_mod, "_free_oauth_lane_author_call", _fake_lane)
    chain = author_mod._default_free_oauth_author_call(prompt="x", response_json=True)
    assert chain.get("ok") is True
    assert chain.get("requested_model_id") == "grok"
    assert calls == ["chatgpt", "grok"]

    # Full author path: DeepSeek 402 → free-oauth chain → grok.
    primary = make_author_call_fn(ok=False, error_class="HTTP_402")
    monkeypatch.setattr(author_mod, "_default_deepseek_call", primary)
    grounded, gate = _gate_and_grounded(subject_guid=SUBJECT_A)
    out = run_author(
        grounded=grounded,
        gate=gate,
        call_fn=None,
        fallback_call_fn=None,  # triggers _default_free_oauth_author_call
        now=OFFPEAK_SUMMER_ET,
    )
    assert out.get("ok") is True, out
    assert out.get("author_fallback_used") is True
    assert out.get("provider") == "grok"
    assert calls.count("chatgpt") >= 2 and calls.count("grok") >= 2
