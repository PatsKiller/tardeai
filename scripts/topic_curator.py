#!/usr/bin/env python3
"""
topic_curator.py — Post-ingestion LLM curation pipeline.

Runs AFTER topic_ingestion.py to:
1. Rate pending content (RAG-worthy / low_quality / blocked)
2. Extract entities (tickers, topics, sectors, people) → content_entity_links
3. Link content to existing DB records (enrichment cache, holdings, watchlist)
4. Generate improved queries for next ingestion run
5. Trigger RAG re-indexing of approved content
6. Log curation feedback for learning loop

The curation loop makes each iteration stronger:
  ingestion → curation → entity linking → RAG index → agents use it →
  agents rate quality → curation adjusts queries → better ingestion

Usage:
    python topic_curator.py                    # curate all pending
    python topic_curator.py --topic ssdi       # single topic
    python topic_curator.py --reindex          # force RAG re-index
    python topic_curator.py --improve-queries  # LLM generates better queries
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)

def _get_conn():
    import psycopg2, psycopg2.extras
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))

def _send_telegram(msg):
    import urllib.request, urllib.parse
    token = _env("TELEGRAM_BOT_TOKEN")
    for cid in _env("TELEGRAM_CHAT_ID").split(","):
        cid = cid.strip()
        if not cid or not token: continue
        try:
            data = urllib.parse.urlencode({"chat_id": cid, "text": msg[:4000]}).encode()
            urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data),
                timeout=10)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# STEP 1: RATE PENDING CONTENT  (RAG / low_quality / blocked)
# ════════════════════════════════════════════════════════════
def rate_pending_content(conn, topic_id=None, limit=50):
    """LLM rates pending articles and transcripts. Tight prompt."""
    try:
        from local_llm import generate
    except ImportError:
        print("  [curator] No LLM available, skipping rating")
        return 0, 0, 0

    cur = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)

    # Get pending articles
    sql = "SELECT id, title, summary, strategy_type FROM news_articles WHERE rag_status='pending' AND source LIKE 'topic_%%'"
    params = []
    if topic_id:
        sql += " AND strategy_type = %s"
        params.append(topic_id)
    sql += f" ORDER BY created_at DESC LIMIT {limit}"
    cur.execute(sql, params)
    articles = cur.fetchall()

    # Get pending transcripts
    sql2 = "SELECT id, video_id, title, LEFT(transcript_text, 500) as preview FROM youtube_transcripts WHERE rag_status='pending' AND added_by='topic_ingestion'"
    params2 = []
    if topic_id:
        sql2 += " AND strategy_tags::text LIKE %s"
        params2.append(f'%{topic_id}%')
    sql2 += f" ORDER BY ingested_at DESC LIMIT {limit}"
    cur.execute(sql2, params2)
    transcripts = cur.fetchall()

    total = len(articles) + len(transcripts)
    if total == 0:
        print("  [curator] No pending content to rate")
        return 0, 0, 0

    print(f"  [curator] Rating {len(articles)} articles + {len(transcripts)} transcripts...")

    approved = 0
    blocked = 0

    # Batch articles in groups of 5 for efficient LLM usage
    for i in range(0, len(articles), 5):
        batch = articles[i:i+5]
        titles = "\n".join(f"{j+1}. {a['title'][:80]}" for j, a in enumerate(batch))
        prompt = (
            f"/no_think Rate these articles for RAG indexing. Topic context: financial intelligence, "
            f"retirement planning, SSDI, trading strategies.\n\n{titles}\n\n"
            f"Reply ONLY with JSON array: "
            f'[{{"id": 1, "rag": "approved" or "low_quality" or "blocked", "reason": "5 words max"}}]'
        )
        raw = generate(prompt, timeout=30, fallback=False, fast=True)
        if raw:
            try:
                match = re.search(r'\[.*\]', raw, re.DOTALL)
                if match:
                    ratings = json.loads(match.group())
                    for r in ratings:
                        idx = r.get("id", 1) - 1
                        if 0 <= idx < len(batch):
                            status = r.get("rag", "pending")
                            if status not in ("approved", "low_quality", "blocked"):
                                status = "pending"
                            reason = r.get("reason", "")[:200]
                            cur.execute("UPDATE news_articles SET rag_status=%s, rag_reason=%s WHERE id=%s",
                                        (status, reason, batch[idx]['id']))
                            if status == "approved": approved += 1
                            if status == "blocked": blocked += 1
            except Exception:
                pass
        conn.commit()

    # Rate transcripts individually (they have more content to judge)
    for t in transcripts:
        prompt = (
            f"/no_think Rate this transcript for RAG. Title: {t['title'][:80]}\n"
            f"Preview: {t['preview'][:300]}\n\n"
            f'Reply JSON: {{"rag": "approved"/"low_quality"/"blocked", "reason": "5 words"}}'
        )
        raw = generate(prompt, timeout=20, fallback=False, fast=True)
        if raw:
            try:
                match = re.search(r'\{[^}]+\}', raw)
                if match:
                    r = json.loads(match.group())
                    status = r.get("rag", "pending")
                    if status in ("approved", "low_quality", "blocked"):
                        cur.execute("UPDATE youtube_transcripts SET rag_status=%s, rag_reason=%s WHERE id=%s",
                                    (status, r.get("reason", ""), t['id']))
                        if status == "approved": approved += 1
                        if status == "blocked":
                            blocked += 1
                            cur.execute("""
                                INSERT INTO blocked_content (content_type, content_id, title, reason, blocked_by, topic_id)
                                VALUES ('youtube', %s, %s, %s, 'llm_curator', %s)
                                ON CONFLICT DO NOTHING
                            """, (t['video_id'], t['title'][:500], r.get("reason", ""), topic_id or ""))
            except Exception:
                pass
        conn.commit()

    print(f"  [curator] Rated {total}: {approved} approved, {blocked} blocked, {total-approved-blocked} low_quality/pending")
    return total, approved, blocked


# ════════════════════════════════════════════════════════════
# STEP 2: EXTRACT ENTITIES (tickers, topics, sectors, etc.)
# ════════════════════════════════════════════════════════════
def extract_and_link_entities(conn, topic_id=None, limit=100):
    """
    LLM extracts tickers, sectors, topics, orgs from content.
    Links by whatever is logical:
    - Articles about NVDA → entity_type='ticker', entity_value='NVDA'
    - Articles about SSDI → entity_type='topic', entity_value='ssdi'
    - Articles about semiconductors → entity_type='sector', entity_value='semiconductors'
    """
    try:
        from local_llm import generate
    except ImportError:
        print("  [curator] No LLM, skipping entity extraction")
        return 0

    cur = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)

    # Get articles without entity links yet
    sql = """
        SELECT na.id, na.title, na.summary, na.strategy_type
        FROM news_articles na
        WHERE na.source LIKE 'topic_%%'
        AND na.rag_status IN ('approved', 'pending')
        AND NOT EXISTS (SELECT 1 FROM content_entity_links cel
                        WHERE cel.content_type='news_article' AND cel.content_id=na.id)
    """
    params = []
    if topic_id:
        sql += " AND na.strategy_type = %s"
        params.append(topic_id)
    sql += f" ORDER BY na.created_at DESC LIMIT {limit}"
    cur.execute(sql, params)
    articles = cur.fetchall()

    if not articles:
        print("  [curator] No articles need entity extraction")
        return 0

    print(f"  [curator] Extracting entities from {len(articles)} articles...")
    total_links = 0

    # Batch 10 at a time
    for i in range(0, len(articles), 10):
        batch = articles[i:i+10]
        items = "\n".join(f"{j+1}. [{a['strategy_type']}] {a['title'][:80]}" for j, a in enumerate(batch))
        prompt = (
            f"/no_think Extract entities from these articles. For each, identify:\n"
            f"- tickers (stock symbols mentioned)\n"
            f"- topics (SSDI, Medicare, Roth, trust, etc.)\n"
            f"- sectors (technology, healthcare, energy, etc.)\n\n"
            f"{items}\n\n"
            f'Reply JSON array: [{{"id": 1, "tickers": ["NVDA"], "topics": ["ai_infrastructure"], "sectors": ["technology"]}}]'
            f'\nIf no tickers, use topics/sectors. Every item must link to something.'
        )
        raw = generate(prompt, timeout=30, fallback=False, fast=True)
        if raw:
            try:
                match = re.search(r'\[.*\]', raw, re.DOTALL)
                if match:
                    results = json.loads(match.group())
                    for r in results:
                        idx = r.get("id", 1) - 1
                        if 0 <= idx < len(batch):
                            article_id = batch[idx]['id']
                            for ticker in r.get("tickers", []):
                                ticker = ticker.upper().strip()
                                if ticker and len(ticker) <= 6:
                                    cur.execute("""
                                        INSERT INTO content_entity_links (content_type, content_id, entity_type, entity_value, extracted_by)
                                        VALUES ('news_article', %s, 'ticker', %s, 'llm_curator')
                                        ON CONFLICT DO NOTHING
                                    """, (article_id, ticker))
                                    total_links += 1
                            for topic in r.get("topics", []):
                                topic = topic.lower().strip().replace(" ", "_")
                                if topic:
                                    cur.execute("""
                                        INSERT INTO content_entity_links (content_type, content_id, entity_type, entity_value, extracted_by)
                                        VALUES ('news_article', %s, 'topic', %s, 'llm_curator')
                                        ON CONFLICT DO NOTHING
                                    """, (article_id, topic))
                                    total_links += 1
                            for sector in r.get("sectors", []):
                                sector = sector.lower().strip()
                                if sector:
                                    cur.execute("""
                                        INSERT INTO content_entity_links (content_type, content_id, entity_type, entity_value, extracted_by)
                                        VALUES ('news_article', %s, 'sector', %s, 'llm_curator')
                                        ON CONFLICT DO NOTHING
                                    """, (article_id, sector))
                                    total_links += 1
            except Exception as e:
                print(f"  [curator] Entity parse error: {e}")
        conn.commit()

    print(f"  [curator] Created {total_links} entity links")
    return total_links


# ════════════════════════════════════════════════════════════
# STEP 3: IMPROVE QUERIES FOR NEXT RUN (learning loop)
# ════════════════════════════════════════════════════════════
def improve_queries(conn, topic_id=None):
    """
    LLM reviews what was found in the last run and generates
    better, more targeted queries for the next run.
    Stores in topic_monitor.llm_generated_queries and topic_curation_feedback.
    """
    try:
        from local_llm import generate
    except ImportError:
        print("  [curator] No LLM, skipping query improvement")
        return

    cur = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)

    sql = "SELECT * FROM topic_monitor WHERE enabled=true"
    params = []
    if topic_id:
        sql += " AND topic_id = %s"
        params.append(topic_id)
    cur.execute(sql, params)
    topics = cur.fetchall()

    for topic in topics:
        tid = topic['topic_id']
        # Get recent articles for this topic
        cur.execute("""
            SELECT title FROM news_articles
            WHERE strategy_type = %s AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY relevance_score DESC NULLS LAST LIMIT 10
        """, (tid,))
        recent_titles = [r['title'] for r in cur.fetchall()]

        # Get extracted tickers linked to this topic
        cur.execute("""
            SELECT DISTINCT entity_value FROM content_entity_links
            WHERE entity_type = 'ticker'
            AND content_id IN (SELECT id FROM news_articles WHERE strategy_type = %s
                               AND created_at > NOW() - INTERVAL '30 days')
            AND content_type = 'news_article'
            LIMIT 20
        """, (tid,))
        linked_tickers = [r['entity_value'] for r in cur.fetchall()]

        if not recent_titles:
            continue

        titles_str = "\n".join(f"  - {t[:80]}" for t in recent_titles[:8])
        tickers_str = ", ".join(linked_tickers[:10]) if linked_tickers else "none extracted"
        context = topic.get('personal_context', '')

        prompt = (
            f"/no_think Improve search queries for topic: {topic['display_name']}\n"
            f"Person: {context[:150]}\n"
            f"Recent articles found:\n{titles_str}\n"
            f"Tickers extracted: {tickers_str}\n\n"
            f"Based on what was found, generate 4 BETTER, more specific queries that:\n"
            f"- Fill gaps in coverage (what's missing?)\n"
            f"- Are more targeted to the person's situation\n"
            f"- Include specific tickers/topics that appeared\n\n"
            f'Reply JSON: {{"video_queries": ["q1","q2","q3","q4"], "news_queries": ["q1","q2","q3","q4"], '
            f'"quality_note": "1 sentence about content quality"}}'
        )

        raw = generate(prompt, timeout=30, fallback=False, fast=True)
        if raw:
            try:
                match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                    vq = result.get("video_queries", [])
                    nq = result.get("news_queries", [])
                    note = result.get("quality_note", "")

                    if vq or nq:
                        cur.execute("""
                            UPDATE topic_monitor
                            SET llm_generated_queries = %s, llm_query_refreshed_at = NOW()
                            WHERE topic_id = %s
                        """, (json.dumps(result), tid))

                        cur.execute("""
                            INSERT INTO topic_curation_feedback
                                (topic_id, articles_reviewed, tickers_extracted,
                                 topics_extracted, suggested_queries, quality_summary)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (tid, len(recent_titles), linked_tickers,
                              [tid], json.dumps({"video": vq, "news": nq}), note))

                        conn.commit()
                        print(f"  [curator] {tid}: improved queries ({len(vq)}v + {len(nq)}n), note: {note[:60]}")
            except Exception as e:
                print(f"  [curator] Query improvement error for {tid}: {e}")


