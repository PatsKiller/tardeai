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
  python3 scripts/hermes_news_bridge.py [--limit 200] [--lookback-hours 48] [--json] [--dry-run]

--dry-run runs the same candidate SELECT and scoring on a READ ONLY session and returns BEFORE
write_news_articles / commit are reachable, listing what it would bridge (the writer's own dedupe
is not evaluated, so "would_bridge" is an upper bound). A real run writes
data/runtime/hermes_news_bridge_last.json (LaneRunReceipt@v1; ok_at only on success) under the
persistent state root and exits 1 when the run failed or every insert attempt errored.
"""
import os, sys, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from lib.writers.news_articles_writer import write_news_articles  # noqa: E402  (the store's one write path)
# Ticker-level Hermes research worth treating as catalyst news. research_backlog is
# topic-level (no symbol) and excluded; thesis_challenge/youtube can be added later.
BRIDGE_TYPES = ("momentum_catalyst",)
RECEIPT_NAME = "hermes_news_bridge"


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


def run(limit=200, lookback_hours=48, as_json=False, dry_run=False):
    load_env()
    conn = db()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)
    cur = conn.cursor()
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

    bridged, skipped_dup, insert_errors = [], 0, 0
    would = []
    for hid, symbol, topic, summary, urls, conf, fresh, created, rtype, stags in rows:
        title = str(topic)[:500]
        # Dedupe is the write module's rule (same symbol + same source_url or title);
        # a duplicate writes nothing and is counted from the receipt below.
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
        if dry_run:
            would.append({"hermes_id": hid, "symbol": symbol, "title": title[:50], "type": rtype,
                          "relevance_score": round(float(scored.get("relevance_score") or 0.0), 3)})
            continue
        try:
            receipt = write_news_articles(cur, [{
                "symbol": symbol, "strategy_type": _strategy_type(stags), "title": title,
                "summary": (str(summary)[:1000] if summary else None), "source": "hermes",
                "source_url": _first_url(urls), "published_at": (fresh or created),
                "relevance_score": round(float(scored.get("relevance_score") or 0.0), 3),
                "raw_payload": json.dumps(payload),
            }], source="hermes")
            if not receipt.rows_written:
                skipped_dup += 1
                continue
            new_id = receipt.ids[0]
            bridged.append({"news_id": new_id, "hermes_id": hid, "symbol": symbol,
                            "title": title[:50], "type": rtype})
        except Exception as e:
            conn.rollback()
            insert_errors += 1
            print(f"  [bridge] {symbol}: insert error — {str(e)[:90]}")
            continue
    if dry_run:
        conn.close()
        report = {"run_at": datetime.now(timezone.utc).isoformat(), "dry_run": True,
                  "candidates": len(rows), "would_bridge": len(would), "rows": would[:20]}
        if as_json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"[hermes-bridge] DRY RUN: {len(rows)} candidates, would attempt {len(would)} "
                  f"news_articles inserts (writer dedupe not evaluated); nothing written")
            for w in would[:15]:
                print(f"  {w['symbol']:>8} | {w['type']:<18} | would bridge hermes#{w['hermes_id']}")
        return report
    conn.commit()
    report = {"run_at": datetime.now(timezone.utc).isoformat(),
              "candidates": len(rows), "bridged": len(bridged),
              "skipped_dup": skipped_dup, "insert_errors": insert_errors, "rows": bridged[:20]}
    conn.close()
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"[hermes-bridge] {len(bridged)} bridged, {skipped_dup} dup-skipped, "
              f"{len(rows)} candidates")
        for b in bridged[:15]:
            print(f"  {b['symbol']:>8} | {b['type']:<18} | news#{b['news_id']} <- hermes#{b['hermes_id']}")
    return report


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 200
    lookback = int(a[a.index("--lookback-hours") + 1]) if "--lookback-hours" in a else 48
    if "--dry-run" in a:
        run(limit=limit, lookback_hours=lookback, as_json="--json" in a, dry_run=True)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        rep = run(limit=limit, lookback_hours=lookback, as_json="--json" in a)
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"[hermes-bridge] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    summary = {k: rep[k] for k in ("candidates", "bridged", "skipped_dup", "insert_errors")}
    # Every attempted insert errored (none bridged, none a clean dup-skip): the run did not work.
    failed = rep["insert_errors"] > 0 and rep["bridged"] == 0 and rep["skipped_dup"] == 0
    write_receipt(RECEIPT_NAME, ok=not failed, summary=summary, started_at=started,
                  error="every news_articles insert errored" if failed else None)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
