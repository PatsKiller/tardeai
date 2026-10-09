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

# ── fused_signal embed text (storage audit 2026-10-09 #1) ─────────────────────
# The old text was symbol||' signal '||direction||' severity:'||severity. signal_fusion.py never
# writes `direction`, so every row embedded as "SYM signal  severity:low": 958k rows, ~14 distinct
# vectors, ~7 GB of content_embeddings with no retrieval value. The text now carries the real
# fields (scores, contributing sources, strategy, severity, sentiment lean, hour bucket), and a
# row whose meaningful fields are all empty is SKIPPED (counted, never embedded).
#
# FUSED_MEANINGFUL_SQL is a prefilter so skipped rows are not re-selected forever by the
# NOT EXISTS + LIMIT 5000 loop (they would starve real rows); fused_signal_is_meaningful() is
# the same rule in Python and is what decides. Keep the two in step.
SENTIMENT_NEUTRAL = 0.5
SENTIMENT_BAND = 0.05
FUSED_COMPONENTS = ("catalyst", "news", "social", "research")

FUSED_MEANINGFUL_SQL = (
    "(COALESCE(f.direction,'') <> ''"
    " OR COALESCE(f.catalyst_score,0) <> 0 OR COALESCE(f.news_score,0) <> 0"
    " OR COALESCE(f.social_score,0) <> 0 OR COALESCE(f.research_score,0) <> 0"
    f" OR abs(COALESCE(f.sentiment_score,{SENTIMENT_NEUTRAL}) - {SENTIMENT_NEUTRAL}) >= {SENTIMENT_BAND}"
    " OR COALESCE(cardinality(f.reason_codes),0) > 0"
    " OR COALESCE(cardinality(f.research_insight_ids),0) > 0"
    " OR COALESCE(f.top_signals,'[]'::jsonb) NOT IN ('[]'::jsonb,'null'::jsonb)"
    " OR COALESCE(f.contradictions,'[]'::jsonb) NOT IN ('[]'::jsonb,'null'::jsonb))"
)


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _nonempty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, tuple, dict, str)):
        return len(v) > 0
    if isinstance(v, (int, float)):
        return v != 0
    return True


def fused_signal_is_meaningful(rec: dict) -> bool:
    """True when a fused signal carries anything beyond the neutral baseline. Mirrors FUSED_MEANINGFUL_SQL."""
    if str(rec.get("direction") or "").strip():
        return True
    if any((_num(rec.get(f"{c}_score")) or 0.0) != 0.0 for c in FUSED_COMPONENTS):
        return True
    sent = _num(rec.get("sentiment_score"))
    if sent is not None and abs(sent - SENTIMENT_NEUTRAL) >= SENTIMENT_BAND:
        return True
    return any(_nonempty(rec.get(k)) for k in ("reason_codes", "research_insights", "top_signals", "contradictions"))


def _hour_bucket(ts) -> str:
    from datetime import datetime, timezone
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts))
        except (TypeError, ValueError):
            return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:00Z")


def _short(v, n=40) -> str:
    if isinstance(v, dict):
        for k in ("type", "signal", "source", "name", "code"):
            if v.get(k):
                return str(v[k])[:n]
        return json.dumps(v, default=str, sort_keys=True)[:n]
    return str(v)[:n]


def build_fused_signal_text(rec) -> "tuple[str, str] | None":
    """(embed_text, title) for one fused_signals record, or None when it must not be embedded."""
    if isinstance(rec, str):
        try:
            rec = json.loads(rec)
        except ValueError:
            return None
    if not isinstance(rec, dict):
        return None
    sym = str(rec.get("symbol") or "").strip().upper()
    if not sym or not fused_signal_is_meaningful(rec):
        return None
    bucket = _hour_bucket(rec.get("created_at"))
    severity = str(rec.get("severity") or "unrated")
    fused = _num(rec.get("fused_score"))
    conf = _num(rec.get("confidence"))
    sent = _num(rec.get("sentiment_score"))
    sources = sorted(((c, _num(rec.get(f"{c}_score")) or 0.0) for c in FUSED_COMPONENTS),
                     key=lambda t: abs(t[1]), reverse=True)
    sources = [(c, v) for c, v in sources if v != 0.0]
    if sent is None or abs(sent - SENTIMENT_NEUTRAL) < SENTIMENT_BAND:
        lean = "neutral"
    else:
        lean = "bullish" if sent > SENTIMENT_NEUTRAL else "bearish"
    direction = str(rec.get("direction") or "").strip()
    parts = [f"{sym} fused signal {bucket}"]
    if rec.get("strategy_type"):
        parts.append(f"strategy {rec['strategy_type']}")
    parts.append(f"severity {severity}")
    if direction:
        parts.append(f"direction {direction}")
    parts.append(f"sentiment {lean}" + (f" {sent:.2f}" if sent is not None else ""))
    if fused is not None:
        parts.append(f"fused score {fused:.3f}" + (f" confidence {conf:.3f}" if conf is not None else ""))
    parts.append("sources " + (", ".join(f"{c} {v:.2f}" for c, v in sources) if sources else "none"))
    if _nonempty(rec.get("research_insights")):
        parts.append(f"research insights {rec['research_insights']}")
    if _nonempty(rec.get("contradictions")):
        parts.append(f"contradictions {rec['contradictions']}")
    top = rec.get("top_signals")
    if isinstance(top, list) and top:
        parts.append("top signals " + "; ".join(_short(t) for t in top[:3]))
    codes = rec.get("reason_codes")
    if isinstance(codes, list) and codes:
        parts.append("reasons " + ", ".join(str(c)[:30] for c in codes[:5]))
    text = " · ".join(parts)
    src_names = ",".join(c for c, _ in sources) or lean
    title = f"{sym} signal: {severity} {direction + ' ' if direction else ''}fused " + (
        f"{fused:.2f}" if fused is not None else "n/a") + f" ({src_names}) {bucket}"
    return text, title[:300]


