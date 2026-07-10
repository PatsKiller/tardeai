#!/usr/bin/env python3
"""youtube_backfill_manager.py — Automated backfill that runs until complete.

Designed to handle YouTube rate limiting gracefully:
- Processes channels in batches (5 at a time)
- Tracks progress per channel in DB
- Backs off on rate limits (429/IP block)
- Resumes where it left off on next run
- Self-schedules via cron until all channels are backfilled
- Sends Telegram progress updates

State machine per channel:
  pending → in_progress → completed / rate_limited

Usage:
    python3 scripts/youtube_backfill_manager.py              # Process next batch
    python3 scripts/youtube_backfill_manager.py --status     # Show progress
    python3 scripts/youtube_backfill_manager.py --reset      # Reset all to pending
"""
import json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

BATCH_SIZE = 5          # Channels per run
VIDEOS_PER_CHANNEL = 50 # ~12 months of weekly uploads
COOLDOWN_HOURS = 4      # Wait before retrying rate-limited channels
MAX_ERRORS_PER_RUN = 3  # Stop run after this many consecutive transcript failures


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _send_tg(msg):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass


def ensure_backfill_table():
    """Create backfill tracking table if it doesn't exist."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS youtube_backfill_status (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT DEFAULT '',
            strategy_focus TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            videos_found INTEGER DEFAULT 0,
            videos_ingested INTEGER DEFAULT 0,
            videos_failed INTEGER DEFAULT 0,
            last_attempted TIMESTAMPTZ,
            last_error TEXT DEFAULT '',
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # Seed from youtube_channels for any not yet tracked
    cur.execute("""
        INSERT INTO youtube_backfill_status (channel_id, channel_name, strategy_focus)
        SELECT channel_id, channel_name, strategy_focus
        FROM youtube_channels WHERE active = TRUE
        ON CONFLICT (channel_id) DO NOTHING
    """)
    conn.commit()
    conn.close()


def get_next_batch() -> list:
    """Get next batch of channels to process.
    Priority: pending first, then rate_limited that have cooled down.
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Pending channels (never attempted)
    cur.execute("""
        SELECT channel_id, channel_name, strategy_focus
        FROM youtube_backfill_status
        WHERE status = 'pending'
        ORDER BY
            CASE strategy_focus
                WHEN 'retirement_ssdi_roth_tax' THEN 1
                WHEN 'dividend_growth_compounding' THEN 2
                WHEN 'swing_trading' THEN 3
                ELSE 4
            END
        LIMIT %s
    """, (BATCH_SIZE,))
    pending = cur.fetchall()

    # If not enough pending, add cooled-down rate_limited channels
    if len(pending) < BATCH_SIZE:
        remaining = BATCH_SIZE - len(pending)
        cooldown_cutoff = datetime.now() - timedelta(hours=COOLDOWN_HOURS)
        cur.execute("""
            SELECT channel_id, channel_name, strategy_focus
            FROM youtube_backfill_status
            WHERE status = 'rate_limited'
              AND (last_attempted IS NULL OR last_attempted < %s)
            ORDER BY last_attempted ASC NULLS FIRST
            LIMIT %s
        """, (cooldown_cutoff, remaining))
        pending.extend(cur.fetchall())

    conn.close()
    return pending


