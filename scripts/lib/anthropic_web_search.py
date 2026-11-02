"""Anthropic hosted web_search as an Ask-the-CIO source.

The provider credential and the credit book live in the governed bridge; this module never sees a
key. It posts ONE tool-bearing call (server tool ``web_search_20260209``) under the registered
caller ``web_search`` and normalises the returned ``web_search_tool_result`` blocks into results.

Hermetic by construction: ``transport=`` is injectable, so tests never touch the network or the
bridge. A refused or unreachable bridge is a typed gap, never an exception into the caller.

**The tool version carries server-side code execution.** ``web_search_20260209`` uses Anthropic's
"dynamic filtering": Claude writes and runs code in Anthropic's own sandbox to call ``web_search`` and
filter the results before they reach the context window (provider docs, tool-use concepts). A real
response therefore also contains ``server_tool_use`` / ``code_execution_tool_result`` blocks, seen live
2026-11-01T23:5xZ, e.g. ``r = await web_search({"query": ...})`` followed by ``print(type(r), len(r))``.
Nothing of ours is executed: the sandbox is Anthropic-side, it never sees a credential, a file or a
broker path, and the only inputs are our query and public search results. The bridge's tool allowlist
(§23.10 P5) is an *outbound* gate and does not cover these blocks, so this module counts them instead of
hiding them: ``search()`` reports ``code_execution_blocks`` and the Ask source carries that count into its
run row. Choosing the older ``web_search_20250305`` is the way to have no code execution at all, at the
cost of the filtering that keeps result noise out of the context.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

CALLER = "web_search"
TASK_TYPE = "web_search"
BRIDGE_URL_ENV = "TRADEAI_BRIDGE_URL"
DEFAULT_URL = "http://127.0.0.1:8766/v1/chat/completions"
#: Server tool: Anthropic runs the search and returns web_search_result blocks (title/url/page_age).
TOOL: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def results_from_blocks(blocks: Any, count: int) -> tuple[list[dict[str, Any]], str | None]:
    """(results, error) from provider content blocks. A success ``content`` is a list; an error is an object."""
    out: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content")
        if isinstance(content, dict):
            return out, str(content.get("error_code") or "WEB_SEARCH_ERROR")
        for row in content or []:
            if isinstance(row, dict) and row.get("type") == "web_search_result":
                out.append({
                    "title": row.get("title"),
                    "url": row.get("url"),
                    # The API returns encrypted_content; the readable page text is not exposed here.
                    "content": row.get("encrypted_content") or "",
                    "published": row.get("page_age"),
                })
                if len(out) >= count:
                    return out, None
    return out, None


def code_execution_blocks(blocks: Any) -> int:
    """How many sandbox results the provider's dynamic filtering produced (see the module docstring).

    Counted, never consumed: the Ask source only reads ``web_search_tool_result`` rows. The count rides
    the run row so a receipt shows that code ran Anthropic-side, instead of the operator discovering it.
    """
    return sum(
        1 for b in (blocks or [])
        if isinstance(b, dict) and b.get("type") == "code_execution_tool_result"
    )


def _post(url: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-TradeAI-Agent": CALLER, "X-TradeAI-Task-Type": TASK_TYPE},
    )
    with build_opener(_NoRedirect).open(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def search(query: str, *, count: int = 5, timeout_s: float = 60.0,
           transport: Callable[[str, dict, float], dict] | None = None) -> dict[str, Any]:
    """Search the web through the governed bridge. Never raises; a failure is a typed gap."""
    url = os.environ.get(BRIDGE_URL_ENV) or DEFAULT_URL
    body = {
        "model": "tradeai_governed",
        "messages": [{"role": "user", "content": f"Search the web for: {query}"}],
        "tools": [TOOL],
        "max_tokens": 1024,
    }
    try:
        document = (transport or _post)(url, body, timeout_s)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return {"ok": False, "provider": "anthropic", "results": [], "error": type(exc).__name__}
    if not isinstance(document, dict) or document.get("error"):
        reason = "BRIDGE_REFUSED"
        if isinstance(document, dict):
            reason = str((document.get("error") or {}).get("code") or reason)
        return {"ok": False, "provider": "anthropic", "results": [], "error": reason}
    blocks = document.get("content_blocks") or (document.get("_tradeai") or {}).get("content_blocks") or []
    results, error = results_from_blocks(blocks, count)
    return {
        "ok": bool(results) and not error,
        "provider": "anthropic",
        "results": results,
        "error": error,
        # Dynamic filtering ran Anthropic-side code to answer this call (module docstring). Reported so the
        # run row says so, rather than leaving it to a provider-side detail nobody reads.
        "code_execution_blocks": code_execution_blocks(blocks),
    }
