"""Phase 10 — performance baseline sanity tests.

The benchmark numbers are a LOCAL CPU baseline (documented measurements), not
SLA budgets. These tests only assert structural sanity: the expected keys
exist and the reported mean latencies are non-negative.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_perf_bench import benchmark  # noqa: E402

EXPECTED_OPS = ("context_build", "memory_retrieval", "mcp_read", "trace_append")


def test_benchmark_returns_expected_keys():
    result = benchmark(n=20)
    assert isinstance(result, dict)
    assert result["authority"] == "READ_ONLY_ADVISORY"
    assert result["n"] == 20
    assert isinstance(result["mean_ms"], dict)
    assert "total_mean_ms" in result
    for op in EXPECTED_OPS:
        assert op in result["mean_ms"], op


def test_benchmark_mean_ms_non_negative():
    result = benchmark(n=20)
    for op in EXPECTED_OPS:
        assert result["mean_ms"][op] >= 0.0, op
    assert result["total_mean_ms"] >= 0.0


def test_benchmark_small_n_completes():
    result = benchmark(n=20)
    assert result["n"] == 20
    assert result["total_mean_ms"] >= 0.0
    assert result["total_mean_ms"] >= result["mean_ms"]["context_build"]
