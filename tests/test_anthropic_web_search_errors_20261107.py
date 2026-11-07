"""LQ-20261107-212 — a web-search bridge failure must carry its cause, not just its exception type.

Live evidence 2026-11-07: every sampled `cio-ask-material-events` run over 24 h recorded the
`web.anthropic` source as ``{"ok": false, "reason": "HTTPError", "status": "no_data"}``. The bridge
had answered with an HTTP status, but ``search()`` threw the status away (``type(exc).__name__``), so
the run row could not say whether the source was unauthorized, misrouted, rate-limited or broken — and
the audit could only grade the lane DEGRADED without naming a cause.

These tests pin the two transport failures that used to collapse into a bare type name, and pin that
nothing from the response body (which can quote the question or a credential error page) reaches the
run row.

ANCHOR: ANTHROPIC_WEB_SEARCH_ERRORS_20261107
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import anthropic_web_search as ws  # noqa: E402

URL = "http://127.0.0.1:8766/v1/chat/completions"


def _http_error(code: int, reason: str, body: bytes):
    def transport(url, payload, timeout_s):  # noqa: ANN001 -- must match search()'s call shape, not a protocol
        raise HTTPError(url, code, reason, {}, io.BytesIO(body))

    return transport


def test_http_error_keeps_its_status():
    out = ws.search("NVDA outlook", transport=_http_error(403, "Forbidden", b'{"error":"denied"}'))
    assert out["ok"] is False and out["results"] == []
    assert out["status"] == 403
    assert "403" in out["error"] and "Forbidden" in out["error"]
    assert out["error"] != "HTTPError"  # the bare type name is what made the lane undiagnosable


def test_http_error_names_a_server_failure_the_same_way():
    out = ws.search("q", transport=_http_error(502, "Bad Gateway", b""))
    assert out["status"] == 502 and "502" in out["error"]


def test_http_error_never_echoes_the_response_body():
    body = b"upstream said: key sk-ant-secret-should-never-be-printed"
    out = ws.search("q", transport=_http_error(401, "Unauthorized", body))
    assert out["status"] == 401
    assert "sk-ant-secret" not in out["error"]
    assert "sk-ant-secret" not in repr(out)


def test_unreachable_bridge_keeps_its_reason():
    def transport(url, payload, timeout_s):  # noqa: ANN001 -- must match search()'s call shape, not a protocol
        raise URLError(ConnectionRefusedError(111, "Connection refused"))

    out = ws.search("q", transport=transport)
    assert out["ok"] is False
    assert "Connect" in out["error"] or "refused" in out["error"].lower()
    assert out["error"] != "URLError"


def test_success_shape_is_unchanged():
    document = {"content_blocks": [{"type": "web_search_tool_result", "content": [
        {"type": "web_search_result", "title": "T", "url": "https://x.invalid/a",
         "encrypted_content": "opaque", "page_age": "2026-11-01"}]}]}

    out = ws.search("q", transport=lambda url, payload, timeout_s: document)
    assert out["ok"] is True and out["provider"] == "anthropic" and out["error"] is None
    assert out["results"][0]["url"] == "https://x.invalid/a"
    assert "status" not in out or out["status"] is None


def test_bridge_refusal_code_is_still_the_error():
    out = ws.search("q", transport=lambda url, payload, timeout_s: {"error": {"code": "CREDIT_EXHAUSTED"}})
    assert out["ok"] is False and out["error"] == "CREDIT_EXHAUSTED"
