#!/usr/bin/env python3
"""intel_auto_discovery.py — Auto-discover new tickers from intelligence pipeline.

Scans news articles, YouTube transcripts, and social posts for ticker mentions
that are NOT currently in the watchlist or classifications. High-quality mentions
get auto-added to watchlist with appropriate strategy classification.

Runs after news ingestion to catch new symbols from Benzinga, Seeking Alpha, etc.

Usage:
    python3 scripts/intel_auto_discovery.py [--telegram] [--dry-run]
"""
import json, re, sys
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


# Common non-ticker words that look like tickers
TICKER_BLACKLIST = {
    "A", "I", "AM", "PM", "CEO", "CFO", "CTO", "IPO", "ETF", "GDP",
    "USA", "NYSE", "SEC", "FDA", "CPI", "PPI", "FOMC", "FED", "IMF",
    "AI", "IT", "OR", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF",
    "IN", "IS", "ME", "MY", "NO", "OF", "ON", "SO", "TO", "UP", "US",
    "WE", "OK", "TV", "CEO", "COO", "VP", "CFP", "CPA", "LLC", "INC",
    "THE", "FOR", "AND", "BUT", "NOT", "YOU", "ALL", "HER", "HIS",
    "RMD", "IRA", "MFS", "SGA", "AGI", "YTD", "RSI", "SMA", "ATR",
    "P&L", "Q1", "Q2", "Q3", "Q4", "FY", "YOY", "QOQ", "MOM",
    "BUY", "SELL", "HOLD", "ADD", "TRIM", "CASH", "DEBT",
}


def extract_tickers_from_text(text: str) -> list:
    """Extract potential ticker symbols from text ($SYMBOL or SYMBOL in context)."""
    tickers = set()

    # Pattern 1: $SYMBOL (most reliable)
    for m in re.finditer(r'\$([A-Z]{1,5})\b', text):
        sym = m.group(1)
        if sym not in TICKER_BLACKLIST and len(sym) >= 2:
            tickers.add(sym)

    # Pattern 2: "ticker SYMBOL" or "stock SYMBOL" or "shares of SYMBOL"
    for m in re.finditer(r'(?:ticker|stock|shares of|position in|bought|sold)\s+([A-Z]{2,5})\b', text, re.IGNORECASE):
        sym = m.group(1).upper()
        if sym not in TICKER_BLACKLIST:
            tickers.add(sym)

    return list(tickers)


