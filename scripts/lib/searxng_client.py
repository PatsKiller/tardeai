"""Shared SearXNG client — one interface for discovery + thesis acquisition.

Do not create a second SearXNG client per agent.
Delegates to the same local SearXNG endpoint Cursor/Hermes already use.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Optional

# Port 18888, not 8080. Nothing has ever listened on 8080 here — all 18 real
# call sites pass 18888 explicitly, so the default only ever applied to a
# caller that forgot, and then failed at connect time looking like the remote
# search was down. The first live residual-web hop hit exactly that.
DEFAULT_SEARXNG = os.environ.get("SEARXNG_URL", "http://127.0.0.1:18888/search")
AUTHORITY = "READ_ONLY_ADVISORY"


def searx_search(
    query: str,
    *,
    categories: str = "general",
    limit: int = 6,
    timeout: float = 12.0,
    searx_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return normalized hit dicts: title, snippet, url, domain, query."""
    url_base = (searx_url or DEFAULT_SEARXNG).rstrip("/")
    if not url_base.endswith("/search"):
        # allow host-only env
        if "://" in url_base and "/search" not in url_base:
            url_base = url_base + "/search"
    params = urllib.parse.urlencode({"q": query, "format": "json", "categories": categories})
    req = urllib.request.Request(
        f"{url_base}?{params}",
        headers={"User-Agent": "TradeAI-SharedSearx/1.0"},
    )
    out: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        for hit in (data.get("results") or [])[:limit]:
            url = hit.get("url") or ""
            domain = ""
            if url:
                import re
                m = re.search(r"https?://([^/]+)", url)
                if m:
                    domain = m.group(1).replace("www.", "")
            out.append({
                "title": (hit.get("title") or "")[:140],
                "snippet": (hit.get("content") or "")[:240],
                "url": url,
                "domain": domain,
                "query": query,
                "engine": "searxng",
                "authority": AUTHORITY,
            })
    except Exception as exc:
        out.append({
            "error": f"{type(exc).__name__}:{exc}",
            "query": query,
            "engine": "searxng",
            "authority": AUTHORITY,
        })
    return out
