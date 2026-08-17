"""MCP timeout + rate/budget governance tests.

Deterministic local providers only. Proves fail-soft timeout, bounded per-wake/
per-tool budgets, fanout protection, and that normal reads are unchanged.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.mcp_read_only_gateway import (  # noqa: E402
    MCP_READ_ONLY_STATUS_LIMITED,
    MCP_READ_ONLY_STATUS_OK,
    MCP_READ_ONLY_STATUS_TIMEOUT,
    MCPRateGovernor,
    call_mcp_tool,
)
from scripts.lib.mcp_provider_adapters import build_local_provider_registry  # noqa: E402

_TRACE_DIR = Path(tempfile.mkdtemp(prefix="mcp_gov_"))


class _SlowSearch:
    name = "slow"

    def health(self):
        return True

    def search(self, tool=None, **kw):
        time.sleep(0.5)
        return {"status": "OK", "results": []}


def _slow_registry():
    return {"documents.search": _SlowSearch()}


def _call(tool, request=None, provider_registry=None, **kw):
    base = {
        "wake_id": "wake_1",
        "trace_id": "tr_wake_1",
        "agent": "alex",
        "tool": tool,
        "provider": tool.split(".")[0],
        "request": request or {},
        "provider_registry": provider_registry or build_local_provider_registry(),
        "trace_path": str(_TRACE_DIR / "tool_traces.jsonl"),
    }
    base.update(kw)
    return call_mcp_tool(**base)


def test_slow_provider_times_out_fail_soft():
    r = _call(
        "documents.search",
        {"query": "x"},
        provider_registry=_slow_registry(),
        timeout_ms=50,
    )
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_TIMEOUT
    assert "timeout" in r["reason"]


def test_normal_read_unchanged_with_high_budget_governor():
    gov = MCPRateGovernor(max_calls_per_wake=100, max_calls_per_tool=100)
    r = _call("portfolio.get_verified_snapshot", {"account_id": "acct_1"}, governor=gov)
    assert r["ok"] is True
    assert r["status"] == MCP_READ_ONLY_STATUS_OK


def test_wake_budget_exceeded_is_limited():
    gov = MCPRateGovernor(max_calls_per_wake=2, max_calls_per_tool=100)
    assert _call("portfolio.get_verified_snapshot", {"account_id": "a"}, governor=gov)["ok"]
    assert _call("portfolio.get_cash_snapshot", {"account_id": "a"}, governor=gov)["ok"]
    r = _call("portfolio.get_risk_snapshot", {"account_id": "a"}, governor=gov)
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_LIMITED
    assert "wake budget" in r["reason"]


def test_tool_budget_exceeded_is_limited():
    gov = MCPRateGovernor(max_calls_per_wake=100, max_calls_per_tool=1)
    assert _call("portfolio.get_verified_snapshot", {"account_id": "a"}, governor=gov)["ok"]
    r = _call("portfolio.get_verified_snapshot", {"account_id": "a"}, governor=gov)
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_LIMITED
    assert "tool budget" in r["reason"]


def test_governor_protects_against_unbounded_fanout():
    # One wake issuing many calls is blocked once it exhausts its budget.
    gov = MCPRateGovernor(max_calls_per_wake=5, max_calls_per_tool=5)
    ok_count = 0
    limited_count = 0
    for _ in range(20):
        r = _call("portfolio.get_verified_snapshot", {"account_id": "a"}, governor=gov)
        if r["ok"]:
            ok_count += 1
        elif r["status"] == MCP_READ_ONLY_STATUS_LIMITED:
            limited_count += 1
    assert ok_count == 5
    assert limited_count == 15


def test_min_interval_rate_limit():
    gov = MCPRateGovernor(max_calls_per_wake=100, max_calls_per_tool=100, min_interval_ms=1000)
    assert _call("portfolio.get_verified_snapshot", {"account_id": "a"}, governor=gov)["ok"]
    r = _call("portfolio.get_cash_snapshot", {"account_id": "a"}, governor=gov)
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_LIMITED
    assert "rate limit" in r["reason"]
