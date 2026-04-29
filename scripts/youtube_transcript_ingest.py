#!/usr/bin/env python3
"""youtube_transcript_ingest.py — Ingest YouTube transcripts for portfolio intelligence.

Fetches transcripts from tracked channels/videos, scores them using the unified
content_scoring engine, and stores in youtube_transcripts table.

Usage:
    python3 scripts/youtube_transcript_ingest.py --test
    python3 scripts/youtube_transcript_ingest.py --ingest VIDEO_URL
    python3 scripts/youtube_transcript_ingest.py --channel CHANNEL_URL
    python3 scripts/youtube_transcript_ingest.py --all-channels
"""
import json, os, re, sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    # Maybe it's just the ID itself
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    return ""


def fetch_transcript(video_id: str) -> dict:
    """Fetch transcript for a video. Returns {text, segments, duration}."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)

        segments = []
        full_text = []
        max_end = 0

        for entry in transcript:
            text = entry.text if hasattr(entry, 'text') else entry.get('text', '')
            start = entry.start if hasattr(entry, 'start') else entry.get('start', 0)
            duration = entry.duration if hasattr(entry, 'duration') else entry.get('duration', 0)
            segments.append({"text": text, "start": start, "duration": duration})
            full_text.append(text)
            max_end = max(max_end, start + duration)

        return {
            "text": " ".join(full_text),
            "segments": len(segments),
            "duration_seconds": int(max_end),
        }
    except Exception as e:
        return {"error": str(e), "text": "", "segments": 0, "duration_seconds": 0}


def get_video_metadata(video_id: str) -> dict:
    """Get basic video metadata (title, channel) via oembed (no API key needed)."""
    try:
        import urllib.request
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return {
                "title": data.get("title", f"Video {video_id}"),
                "channel_name": data.get("author_name", ""),
            }
    except Exception:
        return {"title": f"Video {video_id}", "channel_name": ""}


def _get_portfolio_symbols() -> list:
    """Get active portfolio symbols for relevance scoring."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        symbols = [r[0] for r in cur.fetchall()]
        conn.close()
        return symbols
    except Exception:
        return []


def ingest_video(video_url: str, added_by: str = "user") -> dict:
    """Ingest a single YouTube video transcript."""
    video_id = extract_video_id(video_url)
    if not video_id:
        return {"error": f"Could not extract video ID from: {video_url}"}

    # Check if already ingested
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM youtube_transcripts WHERE video_id=%s", (video_id,))
    if cur.fetchone():
        conn.close()
        return {"status": "already_exists", "video_id": video_id}

    # Fetch transcript
    print(f"  [yt] Fetching transcript for {video_id}...")
    result = fetch_transcript(video_id)
    if result.get("error"):
        conn.close()
        return {"error": result["error"], "video_id": video_id}

    # Get metadata
    meta = get_video_metadata(video_id)

    # Score and tag content
    from content_scoring import score_content, tag_content
    symbols = _get_portfolio_symbols()
    scores = score_content(
        title=meta["title"],
        text=result["text"][:5000],  # Score first 5K chars
        source="youtube",
        channel=meta["channel_name"],
        symbols=symbols,
    )
    tags = tag_content(text=result["text"][:5000], title=meta["title"])

    # Store
    url = f"https://www.youtube.com/watch?v={video_id}"
    cur.execute("""
        INSERT INTO youtube_transcripts
            (video_id, title, channel_name, url, transcript_text, duration_seconds,
             quality_score, relevance_score, validation_status, matched_keywords, added_by,
             strategy_tags, agent_tags)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (video_id, meta["title"], meta["channel_name"], url,
          result["text"][:50000],  # Limit stored text
          result["duration_seconds"],
          scores["quality_score"], scores["relevance_score"],
          scores["validation_status"], json.dumps(scores["matched_keywords"]),
          added_by, json.dumps(tags["strategy_tags"]), json.dumps(tags["agent_tags"])))
    conn.commit()
    conn.close()

    return {
        "status": "ingested",
        "video_id": video_id,
        "title": meta["title"],
        "channel": meta["channel_name"],
        "duration": result["duration_seconds"],
        "quality_score": scores["quality_score"],
        "relevance_score": scores["relevance_score"],
        "validation_status": scores["validation_status"],
        "keywords": scores["matched_keywords"],
    }


def test_pipeline():
    """Test the pipeline with a known finance video."""
    print("=== YouTube Transcript Ingestion — Test ===\n")

    # Test video ID extraction
    test_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ]
    print("Video ID extraction:")
    for url in test_urls:
        vid = extract_video_id(url)
        print(f"  {url[:40]:40} → {vid}")

    # Test scoring engine
    print("\nScoring engine:")
    from content_scoring import score_content
    test_cases = [
        ("Best Dividend Stocks for 2026", "Looking at SCHD yield and retirement income with Roth IRA strategies", "youtube", "Dividend Bull"),
        ("Cat Videos Compilation", "Cute cats playing around the house", "youtube", "CatTV"),
        ("Market Analysis: Fed Rate Decision", "The Federal Reserve interest rate decision impacts stock market valuation", "yahoo_finance", ""),
    ]
    for title, text, source, channel in test_cases:
        s = score_content(title, text, source, channel)
        print(f"  [{s['validation_status']:<14}] Q:{s['quality_score']:3} R:{s['relevance_score']:.2f} | {title[:50]}")
        if s["matched_keywords"]:
            print(f"    keywords: {', '.join(s['matched_keywords'][:5])}")

    # Test transcript fetch (use a short public video)
    print("\nTranscript fetch test:")
    # Use a well-known short video for testing
    test_vid = "jNQXAC9IVRw"  # "Me at the zoo" - first YouTube video, has captions
    result = fetch_transcript(test_vid)
    if result.get("error"):
        print(f"  Transcript fetch: FAILED ({result['error'][:80]})")
        print("  (This is OK — some videos don't have transcripts)")
    else:
        print(f"  Transcript fetch: OK — {result['segments']} segments, {result['duration_seconds']}s")
        print(f"  First 100 chars: {result['text'][:100]}...")

    # Show tracked channels
    print("\nTracked channels:")
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT channel_name, strategy_focus, added_by FROM youtube_channels WHERE active=TRUE ORDER BY channel_name")
    for name, strat, ab in cur.fetchall():
        print(f"  {name:<20} strategy: {strat:<28} added_by: {ab}")
    conn.close()

    # Count existing transcripts
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM youtube_transcripts")
    count = cur.fetchone()[0]
    conn.close()
    print(f"\nStored transcripts: {count}")
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_pipeline()
    elif "--ingest" in sys.argv:
        idx = sys.argv.index("--ingest")
        if idx + 1 < len(sys.argv):
            url = sys.argv[idx + 1]
            result = ingest_video(url)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Usage: --ingest VIDEO_URL")
    elif "--channel" in sys.argv:
        print("Channel bulk ingest not yet implemented (requires YouTube Data API key)")
        print("For now, ingest individual videos with: --ingest VIDEO_URL")
    elif "--all-channels" in sys.argv:
        print("Bulk channel ingest not yet implemented (requires YouTube Data API key)")
    else:
        print("Usage:")
        print("  --test              Run pipeline test")
        print("  --ingest URL        Ingest a single video transcript")
        print("  --channel URL       Ingest recent videos from a channel (requires API key)")
        print("  --all-channels      Ingest from all tracked channels (requires API key)")
