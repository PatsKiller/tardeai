"""Phase 10 — Failure injection: every provider failure must fail-soft.

READ_ONLY_ADVISORY. No broker/order/stop/2FA/risk-policy mutation, no network,
no live side effects, no secrets. Deterministic only.

KEY INVARIANT: no provider failure may create a false ACT_NOW. For every
injected failure below, the envelope's decision section must remain
non-actionable — ``canonical_act_now(decision)`` must stay ``False``.
"""
from __future__ import annotations

import builtins
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_context_envelope import (  # noqa: E402
    AUTHORITY_READ_ONLY_ADVISORY,
    RETRIEVAL_EMPTY,
    RETRIEVAL_ERROR,
    RETRIEVAL_UNAVAILABLE,
    get_context_for_agent,
    validate_context_envelope,
)
from scripts.lib.agent_context_integration import build_specialist_sub_envelope  # noqa: E402
from scripts.lib.agent_memory_governance import retrieve_for_context  # noqa: E402
from scripts.lib.agent_run_trace import append_trace, build_trace  # noqa: E402
from scripts.lib.cio_decision_semantics import canonical_act_now  # noqa: E402
from scripts.lib.mcp_provider_adapters import (  # noqa: E402
    build_external_not_configured_registry,
    build_local_provider_registry,
)
from scripts.lib.mcp_read_only_gateway import (  # noqa: E402
    MCP_READ_ONLY_STATUS_ERROR,
    MCP_READ_ONLY_STATUS_NOT_CONFIGURED,
    call_mcp_tool,
)

_TRACE_DIR = Path(tempfile.mkdtemp(prefix="agent_intel_fail_inj_"))


def _decision(action: str = "HOLD") -> dict:
    return {"decision_id": "dec_fail", "current_action": action, "act_now": False}


def _assert_act_now_unchanged(env: dict) -> None:
    """A provider failure must never flip the advisory decision actionable."""
    assert env["decision"]["act_now"] is False
    effective, _blocking = canonical_act_now(env["decision"])
    assert effective is False


# ── Broken memory providers (narrow duck-typed contract) ───────────────────


class _HealthRaises:
    name = "HealthRaisesMemory"

    def health(self):
        raise RuntimeError("vector store health endpoint down")

    def search(self, query=None, symbols=None, plan_id=None):
        raise AssertionError("search must not run when health raises")


class _Unavailable:
    name = "UnavailableMemory"

    def health(self):
        return False

    def search(self, query=None, symbols=None, plan_id=None):
        raise AssertionError("search must not run when health is False")


class _SearchRaises:
    name = "SearchRaisesMemory"

    def health(self):
        return True

    def search(self, query=None, symbols=None, plan_id=None):
        raise RuntimeError("vector store query failed")


class _MalformedSearch:
    name = "MalformedSearchMemory"

    def health(self):
        return True

    def search(self, query=None, symbols=None, plan_id=None):
        return "not a dict"


class _MalformedProvider:
    """For retrieve_for_context: health OK, search returns a non-dict."""

    name = "MalformedProvider"

    def health(self):
        return {"status": "OK"}

    def search(self, **kwargs):
        return "not a dict"


# ── Mem0 / vector store unavailable ────────────────────────────────────────


def test_memory_health_raises_fail_soft():
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_health"},
        decision=_decision(),
        memory_provider=_HealthRaises(),
    )
    assert env["episodic_memory"]["retrieval_status"] == RETRIEVAL_ERROR
    assert env["episodic_memory"].get("error") == "RuntimeError"
    assert env["episodic_memory"]["records"] == []
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


def test_memory_health_unavailable_fail_soft():
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_unavail"},
        decision=_decision(),
        memory_provider=_Unavailable(),
    )
    assert env["episodic_memory"]["retrieval_status"] == RETRIEVAL_UNAVAILABLE
    assert env["episodic_memory"]["records"] == []
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


def test_memory_search_raises_fail_soft():
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_search"},
        decision=_decision(),
        memory_provider=_SearchRaises(),
    )
    assert env["episodic_memory"]["retrieval_status"] == RETRIEVAL_ERROR
    assert env["episodic_memory"].get("error") == "RuntimeError"
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


def test_memory_malformed_search_fail_soft():
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_malformed"},
        decision=_decision(),
        memory_provider=_MalformedSearch(),
    )
    # A non-dict search result yields no records and never a false ACT_NOW.
    assert env["episodic_memory"]["retrieval_status"] in (
        RETRIEVAL_ERROR,
        RETRIEVAL_UNAVAILABLE,
        RETRIEVAL_EMPTY,
    )
    assert env["episodic_memory"]["records"] == []
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


# ── MCP unavailable ────────────────────────────────────────────────────────


def _mcp(tool: str, request=None, registry=None):
    return call_mcp_tool(
        wake_id="wake_fail",
        trace_id="tr_fail",
        agent="alex",
        tool=tool,
        provider=tool.split(".")[0],
        request=request or {},
        provider_registry=registry if registry is not None else build_local_provider_registry(),
        trace_path=str(_TRACE_DIR / "tool_traces.jsonl"),
    )


