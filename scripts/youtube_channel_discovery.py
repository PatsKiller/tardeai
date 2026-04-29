#!/usr/bin/env python3
"""youtube_channel_discovery.py — Agent-driven YouTube channel discovery.

Agents search for new relevant channels based on portfolio strategy types,
score them, and recommend additions. Human approves before tracking.

Usage:
    python3 scripts/youtube_channel_discovery.py --discover [--telegram]
    python3 scripts/youtube_channel_discovery.py --approve CHANNEL_ID
    python3 scripts/youtube_channel_discovery.py --list-candidates
"""
import json, os, sys, time
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


def _env(key):
    val = os.environ.get(key, "")
    if not val:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith(f"{key}="): val = line.split("=", 1)[1].strip()
    return val


# Search queries aligned with portfolio strategy types
DISCOVERY_QUERIES = [
    {"query": "dividend growth investing 2026", "strategy": "dividend_growth_compounder"},
    {"query": "retirement income strategy SSDI disability", "strategy": "disability_retirement_planning"},
    {"query": "Roth conversion ladder strategy", "strategy": "retirement_planning"},
    {"query": "high yield income BDC CEF investing", "strategy": "high_yield_income_bdc"},
    {"query": "covered call ETF income strategy", "strategy": "tactical_income"},
    {"query": "REIT dividend income investing", "strategy": "reit_income"},
    {"query": "defense sector stocks analysis", "strategy": "defense_sector"},
    {"query": "bond ETF fixed income strategy", "strategy": "bond_income"},
    {"query": "Medicare IRMAA retirement planning", "strategy": "retirement_planning"},
    {"query": "portfolio rebalancing allocation strategy", "strategy": "core_growth_compounder"},
]


def _youtube_search(query: str, max_results: int = 5) -> list:
    """Search YouTube for channels matching a query."""
    import urllib.request, urllib.parse
    api_key = _env("YOUTUBE_API_KEY")
    if not api_key:
        return []

    encoded = urllib.parse.quote(query)
    url = (f"https://www.googleapis.com/youtube/v3/search"
           f"?part=snippet&q={encoded}&type=channel&maxResults={max_results}"
           f"&relevanceLanguage=en&key={api_key}")

    try:
        time.sleep(0.2)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            channels = []
            for item in data.get("items", []):
                ch_id = item.get("id", {}).get("channelId", "")
                snippet = item.get("snippet", {})
                if ch_id:
                    channels.append({
                        "channel_id": ch_id,
                        "channel_name": snippet.get("channelTitle", ""),
                        "description": snippet.get("description", "")[:200],
                    })
            return channels
    except Exception as e:
        print(f"  [yt-discover] Search error: {e}")
        return []


def _get_channel_stats(channel_id: str) -> dict:
    """Get subscriber count and video count for scoring."""
    import urllib.request
    api_key = _env("YOUTUBE_API_KEY")
    if not api_key:
        return {}
    try:
        url = f"https://www.googleapis.com/youtube/v3/channels?part=statistics,snippet&id={channel_id}&key={api_key}"
        time.sleep(0.2)
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("items"):
                stats = data["items"][0].get("statistics", {})
                snippet = data["items"][0].get("snippet", {})
                return {
                    "subscribers": int(stats.get("subscriberCount", 0)),
                    "video_count": int(stats.get("videoCount", 0)),
                    "view_count": int(stats.get("viewCount", 0)),
                    "description": snippet.get("description", "")[:300],
                    "custom_url": snippet.get("customUrl", ""),
                }
    except Exception:
        pass
    return {}


def score_channel(name: str, description: str, subscribers: int, video_count: int, strategy: str) -> dict:
    """Score a discovered channel for relevance and quality."""
    from content_scoring import RELEVANCE_KEYWORDS

    desc_lower = f"{name} {description}".lower()
    score = 0
    matched = []

    # Relevance to retirement income investing
    for kw in RELEVANCE_KEYWORDS["high"]:
        if kw in desc_lower:
            score += 15
            matched.append(kw)
    for kw in RELEVANCE_KEYWORDS["medium"]:
        if kw in desc_lower:
            score += 8
            matched.append(kw)

    # Subscriber quality
    if subscribers > 500000:
        score += 20
    elif subscribers > 100000:
        score += 15
    elif subscribers > 10000:
        score += 10
    elif subscribers > 1000:
        score += 5

    # Video consistency (regular uploaders)
    if video_count > 500:
        score += 10
    elif video_count > 100:
        score += 7
    elif video_count > 30:
        score += 3

    quality = min(100, score)
    recommendation = "ADD" if quality >= 50 else "REVIEW" if quality >= 30 else "SKIP"

    return {
        "quality_score": quality,
        "matched_keywords": matched[:8],
        "recommendation": recommendation,
        "strategy": strategy,
    }


