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

# The words that introduce a symbol, matched in any case. The scoped ``(?i:…)`` matters: it keeps
# the capture below case-SENSITIVE, which is the whole fix (see extract_tickers_from_text).
_TICKER_CONTEXT = r'(?i:ticker|stock|shares of|position in|bought|sold)'


def extract_tickers_from_text(text: str) -> list:
    """Extract potential ticker symbols from text ($SYMBOL or SYMBOL in context).

    The context word is case-insensitive; the SYMBOL is not. Applying ``re.IGNORECASE`` to the
    whole pattern made every ordinary capitalised-start word after "stock"/"bought"/"sold" a
    security: measured 2026-11-07 over 1,310 live news rows it produced 67 candidates of which
    59 were English words (PRICE 49, SEES 12, HAS 9, JUMPS 7 …). Those words became watchlist
    rows and then strategy cards: 170 of the 350 cards classified ``intel_discovery`` have no
    price bar at all, and 206 of the 221 NULL-price cards have never had one. A real ticker is
    printed in capitals, so requiring capitals costs only lowercase mentions and removes the
    whole class.
    """
    tickers = set()

    # Pattern 1: $SYMBOL (most reliable)
    for m in re.finditer(r'\$([A-Z]{1,5})\b', text):
        sym = m.group(1)
        if sym not in TICKER_BLACKLIST and len(sym) >= 2:
            tickers.add(sym)

    # Pattern 2: "ticker SYMBOL" / "stock SYMBOL" / "shares of SYMBOL" — context any case,
    # symbol exactly as printed.
    for m in re.finditer(rf'{_TICKER_CONTEXT}\s+([A-Z]{{2,5}})\b', text):
        sym = m.group(1)
        if sym not in TICKER_BLACKLIST:
            tickers.add(sym)

    return list(tickers)


# A candidate that has never printed a price is a word or a dead listing, not a security. Only
# the price lane can say which is true, so the scan asks it instead of trusting the text.
#
# The trade-off is deliberate and measured (2026-11-07): the price lane covers ~5,600 symbols and
# a news-only ticker is not in it, so this gate also drops real-but-uncovered listings — over a
# 30-day window it dropped 17 of 17 candidates (GOGO, TORO, TCEHY, EADSY …), every one of them a
# genuine security outside the lane. That is the honest answer for a discovery whose output is
# immediately turned into a levels card: support, resistance and an entry cannot be computed from
# no data, and minting the card anyway is what produced 170 of the 350 ``intel_discovery`` cards
# with no price. A dropped symbol belongs in a validation queue (see
# ``hermes_discovery_ingestors.ingest_tickers`` → NEEDS_VALIDATION), not in a card.
PRICE_LOOKBACK_DAYS = 30


def split_priceable(discoveries: list, priced_symbols) -> tuple:
    """Split candidates into (kept, dropped) by whether the price lane has a recent bar.

    Returning the dropped ones separately is the point: a gate that silently shortens a list
    is indistinguishable from a scan that found nothing.
    """
    priced = set(priced_symbols or ())
    kept = [d for d in discoveries if d.get("symbol") in priced]
    dropped = [d for d in discoveries if d.get("symbol") not in priced]
    return kept, dropped


