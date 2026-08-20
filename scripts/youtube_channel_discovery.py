#!/usr/bin/env python3
"""youtube_channel_discovery.py — Agent-driven YouTube channel discovery.

Agents search for new relevant channels across full CIO asset classes
(equities, ETFs, bonds, options income, macro, crypto/commodities, retirement),
score them, and recommend additions. High-confidence ADD candidates
(quality_score >= 75) are auto-approved into youtube_channels; REVIEW stays
for human approval.

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

# Cap new candidate inserts per discovery run to avoid spam.
MAX_CANDIDATES_PER_RUN = 20
# Auto-approve threshold: recommendation==ADD and quality_score >= this.
AUTO_APPROVE_QUALITY = 75


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


# Search queries spanning full CIO asset-class coverage (keep useful retirement queries).
DISCOVERY_QUERIES = [
    # ── Growth / tech / value / small-cap stocks ──
    {"query": "growth stocks investing strategy 2026", "strategy": "core_growth_compounder", "asset_class": "equity"},
    {"query": "technology stocks analysis Nasdaq", "strategy": "tech_growth", "asset_class": "equity"},
    {"query": "value investing deep value stocks", "strategy": "value_equity", "asset_class": "equity"},
    {"query": "small cap stocks investing Russell 2000", "strategy": "small_cap_equity", "asset_class": "equity"},
    {"query": "dividend growth investing 2026", "strategy": "dividend_growth_compounder", "asset_class": "equity"},
    {"query": "defense sector stocks analysis", "strategy": "defense_sector", "asset_class": "equity"},
    # ── Broad + sector + thematic ETFs ──
    {"query": "ETF portfolio strategy VTI SPY QQQ", "strategy": "core_etf", "asset_class": "etf"},
    {"query": "sector ETF rotation investing XLK XLF XLE", "strategy": "sector_etf", "asset_class": "etf"},
    {"query": "thematic ETF investing AI clean energy", "strategy": "thematic_etf", "asset_class": "etf"},
    {"query": "REIT dividend income investing", "strategy": "reit_income", "asset_class": "etf"},
    # ── Bonds: aggregate / corporate / muni / Treasury ──
    {"query": "bond ETF fixed income strategy AGG BND", "strategy": "bond_income", "asset_class": "bond"},
    {"query": "corporate bond ETF investment grade HYG LQD", "strategy": "corporate_bonds", "asset_class": "bond"},
    {"query": "municipal bond investing tax free muni ETF", "strategy": "muni_bonds", "asset_class": "bond"},
    {"query": "Treasury bond ETF TLT IEF interest rates", "strategy": "treasury_bonds", "asset_class": "bond"},
    # ── Covered-call / put-selling / income options ETFs ──
    {"query": "covered call ETF income strategy JEPI QYLD", "strategy": "tactical_income", "asset_class": "options_income"},
    {"query": "put selling ETF cash secured put strategy", "strategy": "put_selling_income", "asset_class": "options_income"},
    {"query": "high yield income BDC CEF investing", "strategy": "high_yield_income_bdc", "asset_class": "income"},
    # ── Inverse / bearish ETFs ──
    {"query": "inverse ETF bearish hedging SQQQ SH", "strategy": "inverse_bearish", "asset_class": "etf"},
    # ── Macro / Fed ──
    {"query": "Federal Reserve FOMC macro investing outlook", "strategy": "macro_fed", "asset_class": "macro"},
    {"query": "inflation interest rates macro analysis", "strategy": "macro_rates", "asset_class": "macro"},
    # ── International / emerging ──
    {"query": "international stocks emerging markets ETF VXUS", "strategy": "international_equity", "asset_class": "equity"},
    {"query": "emerging markets investing EEM VWO", "strategy": "emerging_markets", "asset_class": "equity"},
    # ── Crypto / commodities ──
    {"query": "bitcoin crypto ETF investing analysis", "strategy": "crypto", "asset_class": "crypto"},
    {"query": "commodities gold oil investing ETF", "strategy": "commodities", "asset_class": "commodity"},
    # ── Retirement (kept) ──
    {"query": "retirement income strategy SSDI disability", "strategy": "disability_retirement_planning", "asset_class": "retirement"},
    {"query": "Roth conversion ladder strategy", "strategy": "retirement_planning", "asset_class": "retirement"},
    {"query": "Medicare IRMAA retirement planning", "strategy": "retirement_planning", "asset_class": "retirement"},
    {"query": "portfolio rebalancing allocation strategy", "strategy": "core_growth_compounder", "asset_class": "allocation"},
]

# Extra keywords by asset_class so non-retirement discovery queries can still score.
ASSET_CLASS_KEYWORDS = {
    "equity": ["growth", "value", "stocks", "equity", "earnings", "small cap", "tech"],
    "etf": ["etf", "index", "sector", "thematic", "passive", "vanguard", "ishares"],
    "bond": ["bond", "fixed income", "treasury", "yield curve", "duration", "muni", "corporate bond"],
    "options_income": ["covered call", "put selling", "options income", "cash secured", "premium", "jepi", "qyld"],
    "income": ["dividend", "yield", "bdc", "cef", "income"],
    "macro": ["fed", "fomc", "inflation", "rates", "macro", "recession"],
    "crypto": ["bitcoin", "crypto", "ethereum", "btc", "digital asset"],
    "commodity": ["gold", "oil", "commodities", "silver", "copper"],
    "retirement": ["retirement", "roth", "ira", "401k", "rmd", "medicare"],
    "allocation": ["allocation", "rebalance", "portfolio", "asset allocation"],
}


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


def score_channel(name: str, description: str, subscribers: int, video_count: int,
                  strategy: str, asset_class: str = "") -> dict:
    """Score a discovered channel for relevance and quality."""
    from content_scoring import RELEVANCE_KEYWORDS

    desc_lower = f"{name} {description}".lower()
    score = 0
    matched = []

    for kw in RELEVANCE_KEYWORDS["high"]:
        if kw in desc_lower:
            score += 15
            matched.append(kw)
    for kw in RELEVANCE_KEYWORDS["medium"]:
        if kw in desc_lower:
            score += 8
            matched.append(kw)

    # Asset-class keyword boost (growth/bonds/puts/crypto etc.)
    for kw in ASSET_CLASS_KEYWORDS.get(asset_class, []):
        if kw in desc_lower and kw not in matched:
            score += 12
            matched.append(kw)

    if subscribers > 500000:
        score += 20
    elif subscribers > 100000:
        score += 15
    elif subscribers > 10000:
        score += 10
    elif subscribers > 1000:
        score += 5

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
        "asset_class": asset_class,
    }


def _auto_approve_candidate(cur, channel_id: str, channel_name: str, strategy: str) -> bool:
    """Insert into youtube_channels and mark candidate approved. Returns True on success."""
    try:
        cur.execute("""
            INSERT INTO youtube_channels (channel_id, channel_name, channel_url, strategy_focus, added_by)
            VALUES (%s, %s, %s, %s, 'ai_auto_approved')
            ON CONFLICT (channel_id) DO NOTHING
        """, (channel_id, channel_name,
              f"https://www.youtube.com/channel/{channel_id}",
              strategy))
        cur.execute(
            "UPDATE youtube_channel_candidates SET status='approved' WHERE channel_id=%s",
            (channel_id,),
        )
        return True
    except Exception as e:
        print(f"  [yt-discover] Auto-approve failed for {channel_name}: {e}")
        return False


def _notify_telegram(candidates: list) -> bool:
    """Send discovery results via telegram_alert.send_telegram. Never hard-fails."""
    if not candidates:
        return False
    try:
        from telegram_alert import send_telegram as _tg
    except Exception as e:
        print(f"[yt-discover] Telegram import failed (tokens/module missing?): {e}")
        return False

    lines = ["🔍 *YouTube Channel Discovery*", f"Found {len(candidates)} new candidates:", ""]
    auto = [c for c in candidates if c.get("auto_approved")]
    if auto:
        lines.append(f"_Auto-approved: {len(auto)}_")
    for c in candidates[:5]:
        tag = "AUTO" if c.get("auto_approved") else c["recommendation"]
        lines.append(f"  [{tag}] Q:{c['quality']} *{c['name']}*")
        lines.append(f"    {c['subscribers']:,} subs · {c['strategy'].replace('_', ' ')}")
        if c.get("keywords"):
            lines.append(f"    keywords: {', '.join(c['keywords'][:3])}")
    lines.append("\n_Review: `python3 scripts/youtube_channel_discovery.py --list-candidates`_")

    try:
        ok = _tg("\n".join(lines))
        if ok:
            print("[yt-discover] Telegram notify accepted")
            return True
        print("[yt-discover] Telegram notify not delivered "
              "(ENABLE_TELEGRAM/tokens missing or routed to digest — check logs)")
        return False
    except Exception as e:
        print(f"[yt-discover] Telegram notify failed (non-fatal): {e}")
        return False


def discover_channels(send_telegram: bool = False,
                      max_candidates: int = MAX_CANDIDATES_PER_RUN) -> dict:
    """Search for new relevant YouTube channels and score them."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT channel_id FROM youtube_channels")
    existing = set(r["channel_id"] for r in cur.fetchall())

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
    auto_approved = 0
    inserts = 0

    for q in DISCOVERY_QUERIES:
        if inserts >= max_candidates:
            print(f"[yt-discover] Hit max candidates cap ({max_candidates}); stopping inserts")
            break

        results = _youtube_search(q["query"], max_results=3)
        total_searched += 1

        for ch in results:
            if inserts >= max_candidates:
                break
            if ch["channel_id"] in existing:
                continue

            stats = _get_channel_stats(ch["channel_id"])
            subs = stats.get("subscribers", 0)
            vids = stats.get("video_count", 0)
            desc = stats.get("description", ch.get("description", ""))

            scores = score_channel(
                ch["channel_name"], desc, subs, vids, q["strategy"],
                asset_class=q.get("asset_class", ""),
            )

            if scores["recommendation"] == "SKIP":
                continue

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
                if cur.rowcount == 0:
                    continue
                inserts += 1

                did_auto = False
                if (scores["recommendation"] == "ADD"
                        and scores["quality_score"] >= AUTO_APPROVE_QUALITY):
                    did_auto = _auto_approve_candidate(
                        cur, ch["channel_id"], ch["channel_name"], q["strategy"])
                    if did_auto:
                        auto_approved += 1

                candidates.append({
                    "name": ch["channel_name"],
                    "channel_id": ch["channel_id"],
                    "subscribers": subs,
                    "quality": scores["quality_score"],
                    "recommendation": scores["recommendation"],
                    "strategy": q["strategy"],
                    "asset_class": q.get("asset_class", ""),
                    "keywords": scores["matched_keywords"][:4],
                    "auto_approved": did_auto,
                })
                existing.add(ch["channel_id"])
            except Exception:
                conn.rollback()

    conn.commit()
    conn.close()

    candidates.sort(key=lambda c: c["quality"], reverse=True)

    print(f"[yt-discover] Searched {total_searched} queries, "
          f"found {len(candidates)} new candidates "
          f"(auto-approved={auto_approved}, cap={max_candidates})")
    for c in candidates[:10]:
        tag = "AUTO" if c.get("auto_approved") else c["recommendation"]
        print(f"  [{tag:6}] Q:{c['quality']:3} {c['name']:30} "
              f"subs:{c['subscribers']:>8,} strat:{c['strategy']}")

    if send_telegram:
        _notify_telegram(candidates)

    return {
        "searched": total_searched,
        "candidates": len(candidates),
        "auto_approved": auto_approved,
        "capped_at": max_candidates,
    }


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

    cur.execute("""
        INSERT INTO youtube_channels (channel_id, channel_name, channel_url, strategy_focus, added_by)
        VALUES (%s, %s, %s, %s, 'ai_discovered')
        ON CONFLICT (channel_id) DO NOTHING
    """, (channel_id, candidate["channel_name"],
          f"https://www.youtube.com/channel/{channel_id}",
          candidate["strategy_focus"]))

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
            try:
                kw = json.loads(kw)
            except Exception:
                kw = []
        print(f"  [{r['recommendation']:6}] Q:{r['quality_score']:3} {r['channel_name']:30} "
              f"subs:{r['subscribers']:>8,} strat:{r['strategy_focus']}")
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
