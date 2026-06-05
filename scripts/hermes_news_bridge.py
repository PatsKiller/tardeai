#!/usr/bin/env python3
"""Hermes news bridge (2026-06-04) — Prompt #2.

Bridges Hermes's discovered, ticker-level news (hermes_research_intelligence) into the
TradeAI catalyst path by inserting into news_articles with source='hermes'. The already-
repaired chain then takes over: news_to_catalyst.py classifies these into catalyst_events,
and signal_fusion.py consumes them. No Docker crossing — both ends are the shared Postgres.

HERMES WALL: this job is READ-ONLY on hermes_* tables. It writes ONLY news_articles (the
TradeAI catalyst feed). It never writes back to Hermes-controlled tables or any trading table.

Dedup is tracked on the TradeAI side: each bridged row carries raw_payload.hermes_research_id,
and we skip Hermes rows already bridged. Downstream, catalyst_events(symbol,headline) is unique,
so a Hermes article duplicating an existing one cannot create a duplicate catalyst.

Usage:
  python3 scripts/hermes_news_bridge.py [--limit 200] [--lookback-hours 48] [--json]
"""
import os, sys, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Ticker-level Hermes research worth treating as catalyst news. research_backlog is
# topic-level (no symbol) and excluded; thesis_challenge/youtube can be added later.
BRIDGE_TYPES = ("momentum_catalyst",)


def load_env():
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def _first_url(source_urls_json):
    try:
        v = source_urls_json
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, list) and v:
            return str(v[0])[:1000]
        if isinstance(v, dict) and v:
            return str(next(iter(v.values())))[:1000]
    except Exception:
        pass
    return None


def _strategy_type(strategy_tags):
    try:
        v = strategy_tags
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, list) and v:
            return str(v[0])[:60]
    except Exception:
        pass
    return None


def run(limit=200, lookback_hours=48, as_json=False):
    load_env()
    conn = db(); cur = conn.cursor()
    types = ",".join("%s" for _ in BRIDGE_TYPES)
    # READ-ONLY on hermes_*; only ticker-level rows not already bridged into news_articles.
    cur.execute(f"""
        SELECT h.id, h.symbol, h.topic, h.summary, h.source_urls_json,
               h.confidence_score, h.freshness_date, h.created_at, h.research_type, h.strategy_tags
        FROM hermes_research_intelligence h
        WHERE h.symbol IS NOT NULL AND h.symbol <> ''
          AND h.topic IS NOT NULL AND h.topic <> ''
          AND h.research_type IN ({types})
          AND h.created_at > now() - interval '%s hours'
          AND NOT EXISTS (
              SELECT 1 FROM news_articles n
              WHERE n.source = 'hermes'
                AND (n.raw_payload->>'hermes_research_id') = h.id::text
          )
        ORDER BY h.created_at DESC
        LIMIT %s
    """, list(BRIDGE_TYPES) + [lookback_hours, limit])
    rows = cur.fetchall()

    bridged, skipped_dup = [], 0
    for hid, symbol, topic, summary, urls, conf, fresh, created, rtype, stags in rows:
        title = str(topic)[:500]
        # Also skip if an identical hermes article (symbol,title) is already present.
        cur.execute("""SELECT 1 FROM news_articles
                       WHERE source='hermes' AND symbol=%s AND title=%s LIMIT 1""",
                    (symbol, title))
        if cur.fetchone():
            skipped_dup += 1
            continue
        # Rating alignment (2026-06-04): score Hermes-ingested articles with the SAME framework
        # TradeAI's news_ingestion uses (content_scoring.score_content) so all news_articles share
        # one relevance/quality scale, regardless of which engine ingested them. Hermes's own
        # confidence is kept in raw_payload for provenance, not used as the relevance score.
        try:
            from content_scoring import score_content
            scored = score_content(title, str(summary or ""), source="hermes", symbols=[symbol] if symbol else None)
        except Exception:
            scored = {"relevance_score": (float(conf) if conf is not None else 0.5),
                      "quality_score": None, "validation_status": "unscored"}
        payload = {"hermes_research_id": hid, "research_type": rtype,
                   "bridged_by": "hermes_news_bridge.py",
                   "bridged_at": datetime.now(timezone.utc).isoformat(),
                   "hermes_confidence": (round(float(conf), 3) if conf is not None else None),
                   "quality_score": scored.get("quality_score"),
                   "validation_status": scored.get("validation_status")}
        try:
            cur.execute("""
                INSERT INTO news_articles
                    (symbol, strategy_type, title, summary, source, source_url,
                     published_at, relevance_score, raw_payload, created_at)
                VALUES (%s, %s, %s, %s, 'hermes', %s, %s, %s, %s, now())
                RETURNING id
            """, (symbol, _strategy_type(stags), title,
                  (str(summary)[:1000] if summary else None),
                  _first_url(urls), (fresh or created),
                  round(float(scored.get("relevance_score") or 0.0), 3),
                  json.dumps(payload)))
            new_id = cur.fetchone()[0]
            bridged.append({"news_id": new_id, "hermes_id": hid, "symbol": symbol,
                            "title": title[:50], "type": rtype})
        except Exception as e:
            conn.rollback()
            print(f"  [bridge] {symbol}: insert error — {str(e)[:90]}")
            continue
    conn.commit()
    report = {"run_at": datetime.now(timezone.utc).isoformat(),
              "candidates": len(rows), "bridged": len(bridged),
              "skipped_dup": skipped_dup, "rows": bridged[:20]}
    conn.close()
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"[hermes-bridge] {len(bridged)} bridged, {skipped_dup} dup-skipped, "
              f"{len(rows)} candidates")
        for b in bridged[:15]:
            print(f"  {b['symbol']:>8} | {b['type']:<18} | news#{b['news_id']} <- hermes#{b['hermes_id']}")
    return report


if __name__ == "__main__":
    a = sys.argv
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 200
    lookback = int(a[a.index("--lookback-hours") + 1]) if "--lookback-hours" in a else 48
    run(limit=limit, lookback_hours=lookback, as_json="--json" in a)
