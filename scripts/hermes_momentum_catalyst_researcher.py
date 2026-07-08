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


def run(candidates, dry_run=True, output_path=None, merge=True, max_total_sources=None):
    """Research all candidates. merge=True updates the day's JSONL by symbol instead of clobbering it,
    so the momentum and scalp lanes can share one file without overwriting each other."""
    cap = MAX_TOTAL_SOURCES if max_total_sources is None else max_total_sources
    results = []
    total_sources = 0

    for c in candidates:
        if total_sources >= cap:
            break
        sym = c["symbol"] if isinstance(c, dict) else c
        print(f"  Researching {sym}...", end=" ", flush=True)
        result = research_ticker(sym)
        total_sources += result["source_count"]
        results.append(result)
        status = f"{result['catalyst_type']} ({result['source_count']} sources, conf {result['confidence']:.1f})"
        print(status)

    # Write output (merge by symbol so a second lane doesn't clobber the first)
    if not dry_run and output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        by_symbol = {}
        if merge and Path(output_path).exists():
            for line in Path(output_path).read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    by_symbol[str(rec.get("symbol", "")).upper()] = rec
                except Exception:
                    continue
        for r in results:
            by_symbol[str(r["symbol"]).upper()] = r
        with open(output_path, "w") as f:
            for rec in by_symbol.values():
                f.write(json.dumps(rec, default=str) + "\n")

    return results


def get_scalp_candidates(max_tickers=15):
    """Today's distinct social-scalp candidates (WAIT/GO) whose GO tier depends on catalyst
    verification — highest score first. Read-only."""
    import psycopg2
    syms = []
    try:
        conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
                                dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
                                password=os.getenv("DB_PASSWORD"))
        cur = conn.cursor()
        cur.execute("""SELECT symbol FROM scalp_scan_results
                       WHERE scanned_at::date = current_date AND decision IN ('GO','WAIT')
                       GROUP BY symbol ORDER BY max(score) DESC NULLS LAST LIMIT %s""", (max_tickers,))
        syms = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        print(f"scalp candidate read failed: {e}")
    return syms


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["momentum", "scalp"], default="momentum",
                    help="Which candidate pool to research: TradeAI momentum lane or today's social-scalp candidates.")
    ap.add_argument("--max-tickers", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", default=True)
    args = ap.parse_args()

    if args.source == "scalp":
        candidates = get_scalp_candidates(max_tickers=max(args.max_tickers, 15))
        _cap = 40  # cover ~15 scalp candidates × up to 3 sources
    else:
        from hermes_momentum_candidate_reader import get_momentum_candidates
        candidates = get_momentum_candidates(max_tickers=args.max_tickers)
        _cap = None
    if not candidates:
        print(f"No {args.source} candidates found.")
        sys.exit(0)

    print(f"Researching {len(candidates)} {args.source} candidates...")
    today = datetime.now().strftime("%Y-%m-%d")
    out = str(PROJECT_ROOT / f"data/hermes/momentum_catalysts/{today}_catalysts.jsonl")

    results = run(candidates, dry_run=not args.apply, output_path=out, merge=True, max_total_sources=_cap)

    print(f"\nResults: {len(results)} tickers")
    with_catalyst = sum(1 for r in results if r["catalyst_type"] != "no_clear_catalyst")
    print(f"  With catalyst: {with_catalyst}")
    print(f"  No catalyst: {len(results) - with_catalyst}")
    print(f"  Total sources: {sum(r['source_count'] for r in results)}")
    if not args.apply:
        print("\nDry-run. Use --apply to write.")
