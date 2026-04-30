#!/usr/bin/env python3
"""transcript_slow_processor.py — Incremental transcript processing (LLM summaries).

Processes 1-2 transcripts per run using local LLM. Designed to run hourly
via cron overnight to gradually process the backlog without overwhelming
the system. Fresh (today's) transcripts get priority.

Usage:
    python3 scripts/transcript_slow_processor.py --run           # Process 2 transcripts
    python3 scripts/transcript_slow_processor.py --run --count 5  # Process 5
    python3 scripts/transcript_slow_processor.py --status         # Show pipeline status
    python3 scripts/transcript_slow_processor.py --fresh          # Process only today's transcripts

Cron (overnight hourly): 0 22-6 * * * (10 PM to 6 AM, 2 per hour = ~18/night)
"""
import json, sys, time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def process_batch(count: int = 2, fresh_only: bool = False) -> dict:
    """Process N transcripts: clean → extract → LLM summary → sub-tags → embed."""
    import psycopg2.extras
    from transcript_processor import (clean_transcript, extractive_filter,
                                       generate_structured_summary, extract_sub_tags)
    from content_scoring import score_content, tag_content, index_content

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Priority: fresh (today) first, then by quality score
    date_filter = "AND ingested_at::date = CURRENT_DATE" if fresh_only else ""
    cur.execute(f"""
        SELECT id, video_id, title, channel_name, transcript_text, quality_score,
               cleaned_text, summary, structured_json
        FROM youtube_transcripts
        WHERE transcript_text IS NOT NULL AND LENGTH(transcript_text) > 100
          AND (summary IS NULL OR structured_json IS NULL)
          {date_filter}
        ORDER BY
          CASE WHEN ingested_at::date = CURRENT_DATE THEN 0 ELSE 1 END,
          quality_score DESC
        LIMIT %s
    """, (count,))
    rows = cur.fetchall()

    processed = 0
    for r in rows:
        vid = r["video_id"]
        title = r["title"] or ""
        channel = r["channel_name"] or ""
        raw = r["transcript_text"]

        try:
            # Step 1: Clean (if not already done)
            cleaned = r.get("cleaned_text") or ""
            if not cleaned:
                cleaned = clean_transcript(raw)

            # Step 2: Extract key sentences
            extracted = extractive_filter(cleaned)

            # Step 3: Score
            scores = score_content(title, extracted, source="youtube", channel=channel)
            quality = scores["quality_score"]

            # Step 4: LLM structured summary (the expensive step)
            structured = {}
            summary_text = r.get("summary") or ""
            if not summary_text:
                print(f"  [{vid}] Generating LLM summary for: {title[:50]}...")
                structured = generate_structured_summary(title, extracted, channel, quality)
                if structured:
                    summary_text = structured.get("summary", "")
                    print(f"  [{vid}] Summary: {summary_text[:80]}...")
                else:
                    print(f"  [{vid}] LLM returned empty — skipping summary")

            # Step 5: Sub-tags
            sub_tags = extract_sub_tags(extracted)

            # Step 6: Strategy + agent tags
            tags = tag_content(extracted, title=title)

            # Step 7: Update DB
            ucur = conn.cursor()
            ucur.execute("""UPDATE youtube_transcripts SET
                cleaned_text = %s, quality_score = %s, relevance_score = %s,
                validation_status = %s,
                matched_keywords = %s::jsonb, strategy_tags = %s::jsonb,
                agent_tags = %s::jsonb, sub_tags = %s::jsonb,
                summary = %s,
                structured_json = %s::jsonb
                WHERE id = %s""",
                (cleaned[:10000], quality, scores["relevance_score"],
                 scores["validation_status"],
                 json.dumps(scores.get("matched_keywords", [])),
                 json.dumps(tags["strategy_tags"]),
                 json.dumps(tags["agent_tags"]),
                 json.dumps(sub_tags),
                 summary_text[:2000] if summary_text else None,
                 json.dumps(structured) if structured else None,
                 r["id"]))
            conn.commit()

            # Step 8: Index embedding
            index_content("youtube", r["id"], title, extracted[:2000])

            processed += 1
            print(f"  [{vid}] Done (Q:{quality}, {len(extracted)} chars)")

            # Pause between LLM calls to avoid overwhelming local model
            if processed < len(rows):
                time.sleep(2)

        except Exception as e:
            conn.rollback()
            print(f"  [{vid}] Error: {e}")

    conn.close()
    print(f"[transcript-processor] Processed {processed}/{len(rows)}")
    return {"processed": processed, "total_queued": len(rows)}


def show_status():
    """Show transcript pipeline status."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""SELECT
        count(*) as total,
        SUM(CASE WHEN cleaned_text IS NOT NULL AND cleaned_text != '' THEN 1 ELSE 0 END) as cleaned,
        SUM(CASE WHEN summary IS NOT NULL THEN 1 ELSE 0 END) as summarized,
        SUM(CASE WHEN structured_json IS NOT NULL THEN 1 ELSE 0 END) as structured,
        SUM(CASE WHEN ingested_at::date = CURRENT_DATE THEN 1 ELSE 0 END) as today
    FROM youtube_transcripts""")
    s = cur.fetchone()

    cur.execute("""SELECT count(*) as cnt FROM content_embeddings
        WHERE source_type='youtube' AND embedding IS NOT NULL""")
    emb = cur.fetchone()["cnt"]

    conn.close()

    total = s["total"]
    print(f"\n=== Transcript Pipeline Status ===")
    print(f"  Total transcripts: {total}")
    print(f"  Cleaned:           {s['cleaned']}/{total} ({s['cleaned']*100//max(1,total)}%)")
    print(f"  LLM Summarized:    {s['summarized']}/{total} ({s['summarized']*100//max(1,total)}%)")
    print(f"  Structured JSON:   {s['structured']}/{total} ({s['structured']*100//max(1,total)}%)")
    print(f"  Embedded (768d):   {emb}/{total} ({emb*100//max(1,total)}%)")
    print(f"  Today's ingested:  {s['today']}")
    backlog = total - (s["summarized"] or 0)
    if backlog > 0:
        hours = backlog / 2  # 2 per hour
        print(f"  Backlog:           {backlog} (est. {hours:.0f} hours at 2/hr)")
    print()


if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    elif "--run" in sys.argv or "--fresh" in sys.argv:
        count = 2
        for i, a in enumerate(sys.argv):
            if a == "--count" and i + 1 < len(sys.argv):
                count = int(sys.argv[i + 1])
        fresh = "--fresh" in sys.argv
        process_batch(count=count, fresh_only=fresh)
    else:
        print("Usage: --run [--count N] | --fresh | --status")
