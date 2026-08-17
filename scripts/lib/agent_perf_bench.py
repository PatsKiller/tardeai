"""agent_perf_bench.py — local CPU latency baseline for the agent intelligence chain.

READ_ONLY_ADVISORY. Pure CPU, deterministic fixtures, no network, no secrets,
no broker/order/stop/2FA/risk-policy mutation. The numbers returned are a LOCAL
CPU BASELINE only — documented measurements, not invented SLA budgets.

Measured operations (wall-clock via ``time.perf_counter``):
  * context_build     — get_context_for_agent(...) with a LocalTestMemoryProvider
  * memory_retrieval  — retrieve_for_context(...)
  * mcp_read          — call_mcp_tool(...) on a local read-only tool
  * trace_append      — append_trace(...) to a temp path
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.lib.agent_context_envelope import get_context_for_agent
from scripts.lib.agent_memory_governance import (
    MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
    STATUS_ACTIVE,
    build_memory_record,
    retrieve_for_context,
)
from scripts.lib.agent_memory_provider import LocalTestMemoryProvider
from scripts.lib.agent_run_trace import append_trace, build_trace
from scripts.lib.mcp_provider_adapters import build_local_provider_registry
from scripts.lib.mcp_read_only_gateway import call_mcp_tool, reset_default_governor

AUTHORITY = "READ_ONLY_ADVISORY"

_TRACE_ID = "tr_bench"
_WAKE_ID = "w_bench"

_OPERATIONS = ("context_build", "memory_retrieval", "mcp_read", "trace_append")


def _fixture_memory() -> LocalTestMemoryProvider:
    provider = LocalTestMemoryProvider()
    provider.add_candidate(
        build_memory_record(
            memory_type=MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
            subject="income anchor",
            content="operator prefers SCHD as income anchor",
            source_event_ids=["evt_bench"],
            status=STATUS_ACTIVE,
        )
    )
    return provider


def _fixture_decision() -> dict[str, Any]:
    return {"decision_id": "dec_bench", "current_action": "WAIT", "act_now": False}


def _fixture_truth() -> dict[str, Any]:
    return {
        "holdings_ref": "holdings:real",
        "cash_ref": "cash:real",
        "source_asof": "2026-08-16T00:00:00Z",
    }


def benchmark(n: int = 100) -> dict[str, Any]:
    """Run each operation ``n`` times and return mean wall-clock latency (ms)."""
    n = max(1, int(n))
    # The MCP chokepoint now always applies a shared default rate governor. Reset
    # it so this isolated benchmark measures real reads, not budget rejections.
    reset_default_governor()
    memory = _fixture_memory()
    registry = build_local_provider_registry()
    decision = _fixture_decision()
    truth = _fixture_truth()
    trace = build_trace(trace_id=_TRACE_ID, wake_id=_WAKE_ID, agent="alex", role="cio_synthesis")
    tmp = Path(tempfile.mkdtemp(prefix="agent_perf_bench_"))
    trace_path = tmp / "traces.jsonl"
    tool_trace_path = tmp / "tool_traces.jsonl"

    def context_build() -> dict[str, Any]:
        return get_context_for_agent(
            agent="alex",
            wake={"wake_id": _WAKE_ID},
            decision=decision,
            office_truth=truth,
            memory_provider=memory,
            symbols=["SCHD"],
        )

    def memory_retrieval() -> dict[str, Any]:
        return retrieve_for_context(memory, query="SCHD", symbols=["SCHD"])

    def mcp_read() -> dict[str, Any]:
        return call_mcp_tool(
            wake_id=_WAKE_ID,
            trace_id=_TRACE_ID,
            agent="alex",
            tool="portfolio.get_cash_snapshot",
            provider="portfolio",
            request={"account_id": "acct_1"},
            provider_registry=registry,
            trace_path=str(tool_trace_path),
        )

    def trace_append() -> bool:
        return append_trace(trace, path=str(trace_path))

    # Warm-up so imports / first allocations settle before timing.
    context_build()
    memory_retrieval()
    mcp_read()
    trace_append()

    def _mean_ms(fn) -> float:
        start = time.perf_counter()
        for _ in range(n):
            fn()
        elapsed_s = time.perf_counter() - start
        return (elapsed_s * 1000.0) / n

    mean_ms = {
        "context_build": _mean_ms(context_build),
        "memory_retrieval": _mean_ms(memory_retrieval),
        "mcp_read": _mean_ms(mcp_read),
        "trace_append": _mean_ms(trace_append),
    }

    return {
        "authority": AUTHORITY,
        "n": n,
        "mean_ms": mean_ms,
        "total_mean_ms": sum(mean_ms.values()),
        "note": "local CPU baseline (no network, deterministic fixtures); not an SLA budget",
    }
