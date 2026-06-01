#!/usr/bin/env python3
"""Hermes Scheduled Source Discovery Dry-Run — daily file-only output.

Safety: No DB writes, no backlog mutations, no embeddings, no promotions.
Reads backlog health, picks top 1 item, runs max 2 SearXNG queries.
"""
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
OUT = PR / "docs" / "hermes" / "source_discovery_dryruns"
OUT.mkdir(parents=True, exist_ok=True)
SEARXNG = "http://127.0.0.1:18888/search"
MAX_QUERIES = 2
MAX_RESULTS = 10

def search(query):
    params = urllib.parse.urlencode({"q": query, "format": "json", "categories": "general"})
    req = urllib.request.Request(f"{SEARXNG}?{params}", headers={"User-Agent": "Hermes-ScheduledDryRun/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("results", [])[:MAX_RESULTS]
    except Exception as e:
        return [{"error": str(e)[:200]}]

def main():
    now = datetime.now(timezone.utc)
    ds = now.strftime("%Y-%m-%d")

    # Read backlog health
    bh_path = PR / "docs" / "hermes" / "backlog_health" / "latest_backlog_health_summary.json"
    if not bh_path.exists():
        print("No backlog health summary found. Skipping.")
        return
    bh = json.loads(bh_path.read_text())
    review = bh.get("checks", {}).get("operator_review_list", [])
    if not review:
        print("No backlog items for discovery.")
        return

    top = review[0]
    topic = top.get("topic", "")[:80]
    print(f"Top backlog: id={top['id']} [{top['priority']}] {topic}")

    # Generate queries from topic
    queries = [
        f"{topic} research analysis 2026",
        f"{topic} improvement strategy guide",
    ][:MAX_QUERIES]

    all_results = []
    query_meta = []
    for q in queries:
        print(f"  Query: {q[:60]}")
        results = search(q)
        query_meta.append({"query": q, "results": len(results)})
        all_results.extend([{"title": r.get("title",""), "url": r.get("url",""),
                            "snippet": (r.get("content","") or "")[:300], "engine": r.get("engine",""),
                            "query": q} for r in results if "error" not in r])

    summary = {
        "date": ds, "backlog_item_id": top["id"], "backlog_topic": topic,
        "queries": query_meta, "total_results": len(all_results),
        "db_writes": 0, "backlog_mutations": 0, "embeddings": 0, "promotions": 0,
    }

    (OUT / "latest_source_discovery_dryrun.json").write_text(json.dumps(summary, indent=2))
    (OUT / f"{ds}_source_discovery_dryrun.md").write_text(
        f"# Source Discovery Dry-Run — {ds}\n\nBacklog: id={top['id']} {topic}\n"
        f"Queries: {len(queries)}\nResults: {len(all_results)}\n\n"
        f"**DB writes: ZERO | File output only**\n")

    print(f"Results: {len(all_results)}. Report: {OUT}/{ds}_source_discovery_dryrun.md")
    print("DB writes: 0 | Backlog mutations: 0")

if __name__ == "__main__":
    main()
