#!/usr/bin/env python3
"""web_research.py — Live web search via Brave Search API.

Provides web research capability for agents and auto-research.
Searches for recent news, analysis, and data about symbols/topics.

Usage:
    from web_research import search_web, research_symbol_web

    results = search_web("SCHD dividend growth 2026")
    brief = research_symbol_web("V", focus="earnings guidance")
"""
import json, os, urllib.request, urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_api_key() -> str:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not key:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("BRAVE_SEARCH_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key


def search_web(query: str, count: int = 5, freshness: str = "pw") -> list:
    """Search the web via Brave Search API.

    Args:
        query: Search query
        count: Number of results (max 20)
        freshness: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year)

    Returns list of {title, url, description, age}
    """
    # Lane C: ALL Brave traffic goes through the governed router. The previous
    # direct urlopen fallback is removed — a bypass here is a defect.
    try:
        from scripts.lib.brave_router import search as _governed, router_enabled
    except ImportError:
        try:
            from lib.brave_router import search as _governed, router_enabled  # type: ignore
        except ImportError:
            from brave_search import search as _budgeted_search
            return _budgeted_search(
                query, count=count, freshness=freshness,
                project_root=str(PROJECT_ROOT), caller="web_research",
            )
    if not router_enabled():
        # OFF-state: no side effect.
        return []
    resp = _governed(
        query, kind="web", count=count, freshness=freshness,
        caller="web_research", purpose="web_research.search",
        api_key=_get_api_key(), enabled=True,
    )
    return list(resp.results) if resp.ok else []


def research_symbol_web(symbol: str, focus: str = "", count: int = 5,
                        return_sources: bool = False):
    """Research a symbol via web search and return formatted context.

    With return_sources=True returns (context_text, sources[]) so writers can
    persist real provenance alongside findings (Engine Room v1 WS-2).

    Args:
        symbol: Ticker symbol
        focus: Optional focus area (e.g., "dividend", "earnings", "risk")

    Returns formatted string for LLM context injection.
    """
    queries = []
    if focus:
        queries.append(f"{symbol} stock {focus} 2026")
    queries.append(f"{symbol} stock analysis latest")
    if "dividend" in (focus or "").lower() or "income" in (focus or "").lower():
        queries.append(f"{symbol} dividend yield payout 2026")

    all_results = []
    seen_urls = set()
    for q in queries[:2]:
        results = search_web(q, count=count, freshness="pw")
        for r in results:
            if r["url"] not in seen_urls:
                all_results.append(r)
                seen_urls.add(r["url"])

    if not all_results:
        return ("", []) if return_sources else ""

    lines = [f"WEB RESEARCH ({len(all_results)} results for {symbol}):"]
    for r in all_results[:8]:
        title = r["title"][:60]
        desc = r["description"][:100]
        age = r["age"] or ""
        lines.append(f"  [{age}] {title}")
        if desc:
            lines.append(f"    {desc}")
    text = "\n".join(lines)
    if return_sources:
        return text, [{"title": r["title"][:120], "url": r["url"], "as_of": r.get("age") or None}
                      for r in all_results[:8]]
    return text


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"Searching: {query}")
        results = search_web(query, count=5)
        for r in results:
            print(f"\n  {r['title']}")
            print(f"  {r['url']}")
            print(f"  {r['description'][:120]}")
    else:
        print("Usage: python3 scripts/web_research.py <search query>")
        print("   or: from web_research import search_web, research_symbol_web")