# ════════════════════════════════════════════════════════════
# STEP 4: TRIGGER RAG RE-INDEX
# ════════════════════════════════════════════════════════════
def trigger_rag_reindex(conn):
    """Trigger RAG re-indexing for newly approved content."""
    print("  [curator] Triggering RAG re-index...")
    try:
        import subprocess
        rag_script = PROJECT_ROOT / "scripts" / "rag_indexer.py"
        if rag_script.exists():
            r = subprocess.run(
                [sys.executable, str(rag_script), "--incremental"],
                capture_output=True, text=True, timeout=120,
                cwd=str(PROJECT_ROOT)
            )
            if r.returncode == 0:
                print(f"  [curator] RAG re-index complete")
            else:
                # Try without --incremental flag
                r2 = subprocess.run(
                    [sys.executable, str(rag_script)],
                    capture_output=True, text=True, timeout=180,
                    cwd=str(PROJECT_ROOT)
                )
                print(f"  [curator] RAG index: rc={r2.returncode}")
        else:
            print(f"  [curator] rag_indexer.py not found at {rag_script}")
    except Exception as e:
        print(f"  [curator] RAG re-index error: {e}")


# ════════════════════════════════════════════════════════════
# STEP 5: WIRE INTO AGENT CONTEXT
# ════════════════════════════════════════════════════════════
def update_agent_context(conn, topic_id=None):
    """
    Push curated topic intelligence into agent_event_queue
    so agents (Alex, Maria, etc.) pick it up in their next cycle.
    """
    cur = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)

    # Find topics with new approved content that agents haven't seen
    sql = """
        SELECT t.topic_id, t.display_name, t.agent_tags,
            (SELECT COUNT(*) FROM news_articles
             WHERE strategy_type = t.topic_id AND rag_status = 'approved'
             AND created_at > NOW() - INTERVAL '24 hours') as new_approved
        FROM topic_monitor t
        WHERE t.enabled = true
    """
    params = []
    if topic_id:
        sql += " AND t.topic_id = %s"
        params.append(topic_id)
    cur.execute(sql, params)
    topics = cur.fetchall()

    events_created = 0
    for t in topics:
        if (t.get('new_approved') or 0) > 0:
            agents = t.get('agent_tags', [])
            if isinstance(agents, str):
                agents = json.loads(agents)

            # Get top article titles for the event
            cur.execute("""
                SELECT title FROM news_articles
                WHERE strategy_type = %s AND rag_status = 'approved'
                AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY relevance_score DESC NULLS LAST LIMIT 5
            """, (t['topic_id'],))
            titles = [r['title'][:80] for r in cur.fetchall()]

            try:
                cur.execute("""
                    INSERT INTO agent_event_queue
                        (event_type, symbol, agents_to_notify, priority, trigger_data, status)
                    VALUES ('TOPIC_INTELLIGENCE', %s, %s, 'normal', %s, 'pending')
                """, (
                    f"TOPIC:{t['topic_id']}",
                    agents,
                    json.dumps({
                        "topic": t['display_name'],
                        "new_approved": t['new_approved'],
                        "sample_titles": titles,
                        "message": f"{t['new_approved']} new curated articles for {t['display_name']}. Use RAG to access."
                    })
                ))
                events_created += 1
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"  [curator] Agent event error for {t['topic_id']}: {e}")

    if events_created:
        print(f"  [curator] Created {events_created} agent events for new topic intelligence")
    return events_created


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Post-ingestion topic curation")
    parser.add_argument("--topic", help="Single topic_id")
    parser.add_argument("--reindex", action="store_true", help="Force RAG re-index")
    parser.add_argument("--improve-queries", action="store_true", help="LLM improves queries for next run")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM steps")
    args = parser.parse_args()

    conn = _get_conn()
    print(f"\n{'='*60}")
    print(f"  TOPIC CURATOR — Post-Ingestion Pipeline")
    print(f"{'='*60}\n")

    stats = {}

    # Step 1: Rate pending content
    if not args.no_llm:
        print("[1/5] Rating pending content...")
        total, approved, blocked = rate_pending_content(conn, args.topic)
        stats['rated'] = total
        stats['approved'] = approved
        stats['blocked'] = blocked
    else:
        print("[1/5] Skipping rating (--no-llm)")

    # Step 2: Extract entities and link
    if not args.no_llm:
        print("\n[2/5] Extracting entities and linking...")
        links = extract_and_link_entities(conn, args.topic)
        stats['entity_links'] = links
    else:
        print("[2/5] Skipping entity extraction (--no-llm)")

    # Step 3: Improve queries for next run
    if args.improve_queries and not args.no_llm:
        print("\n[3/5] Improving queries for next run...")
        improve_queries(conn, args.topic)
    else:
        print("[3/5] Skipping query improvement")

    # Step 4: RAG re-index
    if args.reindex or (stats.get('approved', 0) > 0):
        print("\n[4/5] Triggering RAG re-index...")
        trigger_rag_reindex(conn)
    else:
        print("[4/5] Skipping RAG re-index (no new approved content)")

    # Step 5: Wire into agent context
    print("\n[5/5] Updating agent context...")
    events = update_agent_context(conn, args.topic)
    stats['agent_events'] = events

    # Summary
    print(f"\n{'='*60}")
    print(f"  CURATION COMPLETE")
    print(f"  Rated: {stats.get('rated', 0)} | Approved: {stats.get('approved', 0)} | Blocked: {stats.get('blocked', 0)}")
    print(f"  Entity links: {stats.get('entity_links', 0)}")
    print(f"  Agent events: {stats.get('agent_events', 0)}")
    print(f"{'='*60}\n")

    # Telegram summary
    if stats.get('approved', 0) > 0 or stats.get('entity_links', 0) > 0:
        _send_telegram(
            f"Topic Curator: {stats.get('approved',0)} approved for RAG, "
            f"{stats.get('blocked',0)} blocked, "
            f"{stats.get('entity_links',0)} entity links created, "
            f"{stats.get('agent_events',0)} agent events fired."
        )

    conn.close()


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
