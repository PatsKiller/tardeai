# Source Export: scripts/ingestion_learning_engine.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/ingestion_learning_engine.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `b1da1bed6f0f4750c6c1607246f36bbce7c8f3292740870beb83c72bd7077256` |
| **File Size** | 9034 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""ingestion_learning_engine.py — Evaluate source/screener/topic usefulness.

Generates learning hypotheses and recommendations based on ingestion quality.
No active config changes. Dry-run safe.

Usage:
    .venv/bin/python scripts/ingestion_learning_engine.py --analyze --dry-run --json
    .venv/bin/python scripts/ingestion_learning_engine.py --source finviz --dry-run --json
"""
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def analyze_sources(conn, source_filter=None, window_days=30):
    """Analyze ingestion source quality over a window."""
    cur = conn.cursor()
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Get source health
    cur.execute("SELECT source_key, status, last_row_count, failure_count, degraded FROM data_source_health")
    sources = {r[0]: {"status": r[1], "last_row_count": r[2], "failures": r[3], "degraded": r[4]}
               for r in cur.fetchall()}

    # Get scan counts by source
    cur.execute("""
        SELECT source, COUNT(DISTINCT symbol), COUNT(*)
        FROM trade_ai_scans WHERE scanned_at > %s
        GROUP BY source
    """, [window_start])
    for r in cur.fetchall():
        src = (r[0] or "unknown").lower().replace(" ", "_")
        if src not in sources:
            sources[src] = {}
        sources[src]["unique_symbols"] = r[1]
        sources[src]["total_scans"] = r[2]

    # Get news article counts by source
    cur.execute("""
        SELECT source, COUNT(*), AVG(relevance_score)
        FROM news_articles WHERE created_at > %s AND source IS NOT NULL
        GROUP BY source
    """, [window_start])
    news_sources = {}
    for r in cur.fetchall():
        news_sources[r[0] or "unknown"] = {"count": r[1], "avg_relevance": _f(r[2])}

    # Get topic monitor stats
    cur.execute("""
        SELECT topic_id, enabled, created_at
        FROM topic_monitor WHERE enabled = true
    """)
    topics = [{"topic_id": r[0], "enabled": r[1], "created_at": r[2]} for r in cur.fetchall()]

    # Check proposal conversion by source-linked symbols
    cur.execute("""
        SELECT COUNT(DISTINCT symbol), COUNT(*)
        FROM paper_trade_proposals WHERE created_at > %s
    """, [window_start])
    proposal_row = cur.fetchone()
    proposal_symbols = proposal_row[0] if proposal_row else 0

    results = []
    for src_key, data in sources.items():
        if source_filter and source_filter.lower() != src_key.lower():
            continue
        score = {
            "source_key": src_key,
            "window_start": str(window_start),
            "window_end": str(datetime.now(timezone.utc)),
            "signals_seen": data.get("total_scans", data.get("last_row_count", 0)) or 0,
            "unique_symbols": data.get("unique_symbols", 0) or 0,
            "status": data.get("status", "unknown"),
            "failures": data.get("failures", 0) or 0,
            "degraded": data.get("degraded", False),
            "reliability_score": max(0, 100 - (data.get("failures", 0) or 0) * 10),
        }

        # Usefulness heuristic
        signals = score["signals_seen"]
        if signals > 0:
            score["usefulness_score"] = min(100, (score["unique_symbols"] / max(signals, 1)) * 100)
        else:
            score["usefulness_score"] = 0

        # Recommendation
        if score["reliability_score"] < 50:
            score["recommendation"] = "investigate_reliability"
        elif score["usefulness_score"] < 20 and signals > 100:
            score["recommendation"] = "decrease_weight_or_frequency"
        elif score["degraded"]:
            score["recommendation"] = "monitor_degraded_state"
        else:
            score["recommendation"] = "maintain_current"

        results.append(score)

    return {
        "sources": results,
        "news_sources": news_sources,
        "topics": topics,
        "proposal_symbols_in_window": proposal_symbols,
        "window_days": window_days,
    }


def generate_hypotheses(conn, analysis, dry_run=True):
    """Generate learning hypotheses from source analysis."""
    from learning_governance import (create_hypothesis, add_evidence,
                                     create_recommendation, compute_sample_size_status)
    hypotheses = []

    for src in analysis["sources"]:
        if src["recommendation"] == "maintain_current":
            continue

        tier = compute_sample_size_status("ingestion", src["signals_seen"])
        title = f"Source '{src['source_key']}' quality: {src['recommendation']}"
        desc = (f"Reliability={src['reliability_score']}, usefulness={src['usefulness_score']:.0f}, "
                f"signals={src['signals_seen']}, failures={src['failures']}")

        h = {"title": title, "domain": "ingestion", "type": src["recommendation"],
             "description": desc, "sample_size": src["signals_seen"],
             "sample_tier": tier, "source_key": src["source_key"]}

        if not dry_run:
            hid = create_hypothesis(conn, title, "ingestion", "source_weight_change",
                                    desc, sample_size=src["signals_seen"],
                                    payload={"source_key": src["source_key"], "scores": src})
            add_evidence(conn, hid, "source_quality", src,
                         supports=src["recommendation"] != "maintain_current",
                         source_table="data_source_health")
            if tier != "insight_only":
                create_recommendation(conn, hid, "ingestion", src["recommendation"],
                                      title, desc, sample_size=src["signals_seen"],
                                      confidence=src["reliability_score"] / 100,
                                      risk_level="low")
            h["hypothesis_id"] = hid

        hypotheses.append(h)

    return hypotheses


def save_scores(conn, analysis, dry_run=True):
    """Save source learning scores to DB."""
    if dry_run:
        return
    cur = conn.cursor()
    for src in analysis["sources"]:
        cur.execute("""
            INSERT INTO source_learning_scores
                (source_key, window_start, window_end, signals_seen, unique_symbols,
                 usefulness_score, reliability_score, recommendation, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_key, window_start, window_end) DO UPDATE SET
                signals_seen=EXCLUDED.signals_seen, usefulness_score=EXCLUDED.usefulness_score,
                reliability_score=EXCLUDED.reliability_score, recommendation=EXCLUDED.recommendation
        """, [src["source_key"], src["window_start"], src["window_end"],
              src["signals_seen"], src["unique_symbols"],
              src["usefulness_score"], src["reliability_score"],
              src["recommendation"], json.dumps(src, default=str)])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Ingestion Learning Engine")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--source", help="Filter by source key")
    parser.add_argument("--topic", help="Filter by topic slug")
    parser.add_argument("--create-proposals", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--window-days", type=int, default=30)
    args = parser.parse_args()

    conn = _get_conn()
    try:
        if args.analyze or args.source or args.topic:
            analysis = analyze_sources(conn, source_filter=args.source,
                                       window_days=args.window_days)
            hypotheses = generate_hypotheses(conn, analysis, dry_run=args.dry_run)
            save_scores(conn, analysis, dry_run=args.dry_run)

            out = {
                "mode": "dry_run" if args.dry_run else "applied",
                "sources_analyzed": len(analysis["sources"]),
                "news_sources": len(analysis["news_sources"]),
                "topics": len(analysis["topics"]),
                "hypotheses_generated": len(hypotheses),
                "window_days": args.window_days,
            }
            if args.json:
                out["sources"] = analysis["sources"]
                out["hypotheses"] = hypotheses
                print(json.dumps(out, indent=2, default=str))
            else:
                print(f"Ingestion Learning: {out['sources_analyzed']} sources, "
                      f"{out['hypotheses_generated']} hypotheses ({out['mode']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