def discover_channels(send_telegram: bool = False) -> dict:
    """Search for new relevant YouTube channels and score them."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get existing channels to skip
    cur.execute("SELECT channel_id FROM youtube_channels")
    existing = set(r["channel_id"] for r in cur.fetchall())

    # Also check candidates table
    cur.execute("""CREATE TABLE IF NOT EXISTS youtube_channel_candidates (
        id SERIAL PRIMARY KEY,
        channel_id TEXT UNIQUE NOT NULL,
        channel_name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        subscribers INTEGER DEFAULT 0,
        video_count INTEGER DEFAULT 0,
        quality_score INTEGER DEFAULT 0,
        matched_keywords JSONB DEFAULT '[]'::jsonb,
        recommendation TEXT DEFAULT 'REVIEW',
        strategy_focus TEXT DEFAULT '',
        discovered_via TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""")
    conn.commit()

    cur.execute("SELECT channel_id FROM youtube_channel_candidates")
    existing.update(r["channel_id"] for r in cur.fetchall())

    candidates = []
    total_searched = 0

    for q in DISCOVERY_QUERIES:
        results = _youtube_search(q["query"], max_results=3)
        total_searched += 1

        for ch in results:
            if ch["channel_id"] in existing:
                continue

            # Get stats
            stats = _get_channel_stats(ch["channel_id"])
            subs = stats.get("subscribers", 0)
            vids = stats.get("video_count", 0)
            desc = stats.get("description", ch.get("description", ""))

            # Score
            scores = score_channel(ch["channel_name"], desc, subs, vids, q["strategy"])

            if scores["recommendation"] == "SKIP":
                continue

            # Store candidate
            try:
                cur.execute("""
                    INSERT INTO youtube_channel_candidates
                        (channel_id, channel_name, description, subscribers, video_count,
                         quality_score, matched_keywords, recommendation, strategy_focus, discovered_via)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (channel_id) DO NOTHING
                """, (ch["channel_id"], ch["channel_name"], desc[:300],
                      subs, vids, scores["quality_score"],
                      json.dumps(scores["matched_keywords"]),
                      scores["recommendation"], q["strategy"],
                      q["query"]))
                candidates.append({
                    "name": ch["channel_name"],
                    "subscribers": subs,
                    "quality": scores["quality_score"],
                    "recommendation": scores["recommendation"],
                    "strategy": q["strategy"],
                    "keywords": scores["matched_keywords"][:4],
                })
                existing.add(ch["channel_id"])
            except Exception:
                conn.rollback()

    conn.commit()
    conn.close()

    # Sort by quality
    candidates.sort(key=lambda c: c["quality"], reverse=True)

    print(f"[yt-discover] Searched {total_searched} queries, found {len(candidates)} new candidates")
    for c in candidates[:10]:
        print(f"  [{c['recommendation']:6}] Q:{c['quality']:3} {c['name']:30} subs:{c['subscribers']:>8,} strat:{c['strategy']}")

    if send_telegram and candidates:
        try:
            from telegram_alert import send_telegram as _tg
            lines = [f"\U0001F50D *YouTube Channel Discovery*", f"Found {len(candidates)} new candidates:", ""]
            for c in candidates[:5]:
                lines.append(f"  [{c['recommendation']}] Q:{c['quality']} *{c['name']}*")
                lines.append(f"    {c['subscribers']:,} subs · {c['strategy'].replace('_',' ')}")
                if c['keywords']:
                    lines.append(f"    keywords: {', '.join(c['keywords'][:3])}")
            lines.append(f"\n_Review: `python3 scripts/youtube_channel_discovery.py --list-candidates`_")
            _tg("\n".join(lines))
        except Exception:
            pass

    return {"searched": total_searched, "candidates": len(candidates)}


def approve_channel(channel_id: str) -> dict:
    """Approve a candidate channel and start tracking it."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM youtube_channel_candidates WHERE channel_id=%s", (channel_id,))
    candidate = cur.fetchone()
    if not candidate:
        conn.close()
        return {"error": f"Candidate {channel_id} not found"}

    # Add to tracked channels
    cur.execute("""
        INSERT INTO youtube_channels (channel_id, channel_name, channel_url, strategy_focus, added_by)
        VALUES (%s, %s, %s, %s, 'ai_discovered')
        ON CONFLICT (channel_id) DO NOTHING
    """, (channel_id, candidate["channel_name"],
          f"https://www.youtube.com/channel/{channel_id}",
          candidate["strategy_focus"]))

    # Mark as approved
    cur.execute("UPDATE youtube_channel_candidates SET status='approved' WHERE channel_id=%s", (channel_id,))

    conn.commit()
    conn.close()
    print(f"Approved: {candidate['channel_name']} → now tracking")
    return {"approved": candidate["channel_name"], "strategy": candidate["strategy_focus"]}


def list_candidates() -> list:
    """List pending channel candidates for review."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT channel_id, channel_name, subscribers, quality_score, recommendation,
               strategy_focus, matched_keywords, status
        FROM youtube_channel_candidates
        WHERE status='pending'
        ORDER BY quality_score DESC
    """)
    rows = cur.fetchall()
    conn.close()

    for r in rows:
        kw = r.get("matched_keywords", [])
        if isinstance(kw, str):
            try: kw = json.loads(kw)
            except: kw = []
        print(f"  [{r['recommendation']:6}] Q:{r['quality_score']:3} {r['channel_name']:30} subs:{r['subscribers']:>8,} strat:{r['strategy_focus']}")
        print(f"    ID: {r['channel_id']}  keywords: {', '.join(kw[:4])}")
    if not rows:
        print("  No pending candidates. Run --discover first.")
    return rows


if __name__ == "__main__":
    if "--discover" in sys.argv:
        tg = "--telegram" in sys.argv
        discover_channels(send_telegram=tg)
    elif "--approve" in sys.argv:
        idx = sys.argv.index("--approve")
        if idx + 1 < len(sys.argv):
            approve_channel(sys.argv[idx + 1])
        else:
            print("Usage: --approve CHANNEL_ID")
    elif "--list-candidates" in sys.argv or "--list" in sys.argv:
        list_candidates()
    else:
        print("Usage:")
        print("  --discover [--telegram]   Search for new channels and score them")
        print("  --list-candidates         Show pending candidates for review")
        print("  --approve CHANNEL_ID      Approve a candidate and start tracking")