def process_channel(channel_id: str, channel_name: str) -> dict:
    """Backfill one channel: fetch up to 50 videos, ingest transcripts."""
    from youtube_transcript_ingest import list_channel_videos, ingest_video, get_channel_info

    conn = _get_conn()
    cur = conn.cursor()

    # Mark in_progress
    cur.execute("UPDATE youtube_backfill_status SET status='in_progress', last_attempted=NOW() WHERE channel_id=%s",
                (channel_id,))
    conn.commit()

    result = {"channel": channel_name, "found": 0, "ingested": 0, "failed": 0, "status": "completed"}

    try:
        # Get real channel ID if we have a handle/name
        info = get_channel_info(channel_id)
        if info.get("error"):
            # Try the channel_id as-is (might already be correct)
            pass

        videos = list_channel_videos(channel_id, max_results=VIDEOS_PER_CHANNEL)
        result["found"] = len(videos)

        if not videos:
            cur.execute("""UPDATE youtube_backfill_status SET status='completed', videos_found=0,
                          completed_at=NOW(), last_error='No videos found' WHERE channel_id=%s""", (channel_id,))
            conn.commit()
            conn.close()
            return result

        consecutive_errors = 0
        for i, v in enumerate(videos):
            try:
                r = ingest_video(v["url"], added_by="backfill", publish_date=v.get("published"))
                if r.get("status") == "ingested":
                    result["ingested"] += 1
                    consecutive_errors = 0
                    print(f"    [{i+1}/{len(videos)}] INGESTED: {v['title'][:45]}")
                elif r.get("status") == "already_exists":
                    consecutive_errors = 0  # Not an error
                else:
                    result["failed"] += 1
                    consecutive_errors += 1
                    err = str(r.get("error", ""))[:60]
                    if "IpBlocked" in err or "429" in err or "rate" in err.lower():
                        print(f"    [{i+1}/{len(videos)}] RATE LIMITED — stopping channel")
                        result["status"] = "rate_limited"
                        break
                    if consecutive_errors >= MAX_ERRORS_PER_RUN:
                        print(f"    [{i+1}/{len(videos)}] {MAX_ERRORS_PER_RUN} consecutive failures — pausing")
                        result["status"] = "rate_limited"
                        break
            except Exception as e:
                result["failed"] += 1
                consecutive_errors += 1

            # Small delay between videos
            time.sleep(0.5)

    except Exception as e:
        result["status"] = "rate_limited"
        result["error"] = str(e)[:200]

    # Update status
    cur.execute("""
        UPDATE youtube_backfill_status
        SET status=%s, videos_found=%s, videos_ingested=videos_ingested+%s,
            videos_failed=videos_failed+%s, last_attempted=NOW(),
            last_error=%s, completed_at=%s
        WHERE channel_id=%s
    """, (result["status"], result["found"], result["ingested"], result["failed"],
          result.get("error", "")[:200],
          datetime.now() if result["status"] == "completed" else None,
          channel_id))
    conn.commit()
    conn.close()

    return result


