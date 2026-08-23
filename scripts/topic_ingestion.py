#!/usr/bin/env python3
"""
topic_ingestion.py — Topic-based content ingestion with LLM curation.

Architecture:
  1. LLM reads personal_situation + topic context + DB gaps → generates
     targeted search queries (not static). Saved search URLs are reused.
  2. Search cascade: YouTube API → Google News RSS → Brave → DuckDuckGo
  3. ALL results downloaded (not capped at 3-6). Transcripts fetched.
  4. LLM rates each item: RAG-worthy / low-quality / blocked
  5. Blocked items stored in blocked_content table (never re-downloaded)
  6. Good items saved to news_articles / youtube_transcripts with rag_status

Reads topics from topic_monitor table (DB-driven).
Logs all search attempts to iris_library_gap_fills table.

Usage:
    python topic_ingestion.py                    # all enabled topics
    python topic_ingestion.py --topic ssdi       # single topic
    python topic_ingestion.py --dry-run          # preview, no DB writes
    python topic_ingestion.py --gaps-only        # only topics with 0 recent articles
    python topic_ingestion.py --curate           # LLM generates queries first
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── ENV helpers ──────────────────────────────────────────────────────────
_env_cache = {}

def _env(key: str, default: str = "") -> str:
    if not _env_cache:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    _env_cache[k.strip()] = v.strip().strip('"')
    return _env_cache.get(key, os.getenv(key, default))


# ── DB connection ────────────────────────────────────────────────────────
def _get_conn():
    import psycopg2
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai",
        password=_env("DB_PASSWORD")
    )


# ── Desk-side projection (no Telegram) ───────────────────────────────────
# Per-run ingestion counts are non-actionable noise on Telegram; the articles
# themselves already land in news_articles / youtube_transcripts (the canonical
# desk store). Write a small projection the CIO / Advisory Desk can read for
# ingestion health instead of texting a count.
def _write_desk_projection(total_stats: dict) -> None:
    try:
        out = PROJECT_ROOT / "data" / "runtime" / "topic_ingestion_latest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "articles": total_stats.get("articles", 0),
            "transcripts": total_stats.get("transcripts", 0),
            "topics_processed": total_stats.get("topics_processed", 0),
            "topics_skipped": total_stats.get("topics_skipped", 0),
        }
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"  [topic_ingestion] desk projection write failed: {e}")


# ── Global min-interval re-entry guard ───────────────────────────────────
# Belt-and-braces against sub-minute re-invocation (loop defense + any parent
# that fires this script faster than the external APIs can be safely hit). Uses
# a timestamp file rather than a held flock so legitimate sequential drains
# (RI queue, iris --gaps, reground) — which run one topic per subprocess at
# >30s spacing — are never skipped.
_INGESTION_GATE_PATH = "/tmp/topic_ingestion.interval"
_INGESTION_MIN_INTERVAL_S = 30.0


def _interval_gate_ok() -> bool:
    """Return True if enough time has elapsed since the last ingestion start."""
    try:
        p = Path(_INGESTION_GATE_PATH)
        now = time.time()
        if p.exists():
            try:
                last = float(p.read_text().strip() or "0")
            except ValueError:
                last = 0.0
            if now - last < _INGESTION_MIN_INTERVAL_S:
                return False
        p.write_text(str(now), encoding="utf-8")
        return True
    except Exception:
        # Guard must never block ingestion on an I/O edge case.
        return True


# ── Content scoring (reuse existing) ────────────────────────────────────
try:
    from content_scoring import score_content, tag_content
except ImportError:
    def score_content(title, text, source="topic_monitor", **kw):
        return {"quality_score": 50, "relevance_score": 0.5,
                "validation_status": "unscored", "matched_keywords": []}
    def tag_content(text, title="", **kw):
        return {"strategy_tags": [], "agent_tags": []}


# ════════════════════════════════════════════════════════════════════════
# BLOCKED CONTENT CHECK
# ════════════════════════════════════════════════════════════════════════
def _is_blocked(conn, content_type: str, content_id: str) -> bool:
    """Check if content is in blocked_content table."""
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM blocked_content WHERE content_type=%s AND content_id=%s LIMIT 1",
        (content_type, content_id)
    )
    blocked = cur.fetchone() is not None
    # End the read txn — callers do slow fetch/LLM work next, and an open transaction
    # is killed at idle_in_transaction_session_timeout=120s (top offender, 2026-07-04 audit).
    try:
        conn.commit()
    except Exception:
        pass
    return blocked


def _block_content(conn, content_type: str, content_id: str, title: str,
                   reason: str, topic_id: str, blocked_by: str = "llm"):
    """Add content to blocked_content table so it's never re-downloaded."""
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO blocked_content (content_type, content_id, title, reason, blocked_by, topic_id)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (content_type, content_id) DO NOTHING
        """, (content_type, content_id, title[:500], reason, blocked_by, topic_id))
        conn.commit()
    except Exception:
        conn.rollback()


# ════════════════════════════════════════════════════════════════════════
# LLM QUERY GENERATION (reads personal_situation + DB gaps)
# ════════════════════════════════════════════════════════════════════════
def _load_personal_context(conn) -> str:
    """Load personal situation from DB for LLM context."""
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM personal_situation ORDER BY key")
    rows = cur.fetchall()
    if not rows:
        return ""
    return ", ".join(f"{r[0]}={r[1]}" for r in rows)


def _load_existing_titles(conn, topic_id: str, days: int = 30) -> list[str]:
    """Load titles of content already in DB for this topic."""
    cur = conn.cursor()
    titles = []
    cur.execute(
        "SELECT title FROM news_articles WHERE strategy_type=%s AND created_at > NOW() - INTERVAL '%s days'",
        (topic_id, days)
    )
    titles.extend(r[0] for r in cur.fetchall())
    cur.execute(
        "SELECT title FROM youtube_transcripts WHERE ingested_at > NOW() - INTERVAL '%s days' AND (strategy_tags::text LIKE %s OR title ILIKE %s)",
        (days, f'%{topic_id}%', f'%{topic_id.replace("_", " ")}%')
    )
    titles.extend(r[0] for r in cur.fetchall())
    return titles


def llm_generate_queries(conn, topic: dict) -> dict:
    """
    LLM generates targeted search queries by reading:
    - Personal situation (SSDI, NY, age 58, MFS, etc.)
    - Topic context from topic_monitor.personal_context
    - What's already in the DB (avoid duplicating existing content)
    - What's missing (gaps)

    Returns: {"video_queries": [...], "news_queries": [...]}
    Tight prompt: ~200 input tokens, ~100 output tokens.
    """
    personal = topic.get("personal_context", "") or _load_personal_context(conn)
    existing = _load_existing_titles(conn, topic["topic_id"])
    existing_str = "; ".join(existing[:10]) if existing else "none yet"

    prompt = (
        f"/no_think Generate targeted search queries for this topic.\n"
        f"Topic: {topic['display_name']}\n"
        f"Person: {personal}\n"
        f"Already have: {existing_str}\n\n"
        f"Generate 4 YouTube video queries and 4 news queries that are:\n"
        f"- Specific to this person's situation (state, income, filing status)\n"
        f"- Different from what's already downloaded\n"
        f"- Actionable (how-to, strategy, planning, rules, limits)\n\n"
        f'Reply ONLY with JSON: {{"video_queries": ["q1","q2","q3","q4"], "news_queries": ["q1","q2","q3","q4"]}}'
    )

    try:
        from lib.governed_cloud_generation import generate_cloud
        raw, _lane = generate_cloud(
            prompt, process_id="topic_ingestion",
            task_summary=f"topic queries {topic['topic_id']}", timeout=30,
            response_json=True, max_tokens=512,
        )
    except Exception:
        raw = ""
    if not raw:
        return {"video_queries": topic.get("video_queries", []),
                "news_queries": topic.get("search_queries", [])}

    try:
        match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            vq = result.get("video_queries", [])
            nq = result.get("news_queries", [])
            if vq and nq:
                print(f"  [llm-curate] Generated {len(vq)} video + {len(nq)} news queries")
                # Save LLM-generated queries back to DB
                cur = conn.cursor()
                cur.execute("""
                    UPDATE topic_monitor
                    SET llm_generated_queries = %s, llm_query_refreshed_at = NOW()
                    WHERE topic_id = %s
                """, (json.dumps(result), topic["topic_id"]))
                conn.commit()
                return result
    except (json.JSONDecodeError, Exception) as e:
        print(f"  [llm-curate] Parse error: {e}")

    return {"video_queries": topic.get("video_queries", []),
            "news_queries": topic.get("search_queries", [])}


# ════════════════════════════════════════════════════════════════════════
# SAVED SEARCH URL PARSER (reuse Google search URLs)
# ════════════════════════════════════════════════════════════════════════
def _extract_video_ids_from_google_url(search_url: str) -> list[dict]:
    """
    Fetch a saved Google Video search URL and extract video results.
    Google Video tab URLs use udm=7 parameter.
    Returns list of {"video_id": ..., "title": ..., "url": ...}
    """
    try:
        req = urllib.request.Request(search_url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Extract YouTube video IDs from Google results page
        # Pattern: youtube.com/watch?v=VIDEO_ID
        video_pattern = r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})'
        video_ids = list(dict.fromkeys(re.findall(video_pattern, html)))  # unique, preserve order

        results = []
        # Also try to extract titles near video links
        for vid in video_ids:
            # Try to find title near the video ID in HTML
            title_match = re.search(
                rf'([^<]{{10,120}})</[^>]*>[^<]*youtube\.com/watch\?v={vid}|'
                rf'youtube\.com/watch\?v={vid}[^>]*>([^<]{{10,120}})',
                html
            )
            title = ""
            if title_match:
                title = (title_match.group(1) or title_match.group(2) or "").strip()
                title = re.sub(r'&amp;', '&', title)
                title = re.sub(r'&#39;', "'", title)
            results.append({
                "video_id": vid,
                "title": title or f"YouTube video {vid}",
                "url": f"https://www.youtube.com/watch?v={vid}",
                "source": "saved_search_url",
            })

        print(f"  [saved-url] Extracted {len(results)} video IDs from Google search")
        return results
    except Exception as e:
        print(f"  [saved-url] Error fetching Google URL: {e}")
        return []


def _extract_query_from_google_url(url: str) -> str:
    """Extract the search query from a Google search URL."""
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    q = params.get("q", [""])[0]
    return q.replace("+", " ")


def search_saved_urls(conn, topic: dict) -> list[dict]:
    """
    Process saved Google search URLs.
    Strategy: Extract query from URL → route through YouTube Data API
    (Google HTML is JS-rendered, can't scrape directly from cloud IPs).
    Saved URLs are effectively curated queries that we know produce results.
    """
    saved_urls = topic.get("saved_search_urls", [])
    if not saved_urls:
        return []

    print(f"\n  [0/4] Saved Search URLs ({len(saved_urls)} URLs)...")
    # Extract queries from URLs and search via YouTube API
    queries = []
    for url in saved_urls:
        q = _extract_query_from_google_url(url)
        if q:
            queries.append(q)
            print(f"    URL query: '{q}'")

    if not queries:
        return []

    # Use YouTube API to search these curated queries (10 results each)
    results = search_youtube(queries, max_per_query=10, conn=conn)
    print(f"  [saved-url] Found {len(results)} videos from {len(queries)} saved URL queries")
    return results


# ════════════════════════════════════════════════════════════════════════
# LLM QUALITY RATING  (RAG / low_quality / blocked)
# ════════════════════════════════════════════════════════════════════════
def _llm_rate_quality(title: str, content_preview: str,
                      topic_display: str, personal_context: str) -> dict:
    """
    LLM rates content quality for RAG indexing.
    Tight prompt: ~150 input tokens, ~50 output tokens.

    Returns: {"rag_status": "approved"|"low_quality"|"blocked",
              "rag_reason": "...", "summary": "..."}
    """
    prompt = (
        f"/no_think Rate this content for RAG indexing.\n"
        f"Topic: {topic_display}\n"
        f"Person: {personal_context[:150]}\n"
        f"Title: {title}\n"
        f"Content: {content_preview[:400]}\n\n"
        f"Reply ONLY with JSON:\n"
        f'{{"rag_status": "approved" or "low_quality" or "blocked", '
        f'"rag_reason": "1 sentence why", '
        f'"summary": "1-2 sentence summary relevant to the person"}}'
    )

    try:
        from lib.governed_cloud_generation import generate_cloud
        raw, _lane = generate_cloud(
            prompt, process_id="topic_ingestion",
            task_summary=f"RAG quality {topic_display[:80]}", timeout=25,
            response_json=True, max_tokens=384,
        )
    except Exception:
        raw = ""
    if not raw:
        return {"rag_status": "pending", "rag_reason": "", "summary": content_preview[:300]}

    try:
        match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    return {"rag_status": "pending", "rag_reason": "", "summary": content_preview[:300]}


# ════════════════════════════════════════════════════════════════════════
# SOURCE 1: YouTube Data API v3  (video search + transcript)
# ════════════════════════════════════════════════════════════════════════
# ── YouTube Data API v3 daily quota guard ─────────────────────────────────
# search.list costs 100 quota units/call; the default project quota is 10,000/day
# (~100 searches). The topic pipeline previously burned the whole budget in a
# single run and then 429'd for the rest of the day — the topic_youtube_api lane
# read "dead" on the health board from 2026-06-21 to 2026-07-07. Cap our own
# usage well under the ceiling so the lane stays alive at reduced volume, and
# circuit-break for the rest of the day on the first 429. Tunable via
# YOUTUBE_SEARCH_DAILY_CAP (default 80 → ~8,000 units, leaving headroom for the
# channel-based transcript pipeline that shares the same project quota).
_YT_BUDGET_FILE = PROJECT_ROOT / "data" / "portfolios" / "state" / "youtube_search_budget.json"
_YT_DAILY_CAP = int(os.getenv("YOUTUBE_SEARCH_DAILY_CAP", "80"))
_yt_query_cache: dict[str, list[dict]] = {}   # per-process de-dup of identical queries


def _yt_budget_load() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        d = json.loads(_YT_BUDGET_FILE.read_text())
    except Exception:
        d = {}
    if d.get("date") != today:
        d = {"date": today, "count": 0, "quota_blocked": False}
    return d


def _yt_budget_save(d: dict) -> None:
    try:
        _YT_BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _YT_BUDGET_FILE.write_text(json.dumps(d, indent=2))
    except Exception:
        pass


def _yt_budget_allow() -> tuple[bool, str]:
    d = _yt_budget_load()
    if d.get("quota_blocked"):
        return False, "quota 429'd earlier today — circuit-broken until tomorrow"
    if d.get("count", 0) >= _YT_DAILY_CAP:
        return False, f"daily cap {_YT_DAILY_CAP} reached ({d.get('count', 0)} search.list calls)"
    return True, ""


def _yt_budget_record(blocked: bool = False) -> None:
    d = _yt_budget_load()
    d["count"] = d.get("count", 0) + 1
    if blocked:
        d["quota_blocked"] = True
    _yt_budget_save(d)


def _youtube_search(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube via Data API v3. Returns video metadata.
    Guarded by a persistent per-day quota budget (search.list = 100 units/call)."""
    api_key = _env("YOUTUBE_API_KEY")
    if not api_key:
        print("  [youtube] No YOUTUBE_API_KEY — skipping")
        return []
    if query in _yt_query_cache:
        return _yt_query_cache[query]
    ok, why = _yt_budget_allow()
    if not ok:
        print(f"  [youtube] quota guard: {why} — skipping '{query[:50]}'")
        return []
    params = urllib.parse.urlencode({
        "part": "snippet", "q": query, "type": "video",
        "maxResults": max_results, "order": "date",
        "relevanceLanguage": "en", "key": api_key,
    })
    url = f"https://www.googleapis.com/youtube/v3/search?{params}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        _yt_budget_record()   # a search.list call was consumed (100 units)
        results = []
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            snip = item.get("snippet", {})
            if vid:
                results.append({
                    "video_id": vid,
                    "title": snip.get("title", ""),
                    "channel": snip.get("channelTitle", ""),
                    "published": snip.get("publishedAt", ""),
                    "description": snip.get("description", "")[:500],
                    "url": f"https://www.youtube.com/watch?v={vid}",
                })
        _yt_query_cache[query] = results
        print(f"  [youtube] Found {len(results)} videos for: {query}")
        return results
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _yt_budget_record(blocked=True)
            print("  [youtube] HTTP 429 quota exceeded — circuit-breaking YouTube "
                  "search for the rest of today")
        else:
            print(f"  [youtube] Search error: HTTP {e.code}")
        return []
    except Exception as e:
        print(f"  [youtube] Search error: {e}")
        return []


COOKIE_PATH = PROJECT_ROOT / "config" / "youtube_cookies.txt"


def _load_cookie_session():
    """Load YouTube cookies from Netscape-format cookie file for IP ban bypass."""
    if not COOKIE_PATH.exists():
        return None
    try:
        import requests, http.cookiejar
        jar = http.cookiejar.MozillaCookieJar(str(COOKIE_PATH))
        jar.load(ignore_discard=True, ignore_expires=True)
        session = requests.Session()
        session.cookies = jar
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
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


def _parse_transcript_entries(transcript) -> str:
    """Parse transcript entries into plain text."""
    parts = []
    for entry in transcript:
        text = entry.text if hasattr(entry, 'text') else entry.get('text', '')
        parts.append(text)
    return " ".join(parts)


def _fetch_timedtext(video_id: str) -> str | None:
    """Fallback: scrape transcript via YouTube's timedtext XML endpoint with cookies."""
    import xml.etree.ElementTree as ET
    try:
        time.sleep(1)
        page_url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
        req = urllib.request.Request(page_url, headers=headers)
        opener = _get_cookie_opener()
        if opener:
            with opener.open(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        else:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

        m = re.search(r'"baseUrl":"(https://www\.youtube\.com/api/timedtext[^"]+)"', html)
        if not m:
            return None
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
        parts = []
        for elem in root.findall(".//text"):
            text = (elem.text or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts)[:50000] if parts else None
    except Exception as e:
        print(f"  [timedtext] Error for {video_id}: {e}")
        return None


def _fetch_yt_dlp(video_id: str) -> str | None:
    """Last resort: yt-dlp subtitle download (handles anti-bot + JS challenges)."""
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
            vtt_files = list(Path(tmpdir).glob("*.vtt"))
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
                    return " ".join(lines)[:50000]
    except Exception as e:
        print(f"  [yt-dlp] Error for {video_id}: {e}")
    return None


def _fetch_transcript(video_id: str) -> str | None:
    """4-method transcript fetch with cookie auth (matches youtube_transcript_ingest.py):
    1. youtube-transcript-api WITH cookies (bypasses IP bans)
    2. youtube-transcript-api without cookies
    3. Direct timedtext XML scraping with cookies
    4. yt-dlp subtitle download with cookies
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    # Method 1: youtube-transcript-api with cookie session
    session = _load_cookie_session()
    if session:
        try:
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
            text = _parse_transcript_entries(transcript)
            if text.strip():
                return text[:50000]
        except Exception:
            pass  # Fall through

    # Method 2: youtube-transcript-api without cookies
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = None
        for langs in [['en'], ['en-US'], ['en-GB']]:
            try:
                transcript = ytt_api.fetch(video_id, languages=langs)
                break
            except Exception:
                continue
        if transcript is None:
            transcript = ytt_api.fetch(video_id)
        text = _parse_transcript_entries(transcript)
        if text.strip():
            return text[:50000]
    except Exception:
        pass

    # Method 3: timedtext XML scraping with cookies
    text = _fetch_timedtext(video_id)
    if text:
        print(f"  [timedtext] Got transcript for {video_id}")
        return text

    # Method 4: yt-dlp (most robust)
    text = _fetch_yt_dlp(video_id)
    if text:
        print(f"  [yt-dlp] Got transcript for {video_id}")
        return text

    print(f"  [youtube] All 4 transcript methods failed for {video_id}")
    return None


def search_youtube(queries: list[str], max_per_query: int = 10,
                   conn=None) -> list[dict]:
    """Search YouTube and fetch transcripts. Returns enriched results.
    Downloads ALL results (up to max_per_query per query), checks blocked list."""
    results = []
    seen_ids = set()
    for q in queries:
        videos = _youtube_search(q, max_results=max_per_query)
        for v in videos:
            if v["video_id"] in seen_ids:
                continue
            if conn and _is_blocked(conn, "youtube", v["video_id"]):
                print(f"    SKIP (blocked): {v['video_id']}")
                continue
            seen_ids.add(v["video_id"])
            transcript = _fetch_transcript(v["video_id"])
            v["transcript"] = transcript
            v["source"] = "youtube_api"
            results.append(v)
        if results:
            time.sleep(1)  # rate limit
    return results


# ════════════════════════════════════════════════════════════════════════
# SOURCE 2: Google News RSS  (free, no key)
# ════════════════════════════════════════════════════════════════════════
def search_google_news(queries: list[str], max_per_query: int = 5) -> list[dict]:
    """Search Google News RSS. Free, no API key needed."""
    import xml.etree.ElementTree as ET
    results = []
    seen_urls = set()
    for q in queries:
        encoded = urllib.parse.quote_plus(q)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; TradeAI/1.0)"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_text = resp.read().decode("utf-8", errors="replace")
            root = ET.fromstring(xml_text)
            items = root.findall(".//item")
            for item in items[:max_per_query]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                desc = (item.findtext("description") or "").strip()
                # Strip HTML from description
                desc = re.sub(r"<[^>]+>", "", desc)[:500]
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                results.append({
                    "title": title[:500],
                    "url": link,
                    "description": desc,
                    "published": pub,
                    "source": "google_news_rss",
                })
            print(f"  [google-news] Found {len(items)} items for: {q}")
        except Exception as e:
            print(f"  [google-news] Error for '{q}': {e}")
        time.sleep(0.5)
    return results


# ════════════════════════════════════════════════════════════════════════
# SOURCE 3: Brave Search News API
# ════════════════════════════════════════════════════════════════════════
def search_brave_news(queries: list[str], max_per_query: int = 5) -> list[dict]:
    """Search Brave News API. Requires BRAVE_SEARCH_API_KEY.

    RETIRED 2026-07-07: the Brave account returns HTTP 402 Payment Required
    (plan/credits exhausted) and the free DuckDuckGo topic lane already covers
    the same job. Disabled by default so it stops reading "dead" on the health
    board and stops hammering a paywalled endpoint. Set TOPIC_BRAVE_ENABLED=1
    to re-enable once billing is restored."""
    if os.getenv("TOPIC_BRAVE_ENABLED", "0").lower() not in ("1", "true", "yes"):
        print("  [brave] retired (402 paywalled) — set TOPIC_BRAVE_ENABLED=1 to re-enable")
        return []
    try:
        from brave_search import search_news as brave_news
    except ImportError:
        print("  [brave] brave_search module not found")
        return []

    results = []
    seen_urls = set()
    for q in queries:
        hits = brave_news(q, count=max_per_query, freshness="pm",
                          project_root=str(PROJECT_ROOT))
        for h in hits:
            url = h.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append({
                "title": h.get("title", "")[:500],
                "url": url,
                "description": h.get("description", "")[:500],
                "published": h.get("age", ""),
                "source": "brave_news",
            })
        print(f"  [brave] Found {len(hits)} items for: {q}")
        time.sleep(0.3)
    return results


# ════════════════════════════════════════════════════════════════════════
# SOURCE 3b: Yahoo Finance search  (free, keyless — backfills retired Brave)
# ════════════════════════════════════════════════════════════════════════
_YAHOO_SEARCH_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")


def search_yahoo_news(queries: list[str], max_per_query: int = 5) -> list[dict]:
    """Search Yahoo Finance news via /v1/finance/search. Free, no API key.

    Added 2026-07-07 to backfill the retired Brave lane. Finance/ticker-oriented,
    so it's strongest for symbol/company topics. Rotates query1/query2 hosts to
    ride out Yahoo's soft per-host rate limits (mirrors yahoo_news.py)."""
    results = []
    seen_urls = set()
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    for i, q in enumerate(queries):
        params = urllib.parse.urlencode({"q": q, "newsCount": max_per_query,
                                         "quotesCount": 0, "enableFuzzyQuery": "false"})
        hits = 0
        for host in _YAHOO_SEARCH_HOSTS[i % 2:] + _YAHOO_SEARCH_HOSTS[:i % 2]:
            try:
                req = urllib.request.Request(f"{host}/v1/finance/search?{params}",
                                             headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                for n in data.get("news", []):
                    url = n.get("link", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    hits += 1
                    # providerPublishTime is epoch seconds — convert to ISO or the
                    # timestamptz insert in _save_article rejects it and drops the row.
                    pub = ""
                    ts = n.get("providerPublishTime")
                    if isinstance(ts, (int, float)) and ts > 0:
                        try:
                            pub = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        except Exception:
                            pub = ""
                    results.append({
                        "title": n.get("title", "")[:500],
                        "url": url,
                        "description": (n.get("publisher", "") or "")[:500],
                        "published": pub,
                        "source": "yahoo_search",
                    })
                break  # host succeeded — don't try the fallback host
            except Exception as e:
                print(f"  [yahoo-search] {host} error: {e}")
                continue
        print(f"  [yahoo-search] Found {hits} items for: {q}")
        time.sleep(0.3)
    return results


# ════════════════════════════════════════════════════════════════════════
# SOURCE 4: DuckDuckGo HTML scrape  (no key, last resort)
# ════════════════════════════════════════════════════════════════════════
def search_duckduckgo(queries: list[str], max_per_query: int = 5) -> list[dict]:
    """Scrape DuckDuckGo HTML results. No API key. Last resort."""
    results = []
    seen_urls = set()
    for q in queries:
        # 2026-06-20: DDG's html endpoint now requires a POST form + a desktop UA — the old GET ?q=
        # with a Linux UA silently returned 0 results (markup/bot-gate change). POST restores result__a.
        url = "https://html.duckduckgo.com/html/"
        data = urllib.parse.urlencode({"q": q}).encode()
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
                "Content-Type": "application/x-www-form-urlencoded",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            # Parse result links from DuckDuckGo HTML
            # Pattern: <a rel="nofollow" class="result__a" href="...">title</a>
            pattern = r'class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
            matches = re.findall(pattern, html)
            # Also get snippets
            snippet_pattern = r'class="result__snippet"[^>]*>([^<]*(?:<[^>]*>[^<]*)*)</a>'
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|span)', html, re.DOTALL)
            for i, (link, title) in enumerate(matches[:max_per_query]):
                # DDG wraps URLs
                if "uddg=" in link:
                    link = urllib.parse.unquote(link.split("uddg=")[1].split("&")[0])
                # skip sponsored/ad results (duckduckgo.com/y.js?ad_domain=…)
                if "duckduckgo.com/y.js" in link or "ad_domain=" in link:
                    continue
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                desc = re.sub(r"<[^>]+>", "", snippets[i])[:500] if i < len(snippets) else ""
                results.append({
                    "title": title.strip()[:500],
                    "url": link,
                    "description": desc,
                    "published": "",
                    "source": "duckduckgo",
                })
            print(f"  [duckduckgo] Found {len(matches)} results for: {q}")
        except Exception as e:
            print(f"  [duckduckgo] Error: {e}")
        time.sleep(1)
    return results


# ════════════════════════════════════════════════════════════════════════
# LLM NORMALIZATION  (tight prompt, minimal tokens)
# ════════════════════════════════════════════════════════════════════════
def _llm_normalize(title: str, description: str, topic_display: str,
                   transcript: str = "") -> dict | None:
    """
    LLM normalizes raw search result into structured data.
    Tight focused prompt — ~100 input tokens, ~80 output tokens.
    Returns dict with normalized fields or None if irrelevant.
    """
    # Build tight prompt — no wasted tokens
    content_preview = transcript[:800] if transcript else description[:300]
    prompt = (
        f"Topic: {topic_display}\n"
        f"Title: {title}\n"
        f"Content: {content_preview}\n\n"
        "Rate this content for the topic above. Reply ONLY with JSON:\n"
        '{"relevant": true/false, "quality": "high/medium/low", '
        '"summary": "1-2 sentence summary focused on the topic"}\n'
        "If not relevant to the topic, set relevant=false."
    )

    try:
        from lib.governed_cloud_generation import generate_cloud
        raw, _lane = generate_cloud(
            prompt, process_id="topic_ingestion",
            task_summary=f"content normalization {topic_display[:80]}", timeout=30,
            response_json=True, max_tokens=384,
        )
    except Exception:
        raw = ""
    if not raw:
        return {"summary": description[:500], "relevant": True, "quality": "medium"}

    # Extract JSON from response
    try:
        # Find JSON in response
        json_match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result
    except (json.JSONDecodeError, Exception):
        pass

    return {"summary": description[:500], "relevant": True, "quality": "medium"}


# ════════════════════════════════════════════════════════════════════════
# DB WRITE  (follows existing news_articles / youtube_transcripts patterns)
# ════════════════════════════════════════════════════════════════════════
def _save_article(conn, topic: dict, item: dict, normalized: dict) -> bool:
    """Save a normalized news article to news_articles table."""
    cur = conn.cursor()
    try:
        # Dedup by source_url
        cur.execute(
            "SELECT 1 FROM news_articles WHERE source_url = %s LIMIT 1",
            (item["url"][:500],)
        )
        if cur.fetchone():
            return False

        scores = score_content(item["title"], normalized.get("summary", ""),
                               source=item["source"])
        tags = tag_content(normalized.get("summary", ""), title=item["title"])

        # Override strategy_tags and agent_tags from topic config
        strategy_tags = list(set(
            tags.get("strategy_tags", []) +
            json.loads(json.dumps(topic.get("strategy_tags", [])))
        ))
        agent_tags = list(set(
            tags.get("agent_tags", []) +
            json.loads(json.dumps(topic.get("agent_tags", [])))
        ))

        cur.execute("SAVEPOINT article_save")
        cur.execute("""
            INSERT INTO news_articles
                (symbol, strategy_type, title, summary, source, source_url,
                 published_at, relevance_score, strategy_tags, agent_tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            topic["topic_id"],           # symbol field = topic_id for topic-based
            topic["topic_id"],           # strategy_type = topic_id
            item["title"][:500],
            normalized.get("summary", item.get("description", ""))[:1000],
            f"topic_{item['source']}",   # source = topic_google_news_rss, etc.
            item["url"][:500],
            item.get("published") or None,
            scores.get("relevance_score", 0.5),
            json.dumps(strategy_tags),
            json.dumps(agent_tags),
        ))
        conn.commit()
        return True
    except Exception as e:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT article_save")
        except Exception:
            conn.rollback()
        print(f"  [db] Article save error: {e}")
        return False


def _save_transcript(conn, topic: dict, video: dict, normalized: dict) -> bool:
    """Save a YouTube transcript to youtube_transcripts table."""
    if not video.get("transcript"):
        return False
    cur = conn.cursor()
    try:
        # Dedup by video_id
        cur.execute(
            "SELECT 1 FROM youtube_transcripts WHERE video_id = %s LIMIT 1",
            (video["video_id"],)
        )
        if cur.fetchone():
            return False

        scores = score_content(video["title"], video["transcript"][:2000],
                               source="youtube_api", channel=video.get("channel", ""))
        tags = tag_content(video["transcript"][:2000], title=video["title"])

        strategy_tags = list(set(
            tags.get("strategy_tags", []) +
            json.loads(json.dumps(topic.get("strategy_tags", [])))
        ))
        agent_tags = list(set(
            tags.get("agent_tags", []) +
            json.loads(json.dumps(topic.get("agent_tags", [])))
        ))

        cur.execute("SAVEPOINT transcript_save")
        cur.execute("""
            INSERT INTO youtube_transcripts
                (video_id, title, channel_name, url, transcript_text,
                 duration_seconds, quality_score, relevance_score,
                 validation_status, matched_keywords, added_by,
                 strategy_tags, agent_tags, summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            video["video_id"],
            video["title"][:500],
            video.get("channel", "")[:200],
            video["url"][:500],
            video["transcript"][:50000],
            0,  # duration unknown from search
            scores.get("quality_score", 50),
            scores.get("relevance_score", 0.5),
            normalized.get("quality", "medium") if normalized.get("relevant") else "low_confidence",
            json.dumps(scores.get("matched_keywords", [])),
            "topic_ingestion",
            json.dumps(strategy_tags),
            json.dumps(agent_tags),
            normalized.get("summary", "")[:1000],
        ))
        conn.commit()
        return True
    except Exception as e:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT transcript_save")
        except Exception:
            conn.rollback()
        print(f"  [db] Transcript save error: {e}")
        return False


def _log_gap_fill(conn, topic_id: str, source: str, query: str,
                  results_found: int, articles_saved: int,
                  transcripts_saved: int, llm_used: bool,
                  elapsed_ms: int, error: str = None):
    """Log search attempt to iris_library_gap_fills."""
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO iris_library_gap_fills
                (topic_id, source, query_used, results_found, articles_saved,
                 transcripts_saved, llm_normalized, search_time_ms, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (topic_id, source, query[:500], results_found, articles_saved,
              transcripts_saved, llm_used, elapsed_ms, error))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [db] Gap fill log error: {e}")


# ════════════════════════════════════════════════════════════════════════
# MAIN: TOPIC INGESTION ENGINE
# ════════════════════════════════════════════════════════════════════════
def _check_existing_count(conn, topic_id: str, days: int) -> int:
    """Count recent articles for a topic."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE strategy_type = %s AND created_at > NOW() - INTERVAL '%s days'
    """, (topic_id, days))
    news_count = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM youtube_transcripts
        WHERE added_by = 'topic_ingestion'
        AND ingested_at > NOW() - INTERVAL '%s days'
        AND (strategy_tags::text LIKE %s OR title ILIKE %s)
    """, (days, f'%{topic_id}%', f'%{topic_id.replace("_", " ")}%'))
    yt_count = cur.fetchone()[0]
    return news_count + yt_count


def process_topic(conn, topic: dict, dry_run: bool = False,
                  use_llm: bool = True, curate: bool = False) -> dict:
    """
    Process a single topic through the search cascade.

    Cascade order:
      0. Saved search URLs (reuse known-good Google searches)
      1. YouTube Data API (video transcripts — ALL results, not capped)
      2. Google News RSS
      3. Brave Search News
      4. DuckDuckGo HTML

    With --curate: LLM generates queries from personal situation + DB gaps.
    Quality rating: each item rated RAG-worthy / low_quality / blocked.
    Blocked items saved to blocked_content table (never re-downloaded).
    """
    topic_id = topic["topic_id"]
    display = topic["display_name"]
    personal_ctx = topic.get("personal_context", "")
    min_articles = topic.get("min_articles", 3)

    # LLM query generation if curate mode
    if curate and use_llm:
        print(f"\n  [LLM CURATE] Generating targeted queries for {display}...")
        generated = llm_generate_queries(conn, topic)
        search_queries = generated.get("news_queries", topic.get("search_queries", []))
        video_queries = generated.get("video_queries", topic.get("video_queries", []))
    elif topic.get("llm_generated_queries") and topic.get("_use_llm_queries"):
        # Use pre-computed improved queries from topic_curator
        llm_q = topic["llm_generated_queries"]
        if isinstance(llm_q, str):
            llm_q = json.loads(llm_q)
        search_queries = llm_q.get("news_queries", topic.get("search_queries", []))
        video_queries = llm_q.get("video_queries", topic.get("video_queries", []))
        print(f"\n  [IMPROVED QUERIES] Using curator-generated queries for {display}")
    else:
        search_queries = topic.get("search_queries", [])
        video_queries = topic.get("video_queries", search_queries)

    print(f"\n{'='*60}")
    print(f"TOPIC: {display} ({topic_id})")
    print(f"  News queries: {search_queries}")
    print(f"  Video queries: {video_queries}")
    print(f"  Saved URLs: {len(topic.get('saved_search_urls', []))}")
    print(f"  Min articles: {min_articles}")
    print(f"{'='*60}")

    total_articles = 0
    total_transcripts = 0
    total_found = 0
    total_blocked = 0
    sources_used = []

    # ── SOURCE 0: Saved Google search URLs ──
    saved_videos = search_saved_urls(conn, topic)
    if saved_videos:
        sources_used.append("saved_search_url")
        total_found += len(saved_videos)
        for v in saved_videos:
            rating = _llm_rate_quality(
                v["title"], v.get("transcript", v.get("description", ""))[:600],
                display, personal_ctx
            ) if use_llm and v.get("transcript") else {
                "rag_status": "pending", "rag_reason": "", "summary": ""
            }

            if rating.get("rag_status") == "blocked":
                print(f"    BLOCK: {v['title'][:60]} — {rating.get('rag_reason','')}")
                if not dry_run:
                    _block_content(conn, "youtube", v["video_id"], v["title"],
                                   rating.get("rag_reason", "LLM: irrelevant"), topic_id)
                total_blocked += 1
                continue

            if not dry_run:
                if v.get("transcript"):
                    if _save_transcript(conn, topic, v, rating):
                        total_transcripts += 1
                        # Update rag_status on the saved transcript
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE youtube_transcripts SET rag_status=%s, rag_reason=%s WHERE video_id=%s",
                            (rating.get("rag_status", "pending"),
                             rating.get("rag_reason", ""), v["video_id"])
                        )
                        conn.commit()
                        print(f"    SAVED [{rating.get('rag_status','?')}]: {v['title'][:60]}")
                if _save_article(conn, topic, v, rating):
                    total_articles += 1

    # ── SOURCE 1: YouTube API (transcripts first — ALL results) ──
    print("\n  [1/4] YouTube Data API + Transcripts...")
    t0 = time.time()
    videos = search_youtube(video_queries, max_per_query=10, conn=conn)
    elapsed = int((time.time() - t0) * 1000)
    total_found += len(videos)

    src_transcripts = 0
    src_articles = 0
    for v in videos:
        if use_llm and v.get("transcript"):
            rating = _llm_rate_quality(v["title"], v["transcript"][:600],
                                       display, personal_ctx)
            if rating.get("rag_status") == "blocked":
                print(f"    BLOCK: {v['title'][:60]} — {rating.get('rag_reason','')}")
                if not dry_run:
                    _block_content(conn, "youtube", v["video_id"], v["title"],
                                   rating.get("rag_reason", "LLM: irrelevant"), topic_id)
                total_blocked += 1
                continue
        elif use_llm:
            rating = _llm_rate_quality(v["title"], v.get("description", ""),
                                       display, personal_ctx)
            if rating.get("rag_status") == "blocked":
                print(f"    BLOCK: {v['title'][:60]}")
                if not dry_run:
                    _block_content(conn, "youtube", v["video_id"], v["title"],
                                   rating.get("rag_reason", ""), topic_id)
                total_blocked += 1
                continue
        else:
            rating = {"rag_status": "pending", "rag_reason": "",
                      "summary": v.get("description", "")[:500]}

        if not dry_run:
            if v.get("transcript"):
                if _save_transcript(conn, topic, v, rating):
                    src_transcripts += 1
                    total_transcripts += 1
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE youtube_transcripts SET rag_status=%s, rag_reason=%s WHERE video_id=%s",
                        (rating.get("rag_status", "pending"),
                         rating.get("rag_reason", ""), v["video_id"])
                    )
                    conn.commit()
                    print(f"    SAVED [{rating.get('rag_status','?')}]: {v['title'][:60]}")
            if _save_article(conn, topic, v, rating):
                src_articles += 1
                total_articles += 1

    sources_used.append("youtube_api")
    _log_gap_fill(conn, topic_id, "youtube_api",
                  "; ".join(video_queries[:2]), len(videos),
                  src_articles, src_transcripts, use_llm, elapsed)

    # ── SOURCE 2: Google News RSS ──
    print("\n  [2/4] Google News RSS...")
    t0 = time.time()
    news = search_google_news(search_queries, max_per_query=10)
    elapsed = int((time.time() - t0) * 1000)
    total_found += len(news)
    src_articles = 0

    for item in news:
        url_hash = item["url"][:500]
        if conn and _is_blocked(conn, "article", url_hash):
            continue
        if use_llm:
            rating = _llm_rate_quality(item["title"], item["description"],
                                       display, personal_ctx)
            if rating.get("rag_status") == "blocked":
                print(f"    BLOCK: {item['title'][:60]}")
                if not dry_run:
                    _block_content(conn, "article", url_hash, item["title"],
                                   rating.get("rag_reason", ""), topic_id)
                total_blocked += 1
                continue
        else:
            rating = {"rag_status": "pending", "rag_reason": "",
                      "summary": item["description"][:500]}

        if not dry_run:
            if _save_article(conn, topic, item, rating):
                src_articles += 1
                total_articles += 1
                print(f"    SAVED [{rating.get('rag_status','?')}]: {item['title'][:60]}")

    sources_used.append("google_news_rss")
    _log_gap_fill(conn, topic_id, "google_news_rss",
                  "; ".join(search_queries[:2]), len(news),
                  src_articles, 0, use_llm, elapsed)

    # ── SOURCE 3: Yahoo Finance search (free — replaced retired Brave lane) ──
    print("\n  [3/5] Yahoo Finance search...")
    t0 = time.time()
    yahoo = search_yahoo_news(search_queries, max_per_query=10)
    elapsed = int((time.time() - t0) * 1000)
    total_found += len(yahoo)
    src_articles = 0

    for item in yahoo:
        url_hash = item["url"][:500]
        if conn and _is_blocked(conn, "article", url_hash):
            continue
        if use_llm:
            rating = _llm_rate_quality(item["title"], item["description"],
                                       display, personal_ctx)
            if rating.get("rag_status") == "blocked":
                if not dry_run:
                    _block_content(conn, "article", url_hash, item["title"],
                                   rating.get("rag_reason", ""), topic_id)
                total_blocked += 1
                continue
        else:
            rating = {"rag_status": "pending", "rag_reason": "",
                      "summary": item["description"][:500]}

        if not dry_run:
            if _save_article(conn, topic, item, rating):
                src_articles += 1
                total_articles += 1
                print(f"    SAVED [{rating.get('rag_status','?')}]: {item['title'][:60]}")

    sources_used.append("yahoo_search")
    _log_gap_fill(conn, topic_id, "yahoo_search",
                  "; ".join(search_queries[:2]), len(yahoo),
                  src_articles, 0, use_llm, elapsed)

    # ── SOURCE 4: Brave Search News (retired — no-op unless TOPIC_BRAVE_ENABLED) ──
    print("\n  [4/5] Brave Search News API...")
    t0 = time.time()
    brave = search_brave_news(search_queries, max_per_query=10)
    elapsed = int((time.time() - t0) * 1000)
    total_found += len(brave)
    src_articles = 0

    for item in brave:
        url_hash = item["url"][:500]
        if conn and _is_blocked(conn, "article", url_hash):
            continue
        if use_llm:
            rating = _llm_rate_quality(item["title"], item["description"],
                                       display, personal_ctx)
            if rating.get("rag_status") == "blocked":
                if not dry_run:
                    _block_content(conn, "article", url_hash, item["title"],
                                   rating.get("rag_reason", ""), topic_id)
                total_blocked += 1
                continue
        else:
            rating = {"rag_status": "pending", "rag_reason": "",
                      "summary": item["description"][:500]}

        if not dry_run:
            if _save_article(conn, topic, item, rating):
                src_articles += 1
                total_articles += 1
                print(f"    SAVED [{rating.get('rag_status','?')}]: {item['title'][:60]}")

    sources_used.append("brave_news")
    _log_gap_fill(conn, topic_id, "brave_news",
                  "; ".join(search_queries[:2]), len(brave),
                  src_articles, 0, use_llm, elapsed)

    # ── SOURCE 5: DuckDuckGo (last resort) ──
    print("\n  [5/5] DuckDuckGo HTML...")
    t0 = time.time()
    ddg = search_duckduckgo(search_queries[:2], max_per_query=10)
    elapsed = int((time.time() - t0) * 1000)
    total_found += len(ddg)
    src_articles = 0

    for item in ddg:
        url_hash = item["url"][:500]
        if conn and _is_blocked(conn, "article", url_hash):
            continue
        if use_llm:
            rating = _llm_rate_quality(item["title"], item["description"],
                                       display, personal_ctx)
            if rating.get("rag_status") == "blocked":
                if not dry_run:
                    _block_content(conn, "article", url_hash, item["title"],
                                   rating.get("rag_reason", ""), topic_id)
                total_blocked += 1
                continue
        else:
            rating = {"rag_status": "pending", "rag_reason": "",
                      "summary": item["description"][:500]}

        if not dry_run:
            if _save_article(conn, topic, item, rating):
                src_articles += 1
                total_articles += 1
                print(f"    SAVED [{rating.get('rag_status','?')}]: {item['title'][:60]}")

    sources_used.append("duckduckgo")
    _log_gap_fill(conn, topic_id, "duckduckgo",
                  "; ".join(search_queries[:2]), len(ddg),
                  src_articles, 0, use_llm, elapsed)

    return {"articles": total_articles, "transcripts": total_transcripts,
            "found": total_found, "blocked": total_blocked,
            "sources_used": sources_used}


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Topic-based content ingestion")
    parser.add_argument("--topic", help="Single topic_id to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--gaps-only", action="store_true",
                        help="Only process topics with 0 recent articles")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM normalization")
    parser.add_argument("--curate", action="store_true",
                        help="LLM generates targeted queries from personal situation")
    parser.add_argument("--use-llm-queries", action="store_true",
                        help="Use pre-computed LLM queries from topic_curator instead of static queries")
    parser.add_argument("--symbol", help="Single symbol to search for (gap-fill mode)")
    parser.add_argument("--limit", type=int, default=10, help="Max articles per query")
    parser.add_argument("--max-topics", type=int, default=0,
                        help="Cap topics processed this run (0=all). Lets a backfill batch finish "
                             "cleanly within a timeout; staleest topics (NULLS FIRST) go first.")
    parser.add_argument("--owner", default="",
                        help="Restrict to a single owner (e.g. 'shared'). Default: tradeai+shared.")
    parser.add_argument("--no-auto-curate", action="store_true",
                        help="Do NOT auto-spawn topic_curator.py after ingestion. Used by the "
                             "curator's own re-ingest step to break the ingest<->curate loop.")
    args = parser.parse_args()

    # Global min-interval guard: skip (clean exit) if a prior ingestion started
    # too recently. Protects external news/YouTube APIs from sub-minute hammering.
    # --dry-run never hits the external APIs, so it is exempt.
    if not args.dry_run and not _interval_gate_ok():
        print(f"  [topic_ingestion] skipped — within {_INGESTION_MIN_INTERVAL_S:.0f}s "
              f"of the previous run (re-entry guard)")
        return

    conn = _get_conn()
    cur = conn.cursor()

    # Load topics from DB
    if args.topic:
        cur.execute(
            "SELECT * FROM topic_monitor WHERE topic_id = %s AND enabled = true",
            (args.topic,)
        )
    else:
        # Oldest-first (2026-06-04): per-article LLM curation means one run only covers ~7 of 17
        # topics before the 30-min timeout. Ordering by priority alone starved low-priority topics
        # (same 7 ran every time). last_searched ASC NULLS FIRST processes the MOST-STALE topics
        # first, so the daily cron cycles all 17 fairly over ~3 days; priority is the tiebreaker.
        # owner routing (2026-06-04): TradeAI's engine researches tradeai + shared topics.
        # hermes-owned topics are handed off to Hermes via hermes_topic_monitor_bridge.py
        # (which enqueues owner IN ('hermes','shared') into hermes_research_intelligence).
        # shared = researched by BOTH engines.
        if args.owner:
            cur.execute(
                "SELECT * FROM topic_monitor WHERE enabled = true AND owner = %s "
                "ORDER BY last_searched ASC NULLS FIRST, priority, topic_id", (args.owner,)
            )
        else:
            cur.execute(
                "SELECT * FROM topic_monitor WHERE enabled = true AND owner IN ('tradeai','shared') "
                "ORDER BY last_searched ASC NULLS FIRST, priority, topic_id"
            )

    columns = [desc[0] for desc in cur.description]
    topics = [dict(zip(columns, row)) for row in cur.fetchall()]
    # Backfill cap (2026-06-20): with 140+ topics and per-article LLM curation, a full run can't
    # finish in 30m. --max-topics lets a batch process the N stalest topics and exit clean; the
    # NULLS-FIRST ordering means never-searched (newly-routed) topics are picked up first.
    if args.max_topics and len(topics) > args.max_topics:
        topics = topics[:args.max_topics]

    if not topics:
        print("No enabled topics found in topic_monitor table.")
        return

    # Deserialize JSONB fields
    for t in topics:
        for field in ("search_queries", "video_queries", "agent_tags", "strategy_tags",
                       "saved_search_urls", "llm_generated_queries"):
            if isinstance(t.get(field), str):
                t[field] = json.loads(t[field])
        # Flag for using pre-computed LLM queries
        if args.use_llm_queries:
            t["_use_llm_queries"] = True

    print(f"Loaded {len(topics)} topics from topic_monitor table")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'} | "
          f"LLM: {'OFF' if args.no_llm else 'ON'} | "
          f"Curate: {args.curate} | "
          f"Use LLM queries: {args.use_llm_queries} | "
          f"Gaps only: {args.gaps_only}")

    total_stats = {"articles": 0, "transcripts": 0, "topics_processed": 0,
                   "topics_skipped": 0}

    for topic in topics:
        topic_id = topic["topic_id"]
        max_age = topic.get("max_age_days", 30)
        min_articles = topic.get("min_articles", 3)

        # Check existing count
        existing = _check_existing_count(conn, topic_id, max_age)
        print(f"\n{'─'*60}")
        print(f"Topic: {topic['display_name']} | Existing: {existing} | "
              f"Min: {min_articles} | Gap: {existing < min_articles}")

        if args.gaps_only and existing >= min_articles:
            print(f"  SKIP: {existing} >= {min_articles} (no gap)")
            total_stats["topics_skipped"] += 1
            continue

        result = process_topic(conn, topic, dry_run=args.dry_run,
                               use_llm=not args.no_llm, curate=args.curate)

        # Update last_searched timestamp
        if not args.dry_run:
            cur.execute("""
                UPDATE topic_monitor
                SET last_searched = NOW(),
                    last_found_count = %s,
                    updated_at = NOW()
                WHERE topic_id = %s
            """, (result["found"], topic_id))
            conn.commit()

        total_stats["articles"] += result["articles"]
        total_stats["transcripts"] += result["transcripts"]
        total_stats["topics_processed"] += 1

        print(f"\n  Result: {result['articles']} articles, "
              f"{result['transcripts']} transcripts saved "
              f"(sources: {', '.join(result['sources_used'])})")

    # Summary
    print(f"\n{'='*60}")
    print(f"TOPIC INGESTION COMPLETE")
    print(f"  Topics processed: {total_stats['topics_processed']}")
    print(f"  Topics skipped: {total_stats['topics_skipped']}")
    print(f"  Articles saved: {total_stats['articles']}")
    print(f"  Transcripts saved: {total_stats['transcripts']}")
    print(f"{'='*60}")

    # Desk-side projection if anything was found (no Telegram — counts are noise;
    # the articles themselves land in news_articles / youtube_transcripts).
    if total_stats["articles"] + total_stats["transcripts"] > 0 and not args.dry_run:
        _write_desk_projection(total_stats)

    conn.close()

    # Auto-trigger curation pipeline after ingestion (unless the caller is the
    # curator's own re-ingest step — that would form an unbounded ingest<->curate
    # loop; see --no-auto-curate).
    if (total_stats["articles"] + total_stats["transcripts"] > 0
            and not args.dry_run and not args.no_auto_curate):
        print("\n  >> Triggering post-ingestion curation pipeline...")
        try:
            import subprocess
            curator_cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "topic_curator.py")]
            if args.topic:
                curator_cmd.extend(["--topic", args.topic])
            if args.no_llm:
                curator_cmd.append("--no-llm")
            else:
                curator_cmd.append("--improve-queries")
            subprocess.Popen(curator_cmd, stdout=open(str(PROJECT_ROOT / "logs" / "topic_curator.log"), "a"),
                             stderr=subprocess.STDOUT, cwd=str(PROJECT_ROOT))
            print("  >> Curator started in background")
        except Exception as e:
            print(f"  >> Curator launch failed: {e}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
