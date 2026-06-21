#!/usr/bin/env python3
"""region_tag_news.py — populate news_articles region columns for the inference RegionalLayer.

The inference cycle's RegionalLayer reasons about cross-market (Asia/Europe/EM → US) impacts, but the
ingestion layer reported "0 region-tagged" because nothing was filling news_articles.region. This runs the
cheap keyword classifier (inference_hermes_query.classify_region — no LLM) over recently-ingested, untagged
news and writes region / geo_keywords / region_tagged_at. Idempotent; advisory; safe to re-run.

  python3 scripts/region_tag_news.py [--hours 96] [--max 4000] [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(str(ROOT / ".env"))
from db_adapter import _get_conn


def run(hours=96, max_rows=4000, dry_run=False):
    try:
        from inference_hermes_query import classify_region
    except Exception as e:
        print(f"ABORT: classify_region unavailable ({e})"); return 1
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT id, title, summary FROM news_articles
                   WHERE region IS NULL AND created_at > now() - interval %s
                   ORDER BY created_at DESC LIMIT %s""", (f"{hours} hours", max_rows))
    rows = cur.fetchall()
    tally = {}
    for nid, title, summary in rows:
        region, hits = classify_region(title or "", summary or "")
        tally[region] = tally.get(region, 0) + 1
        if not dry_run:
            cur.execute("""UPDATE news_articles
                           SET region=%s, geo_keywords=%s, region_tagged_at=now()
                           WHERE id=%s""", (region, json.dumps(hits[:8]), nid))
    if not dry_run:
        conn.commit()
    print(json.dumps({"mode": "DRY" if dry_run else "APPLIED", "candidates": len(rows),
                      "by_region": tally}, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=96)
    ap.add_argument("--max", type=int, default=4000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    raise SystemExit(run(hours=a.hours, max_rows=a.max, dry_run=a.dry_run))
