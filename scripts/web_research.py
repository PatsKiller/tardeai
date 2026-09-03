#!/usr/bin/env python3
"""web_research.py — Live web search via Brave Search API.

Provides web research capability for agents and auto-research.
Searches for recent news, analysis, and data about symbols/topics.

Usage:
    from web_research import search_web, research_symbol_web

    results = search_web("SCHD dividend growth 2026")
    brief = research_symbol_web("V", focus="earnings guidance")
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def search_web(query: str, count: int = 5, freshness: str = "pw") -> list:
    """Search the web through the governed Brave research router.

    Args:
        query: Search query
        count: Number of results (max 20)
        freshness: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year)

    Returns a list of {title, url, description, age, attribution}. Results are
    ``SEARCH_DISCOVERY`` artifacts, never verified fact.

    Use :func:`search_web_outcome` when the caller needs to distinguish "nothing
    was published" from "we were not allowed to ask" — this wrapper flattens
    both to ``[]`` for the legacy callers that expect a list.

    The private key read and ``urlopen`` that used to sit below the router
    import are gone. They were reachable whenever the import failed, which made
    the module fail *open*: an unimportable budget silently became an
    unbudgeted call, which is the exact inversion the ledger exists to prevent.
    """
    return search_web_outcome(query, count=count, freshness=freshness).get("results", [])


def search_web_outcome(
    query: str, count: int = 5, freshness: str = "pw", *, caller: str = "web_research", purpose: str = "EVIDENCE_GAP"
) -> dict:
    """Routed search that preserves *why* there are no results."""
    try:
        from scripts.lib import brave_research_router as _router
    except ImportError:
        try:
            from lib import brave_research_router as _router  # type: ignore
        except ImportError:
            return {
                "results": [],
                "status": "ROUTER_UNAVAILABLE",
                "degraded": True,
                "note": "Search router unavailable — denied (never fail open).",
            }

    outcome = _router.search(
        query,
        purpose=_router.Purpose(purpose),
        priority=_router.Priority.WATCHLIST,
        caller=caller,
        count=count,
        freshness=freshness,
    )
    return {
        "results": [
            {
                "title": r.title,
                "url": r.url,
                "description": r.description,
                "age": r.age,
                "attribution": r.attribution,
                "is_primary_source": r.is_primary_source,
            }
            for r in outcome.results
        ],
        "status": outcome.status.value,
        "degraded": outcome.degraded,
        "note": outcome.degradation_note(),
        "fingerprint": outcome.fingerprint,
    }


def research_symbol_web(symbol: str, focus: str = "", count: int = 5, return_sources: bool = False):
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
        return text, [
            {"title": r["title"][:120], "url": r["url"], "as_of": r.get("age") or None} for r in all_results[:8]
        ]
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