def test_mcp_empty_registry_fail_soft():
    r = _mcp("portfolio.get_cash_snapshot", {"account_id": "acct_1"}, registry={})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_ERROR
    assert r["authority"] == AUTHORITY_READ_ONLY_ADVISORY


def test_mcp_provider_raises_fail_soft():
    class _Boom:
        name = "BoomProvider"
        domain = "portfolio"

        def health(self):
            return True

        def get(self, **kwargs):
            raise RuntimeError("boom")

        def search(self, **kwargs):
            raise RuntimeError("boom")

    reg = build_local_provider_registry()
    reg["portfolio.get_cash_snapshot"] = _Boom()
    r = _mcp("portfolio.get_cash_snapshot", {"account_id": "acct_1"}, registry=reg)
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_ERROR
    assert "RuntimeError" in r["reason"]
    assert r["authority"] == AUTHORITY_READ_ONLY_ADVISORY


def test_calendar_provider_unavailable_fail_soft():
    r = _mcp("calendar.search", {"query": "earnings"}, registry=build_external_not_configured_registry())
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_NOT_CONFIGURED
    assert r["authority"] == AUTHORITY_READ_ONLY_ADVISORY


def test_document_provider_unavailable_fail_soft():
    r = _mcp("documents.get", {"document_id": "doc_1"}, registry=build_external_not_configured_registry())
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_NOT_CONFIGURED
    assert r["authority"] == AUTHORITY_READ_ONLY_ADVISORY


# ── Trace store temporarily unavailable ────────────────────────────────────


def test_trace_store_unavailable_fail_soft(monkeypatch):
    trace = build_trace(trace_id="tr_fail", wake_id="wake_fail", agent="alex", role="cio_synthesis")
    real_open = builtins.open

    def _read_only_open(file, mode="r", *args, **kwargs):
        if "a" in str(mode):
            raise OSError("trace store read-only")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _read_only_open)
    result = append_trace(trace, path=str(_TRACE_DIR / "unwritable" / "trace.jsonl"))
    assert result is False


# ── Specialist timeout / malformed specialist output ───────────────────────


def test_specialist_garbage_inputs_return_dict():
    sub = build_specialist_sub_envelope("not a dict", "guardian", None)
    assert isinstance(sub, dict)
    assert sub.get("specialist") == "guardian"

    sub2 = build_specialist_sub_envelope({}, "hacker", ["garbage", {"q": 1}])
    assert isinstance(sub2, dict)
    assert sub2.get("specialist") == "hacker"


def test_malformed_memory_provider_retrieve_error():
    res = retrieve_for_context(_MalformedProvider(), query="SCHD", symbols=["SCHD"])
    assert res["retrieval_status"] == RETRIEVAL_ERROR
    assert res["supporting"] == []
    assert res["counter_memory"] == []


# ── Partial / stale / conflicting canonical source ─────────────────────────


def test_partial_office_truth_missing_refs_explicit():
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_partial"},
        decision=_decision(),
        office_truth={"holdings_ref": "holdings:real"},
    )
    # Missing canonical refs are represented explicitly (None), never invented.
    assert env["office_truth"]["holdings_ref"] == "holdings:real"
    assert env["office_truth"]["cash_ref"] is None
    assert env["office_truth"]["portfolio_ref"] is None
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


def test_stale_canonical_source_passed_verbatim():
    truth = {"holdings_ref": "holdings:schd", "source_asof": "1999-01-01T00:00:00Z"}
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_stale"},
        decision=_decision("WAIT"),
        office_truth=truth,
    )
    # Truth is passed through verbatim — not invented, not refreshed, not flipped.
    assert env["office_truth"]["source_asof"] == "1999-01-01T00:00:00Z"
    assert env["office_truth"]["holdings_ref"] == "holdings:schd"
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


def test_conflicting_canonical_source_passed_verbatim():
    truth = {
        "holdings_ref": "holdings:ledger",
        "portfolio_ref": "holdings:broker",
        "cash_ref": "cash:ledger",
        "source_asof": "2026-08-16T00:00:00Z",
    }
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w_conflict"},
        decision=_decision("WAIT"),
        office_truth=truth,
    )
    # The envelope carries each conflicting ref verbatim; it never reconciles.
    assert env["office_truth"]["holdings_ref"] == "holdings:ledger"
    assert env["office_truth"]["portfolio_ref"] == "holdings:broker"
    assert env["office_truth"]["cash_ref"] == "cash:ledger"
    ok, errs = validate_context_envelope(env)
    assert ok, errs
    _assert_act_now_unchanged(env)


# ── KEY INVARIANT: no failure creates a false ACT_NOW ──────────────────────


def test_key_invariant_no_failure_creates_false_act_now():
    providers = [
        _HealthRaises(),
        _Unavailable(),
        _SearchRaises(),
        _MalformedSearch(),
    ]
    for provider in providers:
        env = get_context_for_agent(
            agent="alex",
            wake={"wake_id": "w_inv"},
            decision=_decision(),
            memory_provider=provider,
        )
        effective, _blocking = canonical_act_now(env["decision"])
        assert effective is False, provider.name
