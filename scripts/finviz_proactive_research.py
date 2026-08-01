#!/usr/bin/env python3
"""finviz_proactive_research.py — use Finviz for PROACTIVE research

Data Broker Phase 5: prefer news_ingestion.py as canonical writer; this script
feeds finviz_news rows with URL dedup against news_articles to avoid parallel drift. beyond screeners.

The screener runner discovers tickers; finviz_news.py can pull per-ticker headlines but was only ever
reactive (per-symbol on demand). This runs Finviz's Elite news_export proactively across the whole watch
universe (held + active watchlist + research-discovery candidates), persisting fresh headlines into
news_articles (source='finviz_news') so Finviz is a standing catalyst/research source — not just a screen.

Uses the same FINVIZ_API_TOKEN as the screeners (no extra creds). Deduped by source_url. Advisory.

  python3 scripts/finviz_proactive_research.py [--max 150] [--lookback-hours 72] [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(str(ROOT / ".env"))
from db_adapter import _get_conn


def _universe(cur, max_n):
    """Held + active watchlist + research-discovery candidates — the names worth proactive coverage."""
    syms = []
    try:
        hj = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        syms += [str(h.get("symbol", "")).upper() for h in hj.get("holdings", [])
                 if h.get("symbol") and not h.get("is_cash")]
    except Exception:
        pass
    cur.execute("""SELECT DISTINCT symbol FROM watchlist_items
                   WHERE status <> 'removed' AND symbol ~ '^[A-Z]{1,5}$'
                   ORDER BY symbol""")
    syms += [r[0] for r in cur.fetchall()]
    # de-dup, keep order, cap
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s); out.append(s)
    return out[:max_n]


def run(max_n=150, lookback_hours=72, dry_run=False):
    try:
        from finviz_news import fetch_finviz_stock_news_all
        from content_scoring import score_content, tag_content
    except Exception as e:
        print(f"ABORT: deps unavailable ({e})"); return 1
    conn = _get_conn(); cur = conn.cursor()
    universe = set(_universe(cur, max_n))
    # ONE request for all ticker-tagged Stock news, then distribute to the universe (a headline can tag
    # several tickers, e.g. "CVX,NOC,LMT" → saved once per universe ticker it mentions).
    allnews = fetch_finviz_stock_news_all(lookback_hours=lookback_hours)
    print(f"finviz proactive research: {len(allnews)} stock-news items vs {len(universe)}-symbol universe "
          f"({'DRY' if dry_run else 'LIVE'})")
    saved, skipped, covered = 0, 0, set()
    for it in allnews:
        head = (it.get("headline") or "")[:500]
        url = (it.get("url") or "")[:500]
        if not head or not url:
            continue
        hits = [t for t in it.get("tickers", []) if t in universe]
        for sym in hits:
            cur.execute("SELECT 1 FROM news_articles WHERE source_url=%s AND symbol=%s LIMIT 1", (url, sym))
            if cur.fetchone():
                skipped += 1; continue
            covered.add(sym)
            if dry_run:
                saved += 1; continue
            try:
                from hermes_source_policy import should_ingest
                ok, _why = should_ingest("finviz_news")
                if not ok:
                    skipped += 1
                    continue
                sc = score_content(title=head, text="", source="finviz_news", symbols=[sym])
                tg = tag_content(text="", title=head)
                pub = datetime.fromtimestamp(int(it["datetime"]), tz=timezone.utc) if it.get("datetime") else None
                cur.execute("""INSERT INTO news_articles
                    (symbol, strategy_type, title, summary, source, source_url, published_at,
                     relevance_score, strategy_tags, agent_tags)
                    VALUES (%s,%s,%s,%s,'finviz_news',%s,%s,%s,%s,%s)""",
                    (sym, sym, head, "", url, pub, sc.get("relevance_score", 0.5),
                     json.dumps(tg.get("strategy_tags", [])), json.dumps(tg.get("agent_tags", []))))
                saved += 1
            except Exception as e:
                conn.rollback(); print(f"  {sym}: save error {str(e)[:50]}"); continue
    if not dry_run:
        conn.commit()
    print(json.dumps({"news_items": len(allnews), "universe": len(universe),
                      "symbols_covered": len(covered), "saved": saved, "skipped_dup": skipped,
                      "mode": "DRY" if dry_run else "LIVE"}, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--lookback-hours", type=int, default=72)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    raise SystemExit(run(max_n=a.max, lookback_hours=a.lookback_hours, dry_run=a.dry_run))
