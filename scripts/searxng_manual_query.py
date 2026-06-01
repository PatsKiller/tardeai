#!/usr/bin/env python3
"""SearXNG Manual Query Wrapper — operator-only, file-only output.

Usage:
    python scripts/searxng_manual_query.py "your search query"
    python scripts/searxng_manual_query.py --query "your search query" --max-results 10

Safety:
    - Localhost SearXNG only (127.0.0.1:18888)
    - No DB writes, no embeddings, no ingestion, no promotion
    - No Hermes integration, no autonomous use
    - Output: sanitized JSON + Markdown files only
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SEARXNG_URL = "http://127.0.0.1:18888/search"
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "data" / "searxng_queries"
MAX_SNIPPET_LEN = 500

# Patterns that must never appear in output
SECRET_PATTERNS = [
    r'sk-[a-zA-Z0-9]{20,}',
    r'AKIA[A-Z0-9]{16}',
    r'ghp_[a-zA-Z0-9]{36}',
    r'[0-9]{8,10}:[a-zA-Z0-9_-]{30,}',
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
    r'-----BEGIN [A-Z]+ KEY-----',
]


def sanitize_text(text: str) -> str:
    """Remove secrets, IPs, and truncate."""
    if not text:
        return ""
    for pat in SECRET_PATTERNS:
        text = re.sub(pat, '[REDACTED]', text)
    # Remove IP addresses
    text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', text)
    # Truncate
    if len(text) > MAX_SNIPPET_LEN:
        text = text[:MAX_SNIPPET_LEN] + "..."
    return text


def query_searxng(query: str, max_results: int = 15) -> dict:
    """Query local SearXNG and return raw response."""
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "categories": "general",
    })
    url = f"{SEARXNG_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "TradeAI-ManualWrapper/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return data
    except Exception as e:
        print(f"ERROR: SearXNG query failed: {e}", file=sys.stderr)
        sys.exit(1)


def sanitize_results(raw: dict, max_results: int) -> list[dict]:
    """Extract and sanitize results."""
    results = []
    for r in raw.get("results", [])[:max_results]:
        results.append({
            "title": sanitize_text(r.get("title", "")),
            "url": r.get("url", ""),
            "snippet": sanitize_text(r.get("content", "")),
            "engine": r.get("engine", "unknown"),
            "category": r.get("category", "general"),
        })
    return results


def write_outputs(query: str, results: list[dict], raw_meta: dict, out_dir: Path):
    """Write sanitized output files."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Metadata
    metadata = {
        "query": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result_count": len(results),
        "total_available": raw_meta.get("number_of_results", 0),
        "searxng_version": raw_meta.get("version", "unknown"),
        "engines_used": list(set(r["engine"] for r in results)),
        "wrapper": "searxng_manual_query.py",
        "db_writes": 0,
        "embeddings": 0,
        "ingested": False,
        "promoted": False,
    }
    (out_dir / "query_metadata.json").write_text(json.dumps(metadata, indent=2))

    # 2. Sanitized results JSON
    (out_dir / "query_results_sanitized.json").write_text(json.dumps(results, indent=2))

    # 3. Markdown summary
    lines = [
        f"# SearXNG Manual Query — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**Query:** {query}",
        f"**Results:** {len(results)}",
        f"**Engines:** {', '.join(metadata['engines_used'])}",
        "",
        "---",
        "",
        "**Safety:** File-only output. No DB writes. No embeddings. No ingestion. No promotion.",
        "",
        "---",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r['title']}")
        lines.append(f"**URL:** {r['url']}")
        lines.append(f"**Engine:** {r['engine']}")
        if r["snippet"]:
            lines.append(f"\n{r['snippet']}")
        lines.append("")

    (out_dir / "query_summary.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="SearXNG Manual Query Wrapper")
    parser.add_argument("query_positional", nargs="?", help="Search query")
    parser.add_argument("--query", "-q", help="Search query (alternative)")
    parser.add_argument("--max-results", "-n", type=int, default=15, help="Max results (default 15)")
    args = parser.parse_args()

    query = args.query_positional or args.query
    if not query:
        parser.error("Query required: provide as positional arg or --query")

    # Verify SearXNG is reachable
    try:
        urllib.request.urlopen("http://127.0.0.1:18888/", timeout=3)
    except Exception:
        print("ERROR: SearXNG not reachable at http://127.0.0.1:18888/", file=sys.stderr)
        sys.exit(1)

    print(f"Querying SearXNG: {query}")
    raw = query_searxng(query, args.max_results)
    results = sanitize_results(raw, args.max_results)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / ts
    write_outputs(query, results, raw, out_dir)

    print(f"Results: {len(results)}")
    print(f"Output:  {out_dir}/")
    print(f"  query_summary.md")
    print(f"  query_results_sanitized.json")
    print(f"  query_metadata.json")
    print(f"DB writes: 0 | Embeddings: 0 | Ingested: No | Promoted: No")


if __name__ == "__main__":
    main()