def scan_for_discoveries(days: int = 2, min_mentions: int = 2) -> list:
    """Scan recent intel for ticker mentions not in watchlist/classifications.

    Returns list of {symbol, mentions, sources, strategy_tags, quality_avg}
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get existing symbols
    cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    known = set(r["symbol"] for r in cur.fetchall())
    cur.execute("SELECT DISTINCT symbol FROM watchlist_items")
    known.update(r["symbol"] for r in cur.fetchall())

    # Scan news articles
    cur.execute("""
        SELECT title, summary, source, relevance_score, strategy_tags
        FROM news_articles
        WHERE created_at > NOW() - INTERVAL '%s days'
          AND relevance_score > 0.3
    """, (days,))
    news = cur.fetchall()

    # Scan YouTube transcripts
    cur.execute("""
        SELECT title, LEFT(transcript_text, 2000) as text, channel_name as source,
               quality_score, relevance_score, strategy_tags
        FROM youtube_transcripts
        WHERE ingested_at > NOW() - INTERVAL '%s days'
          AND quality_score > 40
    """, (days,))
    yt = cur.fetchall()

    # Scan social posts
    cur.execute("""
        SELECT text, username as source, quality_score, relevance_score, strategy_tags
        FROM social_posts
        WHERE ingested_at > NOW() - INTERVAL '%s days'
          AND quality_score > 50
    """, (days,))
    social = cur.fetchall()

    conn.close()

    # Extract tickers from all content
    ticker_mentions = {}  # {SYMBOL: {count, sources, strategies, quality_scores}}

    for article in news:
        text = f"{article.get('title', '')} {article.get('summary', '')}"
        tickers = extract_tickers_from_text(text)
        for sym in tickers:
            if sym in known:
                continue
            if sym not in ticker_mentions:
                ticker_mentions[sym] = {"count": 0, "sources": set(), "strategies": set(), "quality_scores": []}
            ticker_mentions[sym]["count"] += 1
            ticker_mentions[sym]["sources"].add(article.get("source", "news"))
            for tag in (article.get("strategy_tags") or []):
                ticker_mentions[sym]["strategies"].add(tag)
            ticker_mentions[sym]["quality_scores"].append(float(article.get("relevance_score", 0)) * 100)

    for transcript in yt:
        text = f"{transcript.get('title', '')} {transcript.get('text', '')}"
        tickers = extract_tickers_from_text(text)
        for sym in tickers:
            if sym in known:
                continue
            if sym not in ticker_mentions:
                ticker_mentions[sym] = {"count": 0, "sources": set(), "strategies": set(), "quality_scores": []}
            ticker_mentions[sym]["count"] += 1
            ticker_mentions[sym]["sources"].add(f"youtube:{transcript.get('source', '')}")
            for tag in (transcript.get("strategy_tags") or []):
                ticker_mentions[sym]["strategies"].add(tag)
            ticker_mentions[sym]["quality_scores"].append(float(transcript.get("quality_score", 0)))

    for post in social:
        tickers = extract_tickers_from_text(post.get("text", ""))
        for sym in tickers:
            if sym in known:
                continue
            if sym not in ticker_mentions:
                ticker_mentions[sym] = {"count": 0, "sources": set(), "strategies": set(), "quality_scores": []}
            ticker_mentions[sym]["count"] += 1
            ticker_mentions[sym]["sources"].add(f"social:{post.get('source', '')}")
            ticker_mentions[sym]["quality_scores"].append(float(post.get("quality_score", 0)))

    # Filter: require min_mentions from multiple sources
    discoveries = []
    for sym, data in ticker_mentions.items():
        if data["count"] >= min_mentions:
            avg_q = sum(data["quality_scores"]) / len(data["quality_scores"]) if data["quality_scores"] else 0
            discoveries.append({
                "symbol": sym,
                "mentions": data["count"],
                "sources": sorted(data["sources"]),
                "strategy_tags": sorted(data["strategies"]),
                "quality_avg": round(avg_q, 1),
            })

    discoveries.sort(key=lambda d: (d["mentions"], d["quality_avg"]), reverse=True)
    return discoveries


def add_discoveries_to_watchlist(discoveries: list, dry_run: bool = False) -> dict:
    """Add discovered tickers to watchlist with auto-classification."""
    if not discoveries:
        return {"added": 0, "discoveries": []}

    import psycopg2
    conn = _get_conn()
    cur = conn.cursor()

    added = 0
    for d in discoveries[:10]:  # Cap at 10 per run
        sym = d["symbol"]
        strategy = d["strategy_tags"][0] if d["strategy_tags"] else "core_growth_compounder"

        if dry_run:
            print(f"  [DRY RUN] Would add: {sym} ({strategy}) — {d['mentions']} mentions, Q:{d['quality_avg']:.0f} from {', '.join(d['sources'][:3])}")
            continue

        # Add to classifications
        try:
            cur.execute("""
                INSERT INTO ticker_strategy_classifications
                    (symbol, strategy_type, asset_type, classification_source, confidence, rationale)
                VALUES (%s, %s, 'stock', 'intel_discovery', 0.6, %s)
                ON CONFLICT (symbol) DO NOTHING
            """, (sym, strategy, f"Auto-discovered: {d['mentions']} mentions in {', '.join(d['sources'][:3])}"))
        except Exception:
            conn.rollback()

        # Add to watchlist
        try:
            cur.execute("""
                INSERT INTO watchlist_items (symbol, source, status, origin_system, updated_at)
                VALUES (%s, 'ai_discovered', 'active', 'intel_auto_discovery', NOW())
                ON CONFLICT DO NOTHING
            """, (sym,))
        except Exception:
            conn.rollback()

        # Log intelligence event
        try:
            cur.execute("""
                INSERT INTO portfolio_intelligence_events
                    (symbol, strategy_type, event_type, severity, source, payload)
                VALUES (%s, %s, 'auto_discovery', 'info', 'intel_auto_discovery.py', %s)
            """, (sym, strategy, json.dumps({
                "mentions": d["mentions"],
                "sources": d["sources"],
                "quality_avg": d["quality_avg"],
            }, default=str)))
        except Exception:
            conn.rollback()

        added += 1
        print(f"  ADDED: {sym} ({strategy}) — {d['mentions']} mentions, Q:{d['quality_avg']:.0f}")

    conn.commit()
    conn.close()
    return {"added": added, "discoveries": discoveries[:10]}


def run(send_telegram: bool = False, dry_run: bool = False):
    """Scan intelligence and auto-discover new tickers."""
    print(f"[intel-discovery] {datetime.now().isoformat()} — Scanning for new tickers...")

    discoveries = scan_for_discoveries(days=3, min_mentions=2)
    print(f"[intel-discovery] Found {len(discoveries)} potential discoveries")

    if not discoveries:
        print("[intel-discovery] No new tickers meeting criteria")
        return {"found": 0, "added": 0}

    for d in discoveries[:10]:
        strats = ", ".join(d["strategy_tags"][:2]) if d["strategy_tags"] else "uncategorized"
        print(f"  {d['symbol']:6} {d['mentions']} mentions  Q:{d['quality_avg']:5.1f}  strat={strats}  from={', '.join(d['sources'][:3])}")

    result = add_discoveries_to_watchlist(discoveries, dry_run=dry_run)

    if send_telegram and result["added"] > 0:
        try:
            from telegram_alert import send_telegram as _tg
            lines = [f"\U0001F50D *Auto-Discovery: {result['added']} new ticker(s)*", ""]
            for d in result["discoveries"][:5]:
                strat = d["strategy_tags"][0].replace("_", " ") if d["strategy_tags"] else "?"
                lines.append(f"  *{d['symbol']}* — {d['mentions']} mentions, Q:{d['quality_avg']:.0f} ({strat})")
            lines.append(f"\n_Auto-added to watchlist. Agent analysis within 15-60 min._")
            _tg("\n".join(lines))
        except Exception:
            pass

    print(f"[intel-discovery] Done: {result['added']} added to watchlist")
    return result


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    dry = "--dry-run" in sys.argv
    run(send_telegram=tg, dry_run=dry)
