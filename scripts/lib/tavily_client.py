"""Shared Tavily client — the ONE interface for the tavily web_search slot.

Do not create a second Tavily client per agent. This module exists because
`config/data_source_authority.json` declared `providers.tavily` (operator-
approved 2026-09-13, budget 20/day, scope "may supply: web_search") and put it
in `domains.web_search.backup`, while no client existed anywhere in the tree.
The chain therefore reached slot 2 on every Brave denial and recorded
`NO_ADAPTER` — a declared source that could never answer.

Written to the `searxng_client.py` idiom on purpose: same normalized hit shape,
same "errors come back as rows, never exceptions" contract, so
`brave_router._tavily_transport` can treat both slots identically.

READ_ONLY_ADVISORY. No broker, no order, no stop, no 2FA. Egress is a single
HTTPS POST to api.tavily.com and only when a key is configured.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

TAVILY_URL = os.environ.get("TAVILY_URL", "https://api.tavily.com/search")
AUTHORITY = "READ_ONLY_ADVISORY"

#: The registry matches this provider on the token "TAVILY_API"; accept the
#: conventional _KEY spelling first and fall back to the bare token so a host
#: configured either way works without a code change.
_KEY_ENV = ("TAVILY_API_KEY", "TAVILY_API")

NOT_CONFIGURED = "NOT_CONFIGURED"


def api_key(env: Optional[dict[str, str]] = None) -> str:
    """Return the configured key, or "" when none is set. Never raises."""
    src = env if env is not None else os.environ
    for name in _KEY_ENV:
        val = str(src.get(name) or "").strip()
        if val:
            return val
    return ""


def configured(env: Optional[dict[str, str]] = None) -> bool:
    """True when a key exists. False is a normal state, not an error."""
    return bool(api_key(env))


def tavily_search(
    query: str,
    *,
    categories: str = "general",
    limit: int = 6,
    timeout: float = 12.0,
    tavily_url: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Return normalized hit dicts: title, snippet, url, domain, query.

    Mirrors ``searxng_client.searx_search``. An unconfigured key, a transport
    failure or a non-JSON body all come back as a single error row rather than
    an exception, because the router's contract is that a dead slot refunds its
    budget unit and the chain moves on — a raise there would lose the question.
    """
    key = api_key(env)
    if not key:
        return [{
            "error": f"{NOT_CONFIGURED}: no TAVILY_API_KEY/TAVILY_API in environment",
            "query": query,
            "engine": "tavily",
            "authority": AUTHORITY,
        }]

    payload = json.dumps({
        "api_key": key,
        "query": query,
        "max_results": max(1, int(limit)),
        "topic": "news" if categories == "news" else "general",
        "search_depth": "basic",
    }).encode("utf-8")

    req = urllib.request.Request(
        (tavily_url or TAVILY_URL),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "TradeAI-SharedTavily/1.0",
        },
        method="POST",
    )

    out: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        for hit in (data.get("results") or [])[:limit]:
            url = str(hit.get("url") or "")
            domain = ""
            if url:
                import re

                m = re.search(r"https?://([^/]+)", url)
                if m:
                    domain = m.group(1).replace("www.", "")
            out.append({
                "title": str(hit.get("title") or "")[:140],
                "snippet": str(hit.get("content") or "")[:240],
                "url": url,
                "domain": domain,
                "age": str(hit.get("published_date") or ""),
                "query": query,
                "engine": "tavily",
                "authority": AUTHORITY,
            })
    except Exception as exc:  # noqa: BLE001 - error rows, never exceptions
        out.append({
            "error": f"{type(exc).__name__}:{exc}",
            "query": query,
            "engine": "tavily",
            "authority": AUTHORITY,
        })
    return out
