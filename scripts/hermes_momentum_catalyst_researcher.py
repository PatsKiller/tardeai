#!/usr/bin/env python3
"""
Hermes momentum catalyst researcher.
Queries SearXNG for news catalysts on TradeAI momentum candidates.
Writes advisory-only context — NOT a trade signal.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888/search")
MAX_SOURCES_PER_TICKER = 3
MAX_TOTAL_SOURCES = 15

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


CATALYST_TYPES = {
    "earnings": ["earnings", "EPS", "revenue", "guidance", "beat", "miss"],
    "analyst": ["upgrade", "downgrade", "price target", "analyst", "rating"],
    "regulatory": ["FDA", "approval", "clearance", "lawsuit", "SEC"],
    "manda": ["acquisition", "merger", "buyout", "takeover"],
    "offering": ["offering", "dilution", "shelf", "ATM offering"],
    "contract": ["contract", "award", "partnership", "deal"],
    "sector": ["sector", "industry", "rotation"],
    "social": ["reddit", "wallstreetbets", "trending", "viral"],
}


def classify_catalyst(text):
    """Classify catalyst type from text."""
    text_lower = text.lower()
    for ctype, keywords in CATALYST_TYPES.items():
        if any(kw.lower() in text_lower for kw in keywords):
            return ctype
    return "news_momentum"


def search_catalyst(symbol, query_suffix="latest news"):
    """Query SearXNG for a symbol's catalyst."""
    query = f"{symbol} stock {query_suffix}"
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "categories": "news",
        "time_range": "day", "engines": "google news,bing news,duckduckgo"
    })
    try:
        req = urllib.request.Request(f"{SEARXNG_URL}?{params}", method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        results = data.get("results", [])[:MAX_SOURCES_PER_TICKER]
        try:
            from hermes_source_policy import filter_search_results
            results = filter_search_results(results)
        except Exception:
            pass
        return [{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", "")[:200],
            "engine": r.get("engine", ""),
            "published": r.get("publishedDate", ""),
        } for r in results]
    except Exception as e:
        return [{"error": str(e)[:100]}]


def research_ticker(symbol):
    """Research a single ticker for catalysts."""
    queries = [
        "latest news",
        "premarket catalyst",
        "earnings guidance analyst",
    ]
    all_sources = []
    for q in queries:
        if len(all_sources) >= MAX_SOURCES_PER_TICKER:
            break
        sources = search_catalyst(symbol, q)
        for s in sources:
            if not s.get("error") and s.get("url") not in [x.get("url") for x in all_sources]:
                all_sources.append(s)
        time.sleep(0.5)  # Rate limit

    # Classify
    catalyst_type = "no_clear_catalyst"
    catalyst_summary = "No clear catalyst found"
    confidence = 0.2

    if all_sources and not all_sources[0].get("error"):
        best = all_sources[0]
        catalyst_type = classify_catalyst(best.get("title", "") + " " + best.get("content", ""))
        catalyst_summary = best.get("title", "")[:100]
        confidence = min(0.7, 0.3 + 0.1 * len(all_sources))

    return {
        "symbol": symbol,
        "research_timestamp": datetime.now().isoformat(),
        "catalyst_type": catalyst_type,
        "catalyst_summary": catalyst_summary,
        "catalyst_strength": "high" if confidence >= 0.5 else "low",
        "confidence": confidence,
        "source_count": len([s for s in all_sources if not s.get("error")]),
        "source_domains": list(set(urllib.parse.urlparse(s.get("url", "")).netloc for s in all_sources if s.get("url"))),
        "sources": all_sources,
        "advisory_only": True,
        "not_trade_signal": True,
        "no_execution": True,
    }


def run(candidates, dry_run=True, output_path=None):
    """Research all candidates."""
    results = []
    total_sources = 0

    for c in candidates:
        if total_sources >= MAX_TOTAL_SOURCES:
            break
        sym = c["symbol"] if isinstance(c, dict) else c
        print(f"  Researching {sym}...", end=" ", flush=True)
        result = research_ticker(sym)
        total_sources += result["source_count"]
        results.append(result)
        status = f"{result['catalyst_type']} ({result['source_count']} sources, conf {result['confidence']:.1f})"
        print(status)

    # Write output
    if not dry_run and output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            for r in results:
                f.write(json.dumps(r, default=str) + "\n")

    return results


if __name__ == "__main__":
    from hermes_momentum_candidate_reader import get_momentum_candidates
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tickers", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", default=True)
    args = ap.parse_args()

    candidates = get_momentum_candidates(max_tickers=args.max_tickers)
    if not candidates:
        print("No momentum candidates found.")
        sys.exit(0)

    print(f"Researching {len(candidates)} momentum candidates...")
    today = datetime.now().strftime("%Y-%m-%d")
    out = str(PROJECT_ROOT / f"data/hermes/momentum_catalysts/{today}_catalysts.jsonl")

    results = run(candidates, dry_run=not args.apply, output_path=out)

    print(f"\nResults: {len(results)} tickers")
    with_catalyst = sum(1 for r in results if r["catalyst_type"] != "no_clear_catalyst")
    print(f"  With catalyst: {with_catalyst}")
    print(f"  No catalyst: {len(results) - with_catalyst}")
    print(f"  Total sources: {sum(r['source_count'] for r in results)}")
    if not args.apply:
        print("\nDry-run. Use --apply to write.")
