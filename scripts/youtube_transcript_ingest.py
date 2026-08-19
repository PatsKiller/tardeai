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
import json, os, re, sys, urllib.request, urllib.parse
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


def _parse_transcript_entries(transcript) -> dict:
    """Parse transcript entries (from any source) into {text, segments, duration}."""
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
    return {"text": " ".join(full_text), "segments": len(segments), "duration_seconds": int(max_end),
            "timed_segments": segments}


COOKIE_PATH = PROJECT_ROOT / "config" / "youtube_cookies.txt"

def _load_cookie_session():
    """Load YouTube cookies from Netscape-format cookie file into a requests.Session.

    Cookie file: config/youtube_cookies.txt (Netscape/Mozilla format)
    Export from browser using: "Get cookies.txt LOCALLY" Chrome extension
    or: yt-dlp --cookies-from-browser chrome --cookies config/youtube_cookies.txt

    Returns requests.Session with cookies loaded, or None if no cookie file.
    """
    if not COOKIE_PATH.exists():
        return None
    try:
        import requests, http.cookiejar
        jar = http.cookiejar.MozillaCookieJar(str(COOKIE_PATH))
        jar.load(ignore_discard=True, ignore_expires=True)
        session = requests.Session()
        session.cookies = jar
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        return session
    except Exception as e:
        print(f"  [cookies] Failed to load {COOKIE_PATH}: {e}")
        return None


def _get_cookie_opener():
    """Build urllib opener with cookies for timedtext fallback."""
    if not COOKIE_PATH.exists():
        return None
    try:
        import http.cookiejar
        jar = http.cookiejar.MozillaCookieJar(str(COOKIE_PATH))
        jar.load(ignore_discard=True, ignore_expires=True)
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    except Exception:
        return None