TEXT_BUILDERS = {"fused_signal": build_fused_signal_text}

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
        # Record as JSON; build_fused_signal_text() makes the text (see FUSED_MEANINGFUL_SQL above).
        "sql": "SELECT f.id, jsonb_build_object("
               "'symbol', f.symbol, 'strategy_type', f.strategy_type, 'direction', f.direction, "
               "'severity', f.severity, 'fused_score', f.fused_score, 'confidence', f.confidence, "
               "'catalyst_score', f.catalyst_score, 'news_score', f.news_score, 'social_score', f.social_score, "
               "'research_score', f.research_score, 'sentiment_score', f.sentiment_score, "
               "'research_insights', COALESCE(cardinality(f.research_insight_ids),0), "
               "'contradictions', CASE WHEN jsonb_typeof(f.contradictions)='array' THEN jsonb_array_length(f.contradictions) ELSE 0 END, "
               "'top_signals', COALESCE(f.top_signals,'[]'::jsonb), "
               "'reason_codes', COALESCE(to_jsonb(f.reason_codes),'[]'::jsonb), "
               "'created_at', f.created_at)::text, ''::text, f.created_at FROM fused_signals f "
               "WHERE " + FUSED_MEANINGFUL_SQL,
        "date_col": "created_at",
        "text_builder": "fused_signal",
        "skip_count_sql": "SELECT count(*) FROM fused_signals f WHERE NOT " + FUSED_MEANINGFUL_SQL +
                          " AND NOT EXISTS (SELECT 1 FROM content_embeddings ce"
                          " WHERE ce.source_type='fused_signal' AND ce.source_id=f.id)",
        "skip_count_date_col": "f.created_at",
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


def index_source(source_type, hours_back=None, backfill=False, conn=None, dry_run=False, stats=None):
    """Index one source type. Returns (indexed, skipped).

    `stats` (optional dict) receives selected / indexed / embed_failed / skipped_empty (rows the
    text builder refused, plus rows the SQL prefilter declined) / samples (dry run only).
    dry_run builds the texts and counts, but calls no embedder and writes nothing."""
    st = stats if stats is not None else {}
    st.update(selected=0, indexed=0, embed_failed=0, skipped_empty=0, skipped_empty_prefilter=0)
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
        st["selected"] = len(rows)
        logger.info(f"  {source_type}: {len(rows)} rows to index")

        skip_sql = config.get("skip_count_sql")
        if skip_sql:
            if not backfill and hours_back:
                skip_sql += f" AND {config['skip_count_date_col']} > NOW() - INTERVAL '{int(hours_back)} hours'"
            cur.execute(skip_sql)
            st["skipped_empty_prefilter"] = int(cur.fetchone()[0] or 0)

        builder = TEXT_BUILDERS.get(config.get("text_builder") or "")
        indexed = 0
        for row_id, embed_txt, preview, dt in rows:
            if builder is not None:
                built = builder(embed_txt)
                if built is None:
                    st["skipped_empty"] += 1
                    continue
                embed_txt, preview = built
            if dry_run:
                indexed += 1
                if len(st.setdefault("samples", [])) < 3:
                    st["samples"].append({"title": preview, "text": str(embed_txt)[:400]})
                continue
            vec = embed_text(str(embed_txt or "")[:2000])
            if vec is None:
                st["embed_failed"] += 1
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
        st["indexed"] = indexed
        st["skipped_empty"] += st["skipped_empty_prefilter"]
        logger.info(f"  {source_type}: {indexed} {'would index' if dry_run else 'new'}, {len(rows)-indexed} skipped"
                    f" (skipped_empty={st['skipped_empty']}, embed_failed={st['embed_failed']})")

        # === IER WRITE-BACK: update RAG coverage counts (non-fatal) ===
        if indexed > 0 and not dry_run:
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="RAG Indexer — embed all intelligence sources")
    parser.add_argument("--source", default="all", help="Comma-separated source types or 'all'")
    parser.add_argument("--hours", type=int, default=None, help="Only index items from last N hours")
    parser.add_argument("--backfill", action="store_true", help="Index ALL rows regardless of age")
    parser.add_argument("--dry-run", action="store_true",
                        help="Select and build texts, report counts; no embedding call, no write")
    args = parser.parse_args(argv)

    sources = list(SOURCE_CONFIGS.keys()) if args.source == "all" else args.source.split(",")
    conn = _get_conn()

    total = 0
    summary = {}
    for st in sources:
        stats = {}
        n, s = index_source(st.strip(), hours_back=args.hours, backfill=args.backfill, conn=conn,
                            dry_run=args.dry_run, stats=stats)
        summary[st.strip()] = stats
        total += n

    conn.close()
    logger.info(f"RAG indexer complete: {total} total {'would-index' if args.dry_run else 'new'} embeddings")
    # One machine-readable line per run: the skip count is recorded, not just logged in prose.
    print("RAG_INDEXER_SUMMARY " + json.dumps({"dry_run": args.dry_run, "total": total, "sources": summary},
                                              default=str, sort_keys=True), flush=True)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    _run_id = None
    try:
        if "--dry-run" not in sys.argv[1:]:  # a dry run records no pipeline run
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
