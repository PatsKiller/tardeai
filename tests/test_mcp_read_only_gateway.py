"""Phase 3 — Read-only MCP gateway unit tests.

No broker, no network. Deterministic local providers only. tmp/temp trace paths.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.mcp_read_only_gateway import (  # noqa: E402
    MCP_READ_ONLY_STATUS_DENIED,
    MCP_READ_ONLY_STATUS_OK,
    call_mcp_tool,
    classify_tool_allowed,
)
from scripts.lib.mcp_provider_adapters import build_local_provider_registry  # noqa: E402
from scripts.lib.agent_tool_trace import query_tool_calls  # noqa: E402

_TEST_TRACE_DIR = Path(tempfile.mkdtemp(prefix="mcp_gw_gateway_"))


def _registry():
    return build_local_provider_registry()


def _call(tool, request=None, **kw):
    base = {
        "wake_id": "wake_1",
        "trace_id": "tr_wake_1",
        "agent": "alex",
        "tool": tool,
        "provider": tool.split(".")[0],
        "request": request or {},
        "provider_registry": _registry(),
        "trace_path": str(_TEST_TRACE_DIR / "tool_traces.jsonl"),
    }
    base.update(kw)
    return call_mcp_tool(**base)


def test_allowed_read_only_tool_passes():
    r = _call("portfolio.get_verified_snapshot", {"account_id": "acct_1"})
    assert r["ok"] is True
    assert r["status"] == MCP_READ_ONLY_STATUS_OK
    assert r["response"] is not None
    assert r["authority"] == "READ_ONLY_ADVISORY"


def test_unknown_tool_denied():
    r = _call("mystery.tool")
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED
    assert "unknown tool" in r["reason"]


def test_broker_tool_denied():
    r = _call("broker.place_order", {"symbol": "SCHD"})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED


def test_shell_tool_denied():
    r = _call("shell.exec", {"command": "ls"})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED


def test_missing_wake_id_denied():
    r = call_mcp_tool(
        wake_id="",
        trace_id="tr_1",
        agent="alex",
        tool="plans.get",
        provider="goals_plans",
        request={},
        provider_registry=_registry(),
        trace_path=str(_TEST_TRACE_DIR / "tool_traces.jsonl"),
    )
    assert r["ok"] is False
    assert r["reason"] == "missing wake_id"


def test_missing_trace_id_denied():
    r = call_mcp_tool(
        wake_id="w1",
        trace_id="",
        agent="alex",
        tool="plans.get",
        provider="goals_plans",
        request={},
        provider_registry=_registry(),
        trace_path=str(_TEST_TRACE_DIR / "tool_traces.jsonl"),
    )
    assert r["ok"] is False
    assert r["reason"] == "missing trace_id"


def test_classify_tool_allowed_mapping():
    ok, cap = classify_tool_allowed("portfolio.get_verified_snapshot")
    assert ok is True
    assert cap == "portfolio"
    ok2, reason = classify_tool_allowed("broker.place_order")
    assert ok2 is False
    assert "broker" in reason or "order" in reason
    ok3, reason3 = classify_tool_allowed("totally.unknown")
    assert ok3 is False
    assert reason3 == "unknown tool"


def test_receipt_is_recorded(tmp_path):
    path = tmp_path / "tool_traces.jsonl"
    r = _call("calendar.search", {"query": "earnings"}, trace_path=str(path))
    assert r["ok"] is True
    rows = query_tool_calls(trace_id="tr_wake_1", path=str(path))
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "calendar.search"


def test_trace_binding_fields_present(tmp_path):
    path = tmp_path / "tool_traces.jsonl"
    _call("documents.get", {"document_id": "doc_1"}, trace_path=str(path))
    rows = query_tool_calls(trace_id="tr_wake_1", path=str(path))
    assert len(rows) == 1
    rec = rows[0]
    for field in (
        "trace_id",
        "wake_id",
        "agent",
        "tool_name",
        "provider",
        "request_digest",
        "response_digest",
        "source_asof",
        "latency_ms",
        "status",
        "started_at",
        "ended_at",
    ):
        assert field in rec, f"missing {field}"
    assert rec["trace_id"] == "tr_wake_1"
    assert rec["wake_id"] == "wake_1"
    assert rec["agent"] == "alex"
    assert rec["status"] == MCP_READ_ONLY_STATUS_OK
