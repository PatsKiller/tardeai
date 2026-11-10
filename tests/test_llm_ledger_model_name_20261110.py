"""LQ-20261107-1808 r2 must-fix 2 — a raising call names the model it attempted, not NULL.

Measured read-only on 2026-11-10 (``REVIEW-LQ1825-25152d18b.md``), the last 7 days of
``llm_consumption_log`` for ``hermes_external_research``:

    deepseek-flash NULL  false  34   ← names no executor at all (PROVIDER_5XX, HTTP_402)

Cause: ``gate_and_generate`` logged ``model_name = returned_model or requested_model_id or model``. A call
that RAISED has neither returned nor requested model in its (empty) provenance, and this lane's caller never
passed ``model`` — so the ledger column was None. The gate had already RESOLVED the provider model id before
it attempted anything (``POLICY_TO_MODEL`` / ``deepseek_model_id``); it simply did not log it.

These pins drive the real ``gate_and_generate`` with a synthetic process row and a fake provider client —
no network, no key, no database — and assert what the log call receives.
"""
from __future__ import annotations

import contextlib
import sys
import types

import pytest

# No ``sys.path`` edit here: ``tests/conftest.py`` already puts the repo root and ``scripts/`` on it. Inserting
# ``scripts/lib`` (as an earlier draft did) made the bare name ``research_lane_health`` resolve to
# ``scripts/lib/research_lane_health.py`` for every later test in the session, so the CLI module of the same
# name lost its ``fix_hint``/``STATUS_PATH`` and tests/test_research_lane_health_alert.py failed by TEST ORDER.
import scripts.lib.llm_consumption as lc  # noqa: E402

PROCESS = "hermes_external_research"
CFG = {
    "process_id": PROCESS,
    "process_name": "Hermes External Research (DeepSeek)",
    "category": "Hermes",
    "mode": "automated",
    "allowed_lanes": ["fast", "deepseek-flash", "grok", "chatgpt"],
    "deepseek_allowed_policies": ["FAST", "PRO_THINK"],
    "max_input_tokens": 16000,
    "max_output_tokens": 4096,
    "daily_soft_cap": 600,
    "daily_cost_cap_usd": 0.3,
    "registered": True,
    "anthropic_first": False,
    "reasoning_tier": "standard",
    "local_only": False,
    "tools_allowed": False,
    "fallback_allowed": False,
    "advisory_only": True,
}


@contextlib.contextmanager
def _noop_attribution(**_kw):
    yield {}


def _fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _wire(monkeypatch, *, generate):
    """Every side effect gate_and_generate performs, except the log call we are pinning."""
    logged: dict = {}

    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "5")
    monkeypatch.delenv("LLM_DEFER_OFFPEAK", raising=False)

    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "automated"})
    monkeypatch.setattr(lc, "get_process_config", lambda process_id: dict(CFG))
    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(lc, "reserve_projected_cost", lambda *a, **k: "res-test")
    monkeypatch.setattr(lc, "settle_reservation", lambda *a, **k: None)
    monkeypatch.setattr(lc, "log_call", lambda **kw: logged.update(kw))
    # gate_and_generate imports llm_lane inside the function; patch the module object that import sees.
    import llm_lane as _llm_lane_mod  # scripts/ is on sys.path
    monkeypatch.setattr(_llm_lane_mod, "generate", generate)

    monkeypatch.setitem(sys.modules, "memory_ring2",
                        _fake_module("memory_ring2", check=lambda *a, **k: {"decision": "ALLOW"},
                                     research_class=lambda *a, **k: False))
    monkeypatch.setitem(sys.modules, "model_chooser",
                        _fake_module("model_chooser", apply=lambda *a, **k: (None, {})))
    try:
        ctx = __import__("lib.provider_cost.context", fromlist=["cost_attribution"])
        monkeypatch.setattr(ctx, "cost_attribution", _noop_attribution)
    except Exception:  # noqa: BLE001 -- the function's own ImportError fallback is the same no-op
        pass
    try:
        crm = __import__("lib.consumption_run_manual", fromlist=["POLICY_TO_MODEL"])
        monkeypatch.setattr(crm, "validate_paid_cap_config", lambda *a, **k: None)
        monkeypatch.setattr(crm, "projected_max_cost_usd", lambda **k: 0.0001)
    except Exception:  # noqa: BLE001
        pass
    try:
        promo = __import__("lib.anthropic_routing", fromlist=["active"])
        monkeypatch.setattr(promo, "anthropic_only", lambda *a, **k: False)
        monkeypatch.setattr(promo, "active", lambda *a, **k: False)
    except Exception:  # noqa: BLE001
        pass
    return logged


def _resolved_fast_id() -> str:
    from lib.llm_model_registry import deepseek_model_id

    return deepseek_model_id("FAST")


def _run(monkeypatch, *, generate, model=None):
    logged = _wire(monkeypatch, generate=generate)
    with pytest.raises(RuntimeError, match="PROVIDER_5XX"):
        lc.gate_and_generate("hello", lane="deepseek-flash", process_id=PROCESS, model=model,
                             max_tokens=16, timeout=1, metadata={})
    return logged


# ── the defect: a raising call logged NULL ────────────────────────────────────────────────────────────────


def test_a_raising_deepseek_call_names_the_model_that_was_attempted(monkeypatch):
    def raise_5xx(*_a, **_k):
        raise RuntimeError("PROVIDER_5XX: simulated upstream failure")

    logged = _run(monkeypatch, generate=raise_5xx)

    assert logged["success"] is False
    assert logged["model_name"] == _resolved_fast_id()          # not None
    assert logged["lane"] == "deepseek-flash" and logged["process_id"] == PROCESS


def test_the_id_is_the_registry_resolved_id_even_when_the_alias_coincides(monkeypatch):
    """The registry's FAST id happens to be the string `deepseek-flash`; the point is that it is the id
    the gate RESOLVED and attempted, recorded on a call that never returned one."""

    def raise_5xx(*_a, **_k):
        raise RuntimeError("PROVIDER_5XX: simulated")

    logged = _run(monkeypatch, generate=raise_5xx)
    assert logged["model_name"] == _resolved_fast_id()
    assert str(logged["model_name"]).strip() != ""


# ── the precedence it must not disturb ───────────────────────────────────────────────────────────────────


def test_a_completed_call_still_names_what_the_provider_returned(monkeypatch):
    def answered(*_a, **_k):
        return "the answer", {"_tradeai": {"returned_model": "claude-haiku-5-5",
                                           "requested_model_id": "deepseek-v4-flash"}}

    logged = _run_ok(monkeypatch, generate=answered)
    assert logged["model_name"] == "claude-haiku-5-5"


def test_an_explicit_model_is_still_what_the_row_names_when_nothing_returned(monkeypatch):
    def raise_5xx(*_a, **_k):
        raise RuntimeError("PROVIDER_5XX: simulated")

    logged = _run(monkeypatch, generate=raise_5xx, model="deepseek-v4-flash")
    assert logged["model_name"] == "deepseek-v4-flash"


def _run_ok(monkeypatch, *, generate):
    logged = _wire(monkeypatch, generate=generate)
    lc.gate_and_generate("hello", lane="deepseek-flash", process_id=PROCESS,
                         max_tokens=16, timeout=1, metadata={})
    return logged
