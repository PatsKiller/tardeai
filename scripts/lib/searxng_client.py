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
    engines: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Return normalized hit dicts: title, snippet, url, domain, query, published.

    ``engines`` (2026-10-10, search routing engine): an explicit engine allowlist. When
    given, ``categories`` is NOT sent — SearXNG unions a category's engines with the
    ``engines`` list, so sending both re-admits every engine in the category. Measured
    2026-10-10 on the local instance: ``categories=general`` includes ``braveapi``, the
    PAID Brave API keyed into SearXNG, so a "free" general query spends one Brave request
    that ``lib/search_budget`` never counts. ``engines=bing,seznam`` returned only bing and
    seznam rows. ``published`` carries SearXNG's ``publishedDate`` when the engine gave one.
    """
    url_base = (searx_url or DEFAULT_SEARXNG).rstrip("/")
    if not url_base.endswith("/search"):
        # allow host-only env
        if "://" in url_base and "/search" not in url_base:
            url_base = url_base + "/search"
    query_params = {"q": query, "format": "json"}
    if engines:
        query_params["engines"] = ",".join(str(e).strip() for e in engines if str(e).strip())
    else:
        query_params["categories"] = categories
    params = urllib.parse.urlencode(query_params)
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
                "engines": list(hit.get("engines") or ([hit["engine"]] if hit.get("engine") else [])),
                "published": str(hit.get("publishedDate") or ""),
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
