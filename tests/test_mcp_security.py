"""Phase 3 — MCP read-only gateway security tests.

SSRF, path traversal, size bounds, fail-soft, redaction, NOT_CONFIGURED.
No broker, no network. Local deterministic providers only.
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
    MCP_READ_ONLY_STATUS_BOUNDED,
    MCP_READ_ONLY_STATUS_DENIED,
    MCP_READ_ONLY_STATUS_ERROR,
    MCP_READ_ONLY_STATUS_NOT_CONFIGURED,
    MCP_READ_ONLY_STATUS_OK,
    _is_safe_doc_path,
    _is_safe_host,
    call_mcp_tool,
)
from scripts.lib.mcp_provider_adapters import (  # noqa: E402
    NotConfiguredProvider,
    build_local_provider_registry,
)

_TEST_TRACE_DIR = Path(tempfile.mkdtemp(prefix="mcp_gw_security_"))


def _registry(**overrides):
    reg = build_local_provider_registry()
    reg.update(overrides)
    return reg


def _call(tool, request=None, registry=None, **kw):
    base = {
        "wake_id": "wake_1",
        "trace_id": "tr_wake_1",
        "agent": "alex",
        "tool": tool,
        "provider": tool.split(".")[0],
        "request": request or {},
        "provider_registry": registry or _registry(),
        "trace_path": str(_TEST_TRACE_DIR / "tool_traces.jsonl"),
    }
    base.update(kw)
    return call_mcp_tool(**base)


# ── Write tool denied ──────────────────────────────────────────────────────


def test_write_tool_denied():
    r = _call("calendar.create", {"summary": "meeting"})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED


def test_document_write_tool_denied():
    r = _call("documents.delete", {"document_id": "doc_1"})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED


# ── SSRF ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/x",
        "http://127.0.0.1:8080/x",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.1/x",
        "http://10.0.0.5/x",
    ],
)
def test_ssrf_doc_url_denied(url):
    r = _call("research.get_source", {"source_url": url})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED
    assert "unsafe host" in r["reason"]


def test_safe_host_allowed_with_allowlist():
    r = _call(
        "research.get_source",
        {"source_url": "https://api.example.com/src/1"},
        safe_hosts=["api.example.com"],
    )
    assert r["ok"] is True
    assert r["status"] == MCP_READ_ONLY_STATUS_OK


def test_is_safe_host_blocks_private():
    assert _is_safe_host("127.0.0.1") is False
    assert _is_safe_host("169.254.169.254") is False
    assert _is_safe_host("localhost") is False
    assert _is_safe_host("10.1.2.3") is False
    assert _is_safe_host("192.168.0.1") is False
    assert _is_safe_host("172.16.0.1") is False
    assert _is_safe_host("::1") is False
    assert _is_safe_host("metadata.google.internal") is False


# ── Path traversal ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["../secret.txt", "../../etc/passwd", "/etc/passwd", "C:\\Windows\\system32", "..\\..\\x"],
)
def test_path_traversal_denied(path):
    r = _call("documents.get", {"document_id": "doc_1", "path": path})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED
    assert "unsafe path" in r["reason"]


def test_is_safe_doc_path_blocks():
    assert _is_safe_doc_path("../x") is False
    assert _is_safe_doc_path("/etc/passwd") is False
    assert _is_safe_doc_path("reports/q1.pdf") is True


# ── Response size bound ────────────────────────────────────────────────────


class _HugeProvider:
    name = "HugeProvider"
    domain = "research"

    def health(self):
        return True

    def get(self, **kwargs):
        return {"blob": "A" * 10000}

    def search(self, **kwargs):
        return {"blob": "A" * 10000}


def test_oversized_response_bounded():
    reg = _registry()
    reg["research.get_source"] = _HugeProvider()
    r = _call("research.get_source", {"source_id": "s1"}, registry=reg, max_response_bytes=64)
    assert r["ok"] is True
    assert r["bounded"] is True
    assert r["status"] == MCP_READ_ONLY_STATUS_BOUNDED


# ── Provider error fail-soft ───────────────────────────────────────────────


class _BoomProvider:
    name = "BoomProvider"
    domain = "research"

    def health(self):
        return True

    def get(self, **kwargs):
        raise RuntimeError("boom")

    def search(self, **kwargs):
        raise RuntimeError("boom")


def test_provider_error_fail_soft():
    reg = _registry()
    reg["research.search"] = _BoomProvider()
    r = _call("research.search", {"query": "x"}, registry=reg)  # no exception expected
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_ERROR


# ── Invalid schema ─────────────────────────────────────────────────────────


def test_invalid_schema_denied_non_dict():
    r = _call("plans.get", request="not-a-dict")
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED
    assert "schema" in r["reason"]


def test_invalid_schema_denied_unknown_field():
    r = _call("plans.get", {"plan_id": "p1", "mutate": True})
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_DENIED


# ── Secret redaction ───────────────────────────────────────────────────────


class _SecretProvider:
    name = "SecretProvider"
    domain = "portfolio"

    def health(self):
        return True

    def get(self, **kwargs):
        return {
            "api_key": "sk-1234567890abcdef",
            "safe": "hello",
            "nested": {"token": "xoxp-abcdefghij"},
        }

    def search(self, **kwargs):
        return {"api_key": "sk-1234567890abcdef"}


def test_secret_in_response_redacted():
    reg = _registry()
    reg["portfolio.get_verified_snapshot"] = _SecretProvider()
    r = _call("portfolio.get_verified_snapshot", {"account_id": "a1"}, registry=reg)
    assert r["ok"] is True
    assert r["response"]["api_key"] == "[REDACTED]"
    assert r["response"]["safe"] == "hello"
    assert r["response"]["nested"]["token"] == "[REDACTED]"


# ── Local read-only providers pass ─────────────────────────────────────────


def test_calendar_search_passes_via_local_provider():
    r = _call("calendar.search", {"query": "earnings", "limit": 5})
    assert r["ok"] is True
    assert r["status"] == MCP_READ_ONLY_STATUS_OK


def test_documents_search_passes_via_local_provider():
    r = _call("documents.search", {"query": "thesis"})
    assert r["ok"] is True
    assert r["status"] == MCP_READ_ONLY_STATUS_OK


# ── NOT_CONFIGURED fail-soft ───────────────────────────────────────────────


def test_not_configured_provider_fail_soft():
    reg = _registry()
    reg["calendar.get_event"] = NotConfiguredProvider()
    r = _call("calendar.get_event", {"event_id": "e1"}, registry=reg)
    assert r["ok"] is False
    assert r["status"] == MCP_READ_ONLY_STATUS_NOT_CONFIGURED
