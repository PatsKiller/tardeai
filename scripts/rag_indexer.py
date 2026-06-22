#!/usr/bin/env python3
"""rag_indexer.py — Universal RAG Indexer for Trade AI v12.

Indexes all intelligence source types into content_embeddings.
Idempotent: uses ON CONFLICT (source_type, source_id) DO NOTHING.

CLI:
  python3 scripts/rag_indexer.py --source all --hours 2
  python3 scripts/rag_indexer.py --backfill
  python3 scripts/rag_indexer.py --source agent_result,cio_decision --hours 8
"""
import argparse, logging, sys, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rag_retrieval import embed_text

logger = logging.getLogger(__name__)

# Column names verified from live schema on 2026-05-01
SOURCE_CONFIGS = {
    "news": {
        "sql": "SELECT id, COALESCE(title,'')||' '||COALESCE(symbol,''), COALESCE(title,''), created_at FROM news_articles",
        "date_col": "created_at",
    },
    "youtube": {
        "sql": "SELECT id, COALESCE(title,'')||' '||COALESCE(channel_name,''), COALESCE(title,''), ingested_at FROM youtube_transcripts",
        "date_col": "ingested_at",
    },
    "social_post": {
        "sql": "SELECT id, COALESCE(text,'')||' '||COALESCE(username,''), LEFT(COALESCE(text,''),200), ingested_at FROM social_posts",
        "date_col": "ingested_at",
    },
    "sec_form4": {
        "sql": "SELECT id, COALESCE(symbol,'')||' '||COALESCE(filer_name,'')||' '||transaction_type, COALESCE(symbol,'')||' Form 4: '||COALESCE(filer_name,''), created_at FROM sec_form4",
        "date_col": "created_at",
    },
    "fred_series": {
        "sql": "SELECT id, COALESCE(series_id,'')||' '||COALESCE(series_name,'')||' '||COALESCE(value::text,''), COALESCE(series_name,'')||': '||COALESCE(value::text,''), fetched_at FROM fred_economic_series",
        "date_col": "fetched_at",
    },
    "agent_result": {
        # id is TEXT (e.g. res-wl-schd-maria-20260426) — use hashtext for numeric source_id
        "sql": "SELECT abs(hashtext(id)), COALESCE(symbol,'')||' '||COALESCE(agent,'')||' '||COALESCE(recommendation,'')||' '||LEFT(COALESCE(summary,''),500), COALESCE(symbol,'')||' '||COALESCE(agent,'')||': '||COALESCE(recommendation,''), created_at FROM watchlist_agent_results",
        "date_col": "created_at",
    },
    "agent_synthesis": {
        # PK is symbol (text), no numeric id — use hashtext
        "sql": "SELECT abs(hashtext(symbol)), COALESCE(symbol,'')||' synthesis '||COALESCE(recommendation,'')||' '||COALESCE(synthesis_narrative,''), COALESCE(symbol,'')||' synthesis: '||COALESCE(recommendation,''), created_at FROM watchlist_final_synthesis",
        "date_col": "created_at",
    },
    "cio_decision": {
        # decision_id is TEXT — use hashtext
        "sql": "SELECT abs(hashtext(decision_id)), COALESCE(symbol,'')||' CIO '||COALESCE(action,'')||' '||LEFT(COALESCE(rationale,''),500), COALESCE(symbol,'')||' CIO: '||COALESCE(action,''), created_at FROM cio_decisions",
        "date_col": "created_at",
    },
    "fused_signal": {
        "sql": "SELECT id, COALESCE(symbol,'')||' signal '||COALESCE(direction,'')||' severity:'||COALESCE(severity::text,''), COALESCE(symbol,'')||' signal: '||COALESCE(direction,''), created_at FROM fused_signals",
        "date_col": "created_at",
    },
    "decision_outcome": {
        "sql": "SELECT id, COALESCE(symbol,'')||' outcome: '||COALESCE(recommendation,'')||' '||COALESCE(notes,''), COALESCE(symbol,'')||' outcome: '||COALESCE(recommendation,''), created_at FROM decision_outcomes",
        "date_col": "created_at",
    },
    "research_finding": {
        "sql": "SELECT id, COALESCE(topic,'')||' '||COALESCE(latest_findings,''), COALESCE(topic,''), COALESCE(latest_finding_at, updated_at) FROM user_research_topics WHERE status='active' AND latest_findings IS NOT NULL",
        "date_col": "latest_finding_at",
    },
    "hermes_research": {
        "sql": """SELECT id,
            COALESCE(topic,'')||' '||COALESCE(summary,'')||' '||COALESCE(thesis,'')||' '||COALESCE(symbol,''),
            COALESCE(topic,''), created_at
            FROM hermes_research_intelligence WHERE status='promoted'""",
        "date_col": "created_at",
    },
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def index_source(source_type, hours_back=None, backfill=False, conn=None):
    """Index one source type. Returns (indexed, skipped)."""
    config = SOURCE_CONFIGS.get(source_type)
    if not config:
        logger.error(f"Unknown source type: {source_type}")
        return 0, 0

    close_conn = conn is None
    if close_conn:
        conn = _get_conn()
    cur = conn.cursor()

    try:
        base_sql = config["sql"]
        where_parts = []
        params = []

        # Only rows not already embedded
        where_parts.append(f"NOT EXISTS (SELECT 1 FROM content_embeddings ce WHERE ce.source_type='{source_type}' AND ce.source_id=sub.id)")

        if not backfill and hours_back:
            where_parts.append(f"sub.dt > NOW() - INTERVAL '{int(hours_back)} hours'")

        # Wrap base SQL as subquery with standardized column names
        sql = f"SELECT sub.id, sub.embed_text, sub.preview, sub.dt FROM ({base_sql}) AS sub(id, embed_text, preview, dt)"
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        sql += " LIMIT 5000"

        cur.execute(sql, params)
        rows = cur.fetchall()
        logger.info(f"  {source_type}: {len(rows)} rows to index")

        indexed = 0
        for row_id, embed_txt, preview, dt in rows:
            vec = embed_text(str(embed_txt or "")[:2000])
            if vec is None:
                continue

            cur.execute("""
                INSERT INTO content_embeddings (source_type, source_id, title, embedding, embedding_model, embedding_dim, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (source_type, source_id) DO NOTHING
            """, (source_type, int(row_id), str(preview or "")[:300], json.dumps(vec), EMBED_MODEL, len(vec)))
            indexed += 1

            if indexed % 25 == 0:
                conn.commit()
                logger.info(f"  {source_type}: {indexed}/{len(rows)} indexed...")

        conn.commit()
        logger.info(f"  {source_type}: {indexed} new, {len(rows)-indexed} skipped")

        # === IER WRITE-BACK: update RAG coverage counts (non-fatal) ===
        if indexed > 0:
            try:
                from intelligence_entity_manager import upsert_entity as _iem_upsert
                from datetime import datetime as _dt, timezone as _tz
                # Find symbols/entities mentioned in indexed titles
                _seen = set()
                for _, _, preview, _ in rows[:100]:
                    if preview:
                        # Check for uppercase symbols (3-5 chars)
                        import re as _re
                        _syms = _re.findall(r'\b([A-Z]{2,5})\b', str(preview)[:200])
                        _seen.update(_syms[:3])
                for _s in list(_seen)[:20]:
                    _iem_upsert(conn, _s, 'market', {
                        'rag_last_indexed': _dt.now(_tz.utc),
                    }, source='rag_indexer')
            except Exception:
                pass
        # === END WRITE-BACK ===

        return indexed, len(rows) - indexed

    except Exception as e:
        logger.error(f"index_source failed for {source_type}: {e}")
        conn.rollback()
        return 0, 0
    finally:
        cur.close()
        if close_conn:
            conn.close()


EMBED_MODEL = "nomic-embed-text"


def main():
    parser = argparse.ArgumentParser(description="RAG Indexer — embed all intelligence sources")
    parser.add_argument("--source", default="all", help="Comma-separated source types or 'all'")
    parser.add_argument("--hours", type=int, default=None, help="Only index items from last N hours")
    parser.add_argument("--backfill", action="store_true", help="Index ALL rows regardless of age")
    args = parser.parse_args()

    sources = list(SOURCE_CONFIGS.keys()) if args.source == "all" else args.source.split(",")
    conn = _get_conn()

    total = 0
    for st in sources:
        n, s = index_source(st.strip(), hours_back=args.hours, backfill=args.backfill, conn=conn)
        total += n

    conn.close()
    logger.info(f"RAG indexer complete: {total} total new embeddings")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('rag_indexer')
    except Exception:
        pass
    try:
        main()
        try:
            if _run_id: run_complete(_run_id)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