def _fetch_timedtext(video_id: str) -> dict:
    """Fallback: fetch transcript via YouTube's timedtext XML endpoint.
    Uses cookies from config/youtube_cookies.txt if available to bypass IP blocks."""
    import time, xml.etree.ElementTree as ET
    try:
        time.sleep(1)  # Rate limit protection
        page_url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
        req = urllib.request.Request(page_url, headers=headers)

        # Use cookie opener if available (bypasses IP blocks)
        opener = _get_cookie_opener()
        if opener:
            with opener.open(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        else:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

        m = re.search(r'"baseUrl":"(https://www\.youtube\.com/api/timedtext[^"]+)"', html)
        if not m:
            return {"error": "No captions found", "text": "", "segments": 0, "duration_seconds": 0}
        caption_url = m.group(1).replace("\\u0026", "&")
        time.sleep(0.5)
        cap_req = urllib.request.Request(caption_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        if opener:
            with opener.open(cap_req, timeout=15) as resp:
                xml_data = resp.read()
        else:
            with urllib.request.urlopen(cap_req, timeout=15) as resp:
                xml_data = resp.read()

        root = ET.fromstring(xml_data)
        entries = []
        for elem in root.findall(".//text"):
            text = (elem.text or "").strip()
            start = float(elem.get("start", 0))
            dur = float(elem.get("dur", 0))
            if text:
                entries.append({"text": text, "start": start, "duration": dur})
        if entries:
            return _parse_transcript_entries(entries)
        return {"error": "Captions empty", "text": "", "segments": 0, "duration_seconds": 0}
    except urllib.error.HTTPError as e:
        if e.code == 429:
            cookie_hint = " (cookies loaded)" if COOKIE_PATH.exists() else " — add cookies: config/youtube_cookies.txt"
            return {"error": f"Rate limited (429){cookie_hint}", "text": "", "segments": 0,
                    "duration_seconds": 0, "rate_limited": True}
        return {"error": f"HTTP {e.code}", "text": "", "segments": 0, "duration_seconds": 0}
    except Exception as e:
        return {"error": f"timedtext: {e}", "text": "", "segments": 0, "duration_seconds": 0}


_YT_COOLDOWN = Path(__file__).resolve().parent.parent / "data" / "runtime" / "youtube_429_cooldown.json"


def _yt_cooldown_active() -> bool:
    try:
        import time
        data = json.loads(_YT_COOLDOWN.read_text())
        return float(data.get("until", 0)) > time.time()
    except Exception:
        return False


def _yt_trip_cooldown(seconds: int = 1800) -> None:
    import time
    try:
        _YT_COOLDOWN.parent.mkdir(parents=True, exist_ok=True)
        _YT_COOLDOWN.write_text(json.dumps({"until": time.time() + seconds, "reason": "429"}))
    except Exception:
        pass


def _is_429(exc_or_result) -> bool:
    s = str(exc_or_result or "").lower()
    return "429" in s or "too many requests" in s or "rate limited" in s


def fetch_transcript(video_id: str) -> dict:
    """Fetch transcript with bounded fallback. A 429 stops the chain and the loop."""
    if _yt_cooldown_active():
        return {"error": "Rate limited (429) cooldown — skipping", "text": "", "segments": 0,
                "duration_seconds": 0, "rate_limited": True}

    def _fail_429(src: str) -> dict:
        _yt_trip_cooldown()
        return {"error": f"Rate limited (429) via {src}", "text": "", "segments": 0,
                "duration_seconds": 0, "rate_limited": True}

    # Method 1: youtube-transcript-api with cookie session
    session = _load_cookie_session()
    if session:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            ytt_api = YouTubeTranscriptApi(http_client=session)
            transcript = None
            for langs in [['en'], ['en-US'], ['en-GB']]:
                try:
                    transcript = ytt_api.fetch(video_id, languages=langs)
                    break
                except Exception:
                    continue
            if transcript is None:
                transcript = ytt_api.fetch(video_id)
            return _parse_transcript_entries(transcript)
        except Exception as e:
            if _is_429(e):
                return _fail_429("youtube-transcript-api+cookies")
            pass  # Fall through to method 2

    # Method 2: youtube-transcript-api without cookies
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt_api = YouTubeTranscriptApi()
        transcript = None
        for langs in [['en'], ['en-US'], ['en-GB']]:
            try:
                transcript = ytt_api.fetch(video_id, languages=langs)
                break
            except Exception as e:
                if _is_429(e):
                    return _fail_429("youtube-transcript-api")
                continue
        if transcript is None:
            transcript = ytt_api.fetch(video_id)
        return _parse_transcript_entries(transcript)
    except Exception as e:
        if _is_429(e):
            return _fail_429("youtube-transcript-api")

    # Method 3: Direct timedtext scraping with cookies
    result = _fetch_timedtext(video_id)
    if result.get("rate_limited") or _is_429(result.get("error")):
        return _fail_429("timedtext")
    if result.get("text"):
        return result

    # Method 4: yt-dlp subtitle download (most robust, handles anti-bot + JS challenges)
    try:
        import subprocess, tempfile
        deno_path = Path.home() / ".deno" / "bin"
        env = {**os.environ, "PATH": f"{deno_path}:{os.environ.get('PATH', '')}"}
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [sys.executable, "-m", "yt_dlp",
                   "--write-auto-sub", "--sub-lang", "en", "--skip-download",
                   "--no-check-formats", "--remote-components", "ejs:github",
                   "-o", f"{tmpdir}/sub", f"https://www.youtube.com/watch?v={video_id}"]
            if COOKIE_PATH.exists():
                cmd.extend(["--cookies", str(COOKIE_PATH)])
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
            # Find the subtitle file
            from pathlib import Path as _P
            vtt_files = list(_P(tmpdir).glob("*.vtt"))
            if vtt_files:
                vtt = vtt_files[0].read_text()
                lines = []
                for line in vtt.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("WEBVTT") and "-->" not in line and not line[0:1].isdigit():
                        clean = re.sub(r"<[^>]+>", "", line)
                        if clean:
                            lines.append(clean)
                if lines:
                    text = " ".join(lines)
                    return {"text": text, "segments": len(lines), "duration_seconds": 0, "timed_segments": []}
    except Exception:
        pass

    return {"error": "All transcript methods failed", "text": "", "segments": 0, "duration_seconds": 0}


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


def _parse_publish_date(raw: str | None) -> date | None:
    """Normalize YouTube ISO8601 or YYYY-MM-DD into a date."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def ingest_video(video_url: str, added_by: str = "user", *, publish_date: str | None = None) -> dict:
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
        return {"error": result["error"], "video_id": video_id,
                "rate_limited": bool(result.get("rate_limited"))}

    # Get metadata
    meta = get_video_metadata(video_id)
    pub = _parse_publish_date(publish_date)

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
    # Store timed segments for timestamped highlights
    timed_json = json.dumps(result.get("timed_segments", [])[:500])  # Cap at 500 segments

    try:
        cur.execute("""
            INSERT INTO youtube_transcripts
                (video_id, title, channel_name, url, publish_date, transcript_text, duration_seconds,
                 quality_score, relevance_score, validation_status, matched_keywords, added_by,
                 strategy_tags, agent_tags, timed_segments)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (video_id, meta["title"], meta["channel_name"], url, pub,
              result["text"][:50000],
              result["duration_seconds"],
              scores["quality_score"], scores["relevance_score"],
              scores["validation_status"], json.dumps(scores["matched_keywords"]),
              added_by, json.dumps(tags["strategy_tags"]), json.dumps(tags["agent_tags"]),
              timed_json))
        row = cur.fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        if "youtube_transcripts_video_id_key" in str(e) or "UniqueViolation" in type(e).__name__:
            return {"status": "already_exists", "video_id": video_id}
        raise
    new_id = row['id'] if isinstance(row, dict) else row[0]
    conn.commit()
    conn.close()

    # Tag immediately at ingest time — never leave a transcript untagged
    try:
        from transcript_tagger import tag_new_transcript
        tag_new_transcript(new_id)
    except Exception as e:
        print(f"  [warning] Transcript tagging failed for {new_id}: {e}")

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


def _get_youtube_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("YOUTUBE_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key


def extract_channel_id(url_or_id: str) -> str:
    """Extract channel ID from various URL formats or return as-is if already an ID."""
    import re
    # Direct channel ID (starts with UC, 24 chars)
    if re.match(r'^UC[a-zA-Z0-9_-]{22}$', url_or_id):
        return url_or_id
    # https://www.youtube.com/channel/UCxxxxx
    m = re.search(r'youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})', url_or_id)
    if m:
        return m.group(1)
    # https://www.youtube.com/@handle — need API lookup
    m = re.search(r'youtube\.com/@([a-zA-Z0-9_.-]+)', url_or_id)
    if m:
        handle = m.group(1)
        api_key = _get_youtube_api_key()
        if api_key:
            try:
                lookup_url = f"https://www.googleapis.com/youtube/v3/channels?part=id,snippet&forHandle={handle}&key={api_key}"
                with urllib.request.urlopen(lookup_url, timeout=10) as resp:
                    data = json.loads(resp.read())
                    if data.get("items"):
                        return data["items"][0]["id"]
            except Exception:
                pass
    return url_or_id  # Return as-is, might be a channel ID


def get_channel_info(channel_id: str) -> dict:
    """Get channel name and uploads playlist ID."""
    api_key = _get_youtube_api_key()
    if not api_key:
        return {"error": "No YOUTUBE_API_KEY"}
    try:
        url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails&id={channel_id}&key={api_key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("items"):
                ch = data["items"][0]
                return {
                    "channel_id": channel_id,
                    "channel_name": ch["snippet"]["title"],
                    "description": ch["snippet"].get("description", "")[:200],
                    "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
                }
    except Exception as e:
        return {"error": str(e)}
    return {"error": "Channel not found"}


def list_channel_videos(channel_id: str, max_results: int = 50) -> list:
    """List videos from a channel's uploads playlist (reliable, ordered by date)."""
    api_key = _get_youtube_api_key()
    if not api_key:
        return []

    info = get_channel_info(channel_id)
    if info.get("error"):
        print(f"[yt] {info['error']}")
        return []

    playlist_id = info["uploads_playlist"]
    videos = []
    next_page = None

    while len(videos) < max_results:
        page_size = min(50, max_results - len(videos))
        url = (f"https://www.googleapis.com/youtube/v3/playlistItems"
               f"?part=snippet&playlistId={playlist_id}&maxResults={page_size}&key={api_key}")
        if next_page:
            url += f"&pageToken={next_page}"

        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
                for item in data.get("items", []):
                    s = item["snippet"]
                    vid = s["resourceId"]["videoId"]
                    videos.append({
                        "video_id": vid,
                        "title": s.get("title", ""),
                        "channel": s.get("channelTitle", info.get("channel_name", "")),
                        "published": s.get("publishedAt", ""),
                        "url": f"https://www.youtube.com/watch?v={vid}",
                    })
                next_page = data.get("nextPageToken")
                if not next_page:
                    break
        except Exception as e:
            print(f"[yt] API error: {e}")
            break

    return videos


def search_channel_videos(channel_name: str, max_results: int = 5) -> list:
    """Search YouTube for recent videos from a channel (fallback if no channel ID)."""
    api_key = _get_youtube_api_key()
    if not api_key:
        return []

    import urllib.parse
    query = urllib.parse.quote(f"{channel_name} finance investing")
    url = (f"https://www.googleapis.com/youtube/v3/search"
           f"?part=snippet&q={query}&type=video&maxResults={max_results}"
           f"&order=date&key={api_key}")

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
            videos = []
            for item in data.get("items", []):
                vid = item.get("id", {}).get("videoId", "")
                snippet = item.get("snippet", {})
                if vid:
                    videos.append({
                        "video_id": vid,
                        "title": snippet.get("title", ""),
                        "channel": snippet.get("channelTitle", ""),
                        "published": snippet.get("publishedAt", ""),
                        "url": f"https://www.youtube.com/watch?v={vid}",
                    })
            return videos
    except Exception as e:
        print(f"[yt] Search error: {e}")
        return []


def import_channel(channel_url: str, max_videos: int = 20, strategy_focus: str = "") -> dict:
    """Import a YouTube channel: add to tracked channels + ingest recent video transcripts.

    Args:
        channel_url: Channel URL (youtube.com/channel/UCxxx or youtube.com/@handle) or channel ID
        max_videos: How many recent videos to ingest (default 20)
        strategy_focus: Optional strategy tag (e.g. 'retirement_planning')
    """
    channel_id = extract_channel_id(channel_url)
    info = get_channel_info(channel_id)
    if info.get("error"):
        return {"error": info["error"], "input": channel_url}

    channel_name = info["channel_name"]
    print(f"[yt] Importing channel: {channel_name} ({channel_id})")
    print(f"[yt] Fetching up to {max_videos} videos...")

    # Add to tracked channels
    import psycopg2
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO youtube_channels (channel_id, channel_name, channel_url, strategy_focus, added_by)
        VALUES (%s, %s, %s, %s, 'user')
        ON CONFLICT (channel_id) DO UPDATE SET channel_name=EXCLUDED.channel_name, channel_url=EXCLUDED.channel_url
    """, (channel_id, channel_name, f"https://www.youtube.com/channel/{channel_id}",
          strategy_focus or "general"))
    conn.commit()
    conn.close()
    print(f"[yt] Channel added to tracking: {channel_name}")

    # Get videos via uploads playlist
    videos = list_channel_videos(channel_id, max_results=max_videos)
    print(f"[yt] Found {len(videos)} videos")

    # Ingest transcripts
    ingested = 0
    skipped = 0
    errors = 0
    for i, v in enumerate(videos):
        result = ingest_video(v["url"], added_by="user", publish_date=v.get("published"))
        if result.get("status") == "ingested":
            ingested += 1
            print(f"  [{i+1}/{len(videos)}] INGESTED: {v['title'][:50]} (Q:{result.get('quality_score',0)} R:{result.get('relevance_score',0):.2f})")
        elif result.get("status") == "already_exists":
            skipped += 1
        else:
            errors += 1
            if i < 5:  # Only print first few errors
                print(f"  [{i+1}/{len(videos)}] SKIP: {v['title'][:40]} — {str(result.get('error',''))[:40]}")
            if result.get("rate_limited") or _is_429(result.get("error")):
                print("[yt] 429 — stopping channel ingest for this run (cooldown armed)")
                break

    # Update last_checked
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE youtube_channels SET last_checked=NOW() WHERE channel_id=%s", (channel_id,))
    conn.commit()
    conn.close()

    return {
        "channel": channel_name,
        "channel_id": channel_id,
        "videos_found": len(videos),
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
    }


def fetch_channel_videos(channel_id_or_name: str, max_videos: int = 3) -> dict:
    """Discover and ingest recent videos from a channel."""
    # Look up channel in DB
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT channel_name, channel_url FROM youtube_channels WHERE channel_id=%s OR channel_name ILIKE %s",
                (channel_id_or_name, f"%{channel_id_or_name}%"))
    ch = cur.fetchone()
    conn.close()

    channel_name = ch["channel_name"] if ch else channel_id_or_name
    print(f"[yt] Searching for recent videos from: {channel_name}")

    videos = search_channel_videos(channel_name, max_results=max_videos)
    if not videos:
        return {"channel": channel_name, "found": 0, "ingested": 0}

    print(f"[yt] Found {len(videos)} videos")
    ingested = 0
    results = []
    for v in videos:
        print(f"  → {v['title'][:60]}")
        result = ingest_video(v["url"], added_by="ai")
        results.append(result)
        if result.get("status") == "ingested":
            ingested += 1

    # Update last_checked
    try:
        conn = _get_conn()
        cur = conn.cursor()
        if ch:
            cur.execute("UPDATE youtube_channels SET last_checked=NOW() WHERE channel_name=%s", (channel_name,))
            conn.commit()
        conn.close()
    except Exception:
        pass

    return {"channel": channel_name, "found": len(videos), "ingested": ingested, "videos": results}


def ingest_all_channels(max_per_channel: int = 3) -> dict:
    """Ingest videos from all tracked channels.

    Args:
        max_per_channel: Videos to fetch per channel (3 = daily, 50 = backfill 12 months)
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT channel_id, channel_name FROM youtube_channels WHERE active=TRUE ORDER BY last_checked ASC NULLS FIRST")
    channels = cur.fetchall()
    conn.close()

    print(f"[yt] Processing {len(channels)} tracked channels (max {max_per_channel} videos each)")
    total_found = 0
    total_ingested = 0
    channel_results = []

    for ch in channels:
        result = fetch_channel_videos(ch["channel_id"], max_videos=max_per_channel)
        total_found += result.get("found", 0)
        total_ingested += result.get("ingested", 0)
        channel_results.append(result)

    print(f"[yt] All channels done: {total_found} found, {total_ingested} ingested")
    return {"channels": len(channels), "total_found": total_found, "total_ingested": total_ingested, "results": channel_results}


def backfill_all_channels(max_per_channel: int = 50) -> dict:
    """Backfill: fetch up to 50 videos per channel (~12 months of weekly uploads).
    Use this once when adding new channels, not for daily runs.
    """
    print(f"[yt-backfill] Starting backfill — up to {max_per_channel} videos per channel")
    return ingest_all_channels(max_per_channel=max_per_channel)


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
    elif "--import-channel" in sys.argv or "--import" in sys.argv:
        flag = "--import-channel" if "--import-channel" in sys.argv else "--import"
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            channel_url = sys.argv[idx + 1]
            max_vids = 20
            strategy = ""
            if "--max" in sys.argv:
                mi = sys.argv.index("--max")
                if mi + 1 < len(sys.argv):
                    max_vids = int(sys.argv[mi + 1])
            if "--strategy" in sys.argv:
                si = sys.argv.index("--strategy")
                if si + 1 < len(sys.argv):
                    strategy = sys.argv[si + 1]
            result = import_channel(channel_url, max_videos=max_vids, strategy_focus=strategy)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Usage: --import-channel URL [--max 20] [--strategy retirement_planning]")
    elif "--channel" in sys.argv:
        idx = sys.argv.index("--channel")
        if idx + 1 < len(sys.argv):
            channel_id = sys.argv[idx + 1]
            results = fetch_channel_videos(channel_id)
            print(json.dumps(results, indent=2, default=str))
        else:
            print("Usage: --channel CHANNEL_ID")
    elif "--backfill" in sys.argv:
        max_v = 50
        if "--max" in sys.argv:
            mi = sys.argv.index("--max")
            if mi + 1 < len(sys.argv):
                max_v = int(sys.argv[mi + 1])
        results = backfill_all_channels(max_per_channel=max_v)
        print(json.dumps(results, indent=2, default=str))
    elif "--all-channels" in sys.argv:
        try:
            results = ingest_all_channels()
            print(json.dumps(results, indent=2, default=str))
        except Exception as e:
            print(f"[yt] FATAL: {e}")
            try:
                sys.path.insert(0, os.path.dirname(__file__))
                from telegram_alert import send_telegram
                send_telegram(
                    f"PIPELINE FAILURE: youtube_transcript_ingest\n"
                    f"Error: {str(e)[:200]}\n\n"
                    f"Reply to retry:\n"
                    f"  add video <url> — ingest specific video\n"
                    f"  status — system health check"
                )
            except Exception:
                pass
            sys.exit(1)
    else:
        print("Usage:")
        print("  --import-channel URL [--max 20] [--strategy retirement_planning]")
        print("      Import a channel: add to tracking + ingest transcripts")
        print("  --backfill [--max 50]    Backfill: fetch up to 50 videos per channel (~12 months)")
        print("      Run once after adding new channels. NOT for daily use.")
        print("  --all-channels           Daily: fetch latest 3 videos per channel")
        print("  --ingest URL             Ingest a single video transcript")
        print("  --channel ID             List recent videos from a channel")
        print("  --test                   Run pipeline test")