def scan_for_discoveries(days: int = 2, min_mentions: int = 2, *, stats: dict = None) -> list:
    """Scan recent intel for ticker mentions not in watchlist/classifications.

    Returns list of {symbol, mentions, sources, strategy_tags, quality_avg}. ``stats``, when
    given, is filled with what the scan considered and what it dropped and why, so the reason
    travels to the caller instead of living only in a log line.
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get existing symbols
    cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    known = set(r["symbol"] for r in cur.fetchall())
    cur.execute("SELECT DISTINCT symbol FROM watchlist_items")
    known.update(r["symbol"] for r in cur.fetchall())

    # Symbols the price lane has actually seen recently. Read here, before the connection
    # closes: "has no price" is the price lane's fact to state, not this scan's to assume.
    cur.execute(
        "SELECT DISTINCT symbol FROM ticker_prices WHERE price_date > CURRENT_DATE - INTERVAL '%s days'",
        (PRICE_LOOKBACK_DAYS,),
    )
    priced = set(r["symbol"] for r in cur.fetchall())

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

    # A candidate the price lane has never seen is not a security. 206 of the 221 NULL-price
    # strategy cards have no price bar at all, and they arrived this way (2026-11-07).
    candidates, unpriced = split_priceable(discoveries, priced)
    if stats is not None:
        stats.update({
            "candidates": len(discoveries),
            "kept": len(candidates),
            "dropped_no_price": len(unpriced),
            "dropped_symbols": [d["symbol"] for d in unpriced][:20],
            "price_lookback_days": PRICE_LOOKBACK_DAYS,
        })
    if unpriced:
        print(f"  [intel-discovery] dropped {len(unpriced)} candidate(s) with no price bar in "
              f"{PRICE_LOOKBACK_DAYS} days: {', '.join(d['symbol'] for d in unpriced[:15])}"
              f"{' …' if len(unpriced) > 15 else ''}")

    candidates.sort(key=lambda d: (d["mentions"], d["quality_avg"]), reverse=True)
    return candidates


def add_discoveries_to_watchlist(discoveries: list, dry_run: bool = False) -> dict:
    """Add discovered tickers to watchlist with auto-classification.

    Each statement owns a savepoint. The previous bare ``except: conn.rollback()`` did two wrong
    things at once: it discarded every insert already made in this run (nothing commits until
    the end), and it still counted the symbol as added. A symbol now counts as added only when
    its watchlist row was actually written, and every failure is returned with its reason.
    """
    if not discoveries:
        return {"added": 0, "failed": 0, "failures": [], "discoveries": []}

    import psycopg2
    conn = _get_conn()
    cur = conn.cursor()

    added = 0
    failures = []
    for d in discoveries[:10]:  # Cap at 10 per run
        sym = d["symbol"]
        strategy = d["strategy_tags"][0] if d["strategy_tags"] else "core_growth_compounder"

        if dry_run:
            print(f"  [DRY RUN] Would add: {sym} ({strategy}) — {d['mentions']} mentions, Q:{d['quality_avg']:.0f} from {', '.join(d['sources'][:3])}")
            continue

        written = {}
        statements = {
            "classification": (
                """
                INSERT INTO ticker_strategy_classifications
                    (symbol, strategy_type, asset_type, classification_source, confidence, rationale)
                VALUES (%s, %s, 'stock', 'intel_discovery', 0.6, %s)
                ON CONFLICT (symbol) DO NOTHING
                """,
                (sym, strategy, f"Auto-discovered: {d['mentions']} mentions in {', '.join(d['sources'][:3])}"),
            ),
            "watchlist": (
                """
                INSERT INTO watchlist_items (symbol, source, status, origin_system, updated_at)
                VALUES (%s, 'ai_discovered', 'active', 'intel_auto_discovery', NOW())
                ON CONFLICT DO NOTHING
                """,
                (sym,),
            ),
            "event": (
                """
                INSERT INTO portfolio_intelligence_events
                    (symbol, strategy_type, event_type, severity, source, payload)
                VALUES (%s, %s, 'auto_discovery', 'info', 'intel_auto_discovery.py', %s)
                """,
                (sym, strategy, json.dumps({
                    "mentions": d["mentions"],
                    "sources": d["sources"],
                    "quality_avg": d["quality_avg"],
                }, default=str)),
            ),
        }
        for step, (sql, params) in statements.items():
            try:
                cur.execute("SAVEPOINT sp_discovery_stmt")
                cur.execute(sql, params)
                cur.execute("RELEASE SAVEPOINT sp_discovery_stmt")
                written[step] = True
            except Exception as e:
                written[step] = False
                failure = {"symbol": sym, "step": step, "error": str(e)[:200]}
                failures.append(failure)
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_discovery_stmt")
                    cur.execute("RELEASE SAVEPOINT sp_discovery_stmt")
                except Exception as savepoint_error:
                    # Nothing is left to undo (the savepoint went with the failed statement), so
                    # the batch continues — but the reason is recorded rather than dropped.
                    failure["savepoint_error"] = str(savepoint_error)[:160]

        if written.get("watchlist"):
            added += 1
            print(f"  ADDED: {sym} ({strategy}) — {d['mentions']} mentions, Q:{d['quality_avg']:.0f}")
        else:
            print(f"  NOT ADDED: {sym} — watchlist row was not written")

    conn.commit()
    conn.close()
    return {"added": added, "failed": len(failures), "failures": failures,
            "discoveries": discoveries[:10]}


def run(send_telegram: bool = False, dry_run: bool = False):
    """Scan intelligence and auto-discover new tickers."""
    print(f"[intel-discovery] {datetime.now().isoformat()} — Scanning for new tickers...")

    stats = {}
    discoveries = scan_for_discoveries(days=3, min_mentions=2, stats=stats)
    # A stat the scan did not fill is unknown, not zero: printing 0 would claim the scan looked
    # and found nothing to drop.
    considered = stats.get("candidates")
    dropped = stats.get("dropped_no_price")
    dropped_symbols = stats.get("dropped_symbols")
    print(f"[intel-discovery] Found {len(discoveries)} potential discoveries"
          f" (considered {considered if considered is not None else 'unknown'};"
          f" dropped for no price bar: {dropped if dropped is not None else 'unknown'})")

    if not discoveries:
        print("[intel-discovery] No new tickers meeting criteria")
        return {"found": 0, "added": 0,
                "dropped_no_price": dropped,
                "dropped_symbols": dropped_symbols}

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
            _tg("\n".join(lines), priority="P3", producer="intel_auto_discovery")
        except Exception:
            pass

    print(f"[intel-discovery] Done: {result['added']} added to watchlist"
          f"{', ' + str(result['failed']) + ' failed' if result.get('failed') else ''}")
    result.update({
        "dropped_no_price": dropped,
        "dropped_symbols": dropped_symbols,
    })
    return result


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    dry = "--dry-run" in sys.argv
    run(send_telegram=tg, dry_run=dry)
