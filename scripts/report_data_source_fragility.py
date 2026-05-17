#!/usr/bin/env python3
"""report_data_source_fragility.py — Measure data source health from existing logs/caches.

Read-only. No expensive API calls. No secrets printed. No mutations.

Usage:
    .venv/bin/python scripts/report_data_source_fragility.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
                            cursor_factory=psycopg2.extras.RealDictCursor)


def _check_env_key(name):
    """Check if key exists in .env without revealing value."""
    for line in (PROJ / ".env").read_text().splitlines():
        if line.startswith(f"{name}=") and len(line.split("=", 1)[1].strip()) > 0:
            return True
    return False


def main():
    p = argparse.ArgumentParser(description="Data source fragility (read-only)")
    p.add_argument("--since-days", type=int, default=7)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    sources = []

    # Finviz
    cur.execute("SELECT COUNT(*) as c, MAX(scanned_at) as last FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '%s days'", [args.since_days])
    r = cur.fetchone()
    sources.append({"name": "Finviz", "records": r["c"], "last_update": str(r["last"]) if r["last"] else None,
                     "key_configured": _check_env_key("FINVIZ_COOKIE"), "health": "healthy" if r["c"] > 10 else "degraded" if r["c"] > 0 else "stale",
                     "impact": "critical", "used_by": "proposals, screeners"})

    # Alpaca
    cur.execute("SELECT COUNT(*) as c, MAX(created_at) as last FROM paper_trades WHERE created_at > NOW() - INTERVAL '%s days'", [args.since_days])
    r = cur.fetchone()
    sources.append({"name": "Alpaca Paper", "records": r["c"], "last_update": str(r["last"]) if r["last"] else None,
                     "key_configured": _check_env_key("ALPACA_API_KEY"), "health": "healthy" if _check_env_key("ALPACA_API_KEY") else "missing",
                     "impact": "critical", "used_by": "paper trades, quotes"})

    # News
    cur.execute("SELECT COUNT(*) as c, MAX(published_at) as last FROM news_articles WHERE published_at > NOW() - INTERVAL '%s days'", [args.since_days])
    r = cur.fetchone()
    sources.append({"name": "News APIs", "records": r["c"], "last_update": str(r["last"]) if r["last"] else None,
                     "key_configured": _check_env_key("NEWSAPI_KEY"), "health": "healthy" if r["c"] > 50 else "degraded" if r["c"] > 0 else "stale",
                     "impact": "medium", "used_by": "agents, intelligence"})

    # YouTube
    try:
        cur.execute("SELECT COUNT(*) as c, MAX(processed_at) as last FROM youtube_transcripts WHERE processed_at > NOW() - INTERVAL '%s days'", [args.since_days])
        r = cur.fetchone()
        sources.append({"name": "YouTube Transcripts", "records": r["c"], "last_update": str(r["last"]) if r["last"] else None,
                         "key_configured": True, "health": "healthy" if r["c"] > 5 else "degraded",
                         "impact": "low", "used_by": "agents, intelligence"})
    except Exception:
        sources.append({"name": "YouTube Transcripts", "records": 0, "health": "unknown", "impact": "low"})
        conn.rollback()

    conn.close()

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "since_days": args.since_days, "sources": sources}

    if args.verbose:
        print(f"Data Source Fragility (last {args.since_days} days)")
        for s in sources:
            print(f"  {s['name']:25s} [{s['health']:10s}] records={s.get('records',0):5d} impact={s['impact']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Data Source Fragility", "", "| Source | Health | Records | Impact |", "|--------|--------|---------|--------|"]
        for s in sources:
            md.append(f"| {s['name']} | {s.get('health','?')} | {s.get('records',0)} | {s['impact']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