def run():
    """Process next batch of channels for backfill."""
    ensure_backfill_table()

    batch = get_next_batch()
    if not batch:
        print("[backfill] All channels completed or cooling down. Nothing to do.")
        show_status()
        return {"status": "idle", "processed": 0}

    print(f"[backfill] {datetime.now().strftime('%H:%M')} — Processing {len(batch)} channels")

    results = []
    for ch in batch:
        print(f"\n  Channel: {ch['channel_name']} ({ch['strategy_focus']})")
        result = process_channel(ch["channel_id"], ch["channel_name"])
        results.append(result)
        print(f"    → {result['status']}: {result['ingested']} ingested, {result['failed']} failed of {result['found']} found")

        if result["status"] == "rate_limited":
            print(f"    → Rate limited. Remaining channels will retry in {COOLDOWN_HOURS}h.")
            # Don't process more channels if YouTube is blocking
            break

    # Summary
    total_ingested = sum(r["ingested"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    completed = sum(1 for r in results if r["status"] == "completed")
    rate_limited = sum(1 for r in results if r["status"] == "rate_limited")

    print(f"\n[backfill] Batch done: {completed} completed, {rate_limited} rate-limited, {total_ingested} transcripts ingested")

    # Check overall progress
    status = get_status_summary()
    pct = status["completed_pct"]

    # Telegram update
    if total_ingested > 0 or rate_limited > 0:
        _send_tg(
            f"\U0001F4FC *YouTube Backfill Progress*\n"
            f"Batch: {total_ingested} ingested, {total_failed} failed\n"
            f"Overall: {status['completed']}/{status['total']} channels ({pct:.0f}%)\n"
            f"{'Rate limited — will retry in ' + str(COOLDOWN_HOURS) + 'h' if rate_limited else 'Continuing...'}"
        )

    return {"processed": len(results), "ingested": total_ingested, "progress": pct}


def get_status_summary() -> dict:
    """Get overall backfill progress."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT status, count(*) as cnt,
               sum(videos_ingested) as ingested,
               sum(videos_failed) as failed
        FROM youtube_backfill_status
        GROUP BY status
    """)
    rows = {r["status"]: r for r in cur.fetchall()}
    cur.execute("SELECT count(*) FROM youtube_backfill_status")
    total = cur.fetchone()["count"]
    conn.close()

    completed = rows.get("completed", {}).get("cnt", 0)
    return {
        "total": total,
        "completed": completed,
        "pending": rows.get("pending", {}).get("cnt", 0),
        "in_progress": rows.get("in_progress", {}).get("cnt", 0),
        "rate_limited": rows.get("rate_limited", {}).get("cnt", 0),
        "total_ingested": sum(r.get("ingested", 0) or 0 for r in rows.values()),
        "total_failed": sum(r.get("failed", 0) or 0 for r in rows.values()),
        "completed_pct": (completed / total * 100) if total > 0 else 0,
    }


def show_status():
    """Print backfill status for all channels."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT channel_name, strategy_focus, status, videos_found, videos_ingested, videos_failed, last_attempted
        FROM youtube_backfill_status
        ORDER BY
            CASE status WHEN 'pending' THEN 1 WHEN 'rate_limited' THEN 2 WHEN 'in_progress' THEN 3 ELSE 4 END,
            channel_name
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"\n{'Channel':<30} {'Strategy':<28} {'Status':<14} {'Found':>5} {'Got':>5} {'Fail':>5} {'Last Attempt'}")
    print("-" * 120)
    for r in rows:
        la = str(r.get("last_attempted") or "never")[:16]
        print(f"{r['channel_name'][:29]:<30} {r['strategy_focus'][:27]:<28} {r['status']:<14} {r['videos_found'] or 0:>5} {r['videos_ingested'] or 0:>5} {r['videos_failed'] or 0:>5} {la}")

    s = get_status_summary()
    print(f"\nTotal: {s['completed']}/{s['total']} completed ({s['completed_pct']:.0f}%) | {s['total_ingested']} ingested | {s['total_failed']} failed | {s['pending']} pending | {s['rate_limited']} rate-limited")


def reset():
    """Reset all channels to pending for a fresh backfill."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE youtube_backfill_status SET status='pending', videos_found=0, videos_ingested=0, videos_failed=0, last_attempted=NULL, completed_at=NULL")
    print(f"Reset {cur.rowcount} channels to pending")
    conn.commit()
    conn.close()


def process_video_queue(limit: int = 10) -> int:
    """Process pending entries in youtube_backfill_queue.

    These are individual videos discovered via symbol_enrichment GO signal search.
    Download their transcripts using the same ingest_video() used for channel backfill.
    """
    from youtube_transcript_ingest import ingest_video

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, video_id, channel_id, symbol_trigger, priority
        FROM youtube_backfill_queue
        WHERE status = 'pending'
        ORDER BY
            CASE priority WHEN 'high' THEN 0 ELSE 1 END,
            created_at ASC
        LIMIT %s
    """, [limit])
    pending = cur.fetchall()

    if not pending:
        conn.close()
        return 0

    processed = 0
    for queue_id, video_id, channel_id, symbol_trigger, priority in pending:
        cur.execute("""
            UPDATE youtube_backfill_queue
            SET status = 'processing', updated_at = NOW()
            WHERE id = %s
        """, [queue_id])
        conn.commit()

        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            result = ingest_video(url, added_by=f"backfill_queue:{symbol_trigger}")

            if result.get("status") in ("ingested", "already_exists"):
                status = "completed"
                processed += 1
            else:
                status = "failed"

            cur.execute("""
                UPDATE youtube_backfill_queue
                SET status = %s, completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, [status, queue_id])
            conn.commit()
        except Exception as e:
            cur.execute("""
                UPDATE youtube_backfill_queue
                SET status = 'failed', error = %s, updated_at = NOW()
                WHERE id = %s
            """, [str(e)[:200], queue_id])
            conn.commit()

        time.sleep(0.5)

    conn.close()
    print(f"[backfill-queue] Processed {processed}/{len(pending)} videos")
    return processed


if __name__ == "__main__":
    if "--status" in sys.argv:
        ensure_backfill_table()
        show_status()
    elif "--reset" in sys.argv:
        reset()
    elif "--queue" in sys.argv:
        process_video_queue(limit=20)
    else:
        # Process channel backfill AND video queue
        run()
        process_video_queue(limit=10)
