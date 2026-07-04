#!/usr/bin/env python3
"""news_ingestion.py — Ingest news for portfolio/watchlist symbols.

Sources:
  - Yahoo RSS (free, always active)
  - Finnhub (if FINNHUB_API_KEY exists)
  - Benzinga RSS (free, always active — benzinga.com/feed)
  - Benzinga API (if BENZINGA_API_KEY exists — richer data, analyst ratings)

All sources dedup by symbol + title. Scored + tagged via content_scoring.
Feeds into: news_articles, catalyst_events, sentiment_observations.

Modes:
  --priority    Weekday cadence: holdings/proposals/buy/active/directives (NEWS_INGEST_MAX, default 60)
  --tail-rotate Weekend stagger: rotating batch through classified tail (NEWS_TAIL_BATCH, default 500)

Every successful run prints a logfile heartbeat line for system_freshness_monitor.py:
  [news] heartbeat ok mode=... scanned=N new=M offset=...

Usage:
    python3 scripts/news_ingestion.py --priority [--json]
    python3 scripts/news_ingestion.py --tail-rotate [--json]
    python3 scripts/news_ingestion.py --full [--json]   # alias: one-shot full universe head (legacy)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
ROTATION_FILE = RUNTIME_DIR / "news_ingest_rotation.json"
HEARTBEAT_NEEDLE = "[news] heartbeat ok"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _strategy_map(conn, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, COALESCE(strategy_type, 'watchlist') FROM ticker_strategy_classifications
           WHERE symbol = ANY(%s)""",
        (symbols,),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def _get_actionable_pairs(conn) -> list[tuple[str, str]]:
    """Holdings, proposals, scans, directives, daily-priority buy/start — always first in --priority."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT DISTINCT UPPER(u.symbol) AS symbol, COALESCE(tsc.strategy_type, 'traded') AS strategy_type
        FROM (
            SELECT symbol FROM paper_trades
             WHERE entry_time > now() - interval '30 days' AND symbol IS NOT NULL
            UNION SELECT symbol FROM paper_trade_proposals
             WHERE status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST','MODIFIED','BROKER_SUBMITTED')
               AND symbol IS NOT NULL
            UNION SELECT symbol FROM trade_ai_scans
             WHERE run_date >= CURRENT_DATE AND decision IN ('GO','WAIT') AND symbol IS NOT NULL
            UNION SELECT symbol FROM watchlist_items WHERE status = 'active' AND symbol IS NOT NULL
            UNION SELECT symbol FROM watchlist_items
             WHERE in_directive_watch = true AND status <> 'removed' AND symbol IS NOT NULL
        ) u
        LEFT JOIN ticker_strategy_classifications tsc ON tsc.symbol = u.symbol
    """)
    pairs = [(r["symbol"], r["strategy_type"]) for r in cur.fetchall() if r.get("symbol")]
    try:
        from watchlist_priority import load_daily_priority_symbols
        dcur = conn.cursor()
        daily = load_daily_priority_symbols(dcur, PROJECT_ROOT)
        dcur.close()
        smap = _strategy_map(conn, sorted(daily))
        seen = {p[0].upper() for p in pairs}
        for sym in sorted(daily):
            if sym not in seen:
                pairs.append((sym, smap.get(sym, "watchlist")))
                seen.add(sym)
    except Exception:
        pass
    return pairs


def _get_full_universe_pairs(conn) -> list[tuple[str, str]]:
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT symbol, COALESCE(strategy_type, 'watchlist') AS strategy_type "
        "FROM ticker_strategy_classifications WHERE active=TRUE ORDER BY symbol"
    )
    symbols = [(r["symbol"], r["strategy_type"]) for r in cur.fetchall()]
    existing = {s[0] for s in symbols}
    try:
        cur.execute("""
            SELECT DISTINCT symbol, COALESCE(strategy_id, 'screener') AS strategy_type
            FROM incubator_universe
            WHERE status = 'ACTIVE' AND latest_score >= 35
            ORDER BY latest_score DESC LIMIT 50
        """)
        for r in cur.fetchall():
            if r["symbol"] not in existing:
                symbols.append((r["symbol"], r["strategy_type"]))
                existing.add(r["symbol"])
    except Exception:
        conn.rollback()
    return symbols


def _load_rotation() -> dict:
    try:
        return json.loads(ROTATION_FILE.read_text())
    except Exception:
        return {"offset": 0, "tail_size": 0, "last_mode": None}


def _save_rotation(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    ROTATION_FILE.write_text(json.dumps(state, indent=2, default=str))


def select_tail_batch(
    universe: list[tuple[str, str]],
    priority_syms: set[str],
    batch_size: int,
    offset: int,
) -> tuple[list[tuple[str, str]], int, int]:
    """Return (batch pairs, next_offset, tail_len) rotating through non-priority classified names."""
    stmap = {s: t for s, t in universe}
    tail = sorted(s for s in stmap if s.upper() not in priority_syms)
    n = len(tail)
    if n == 0:
        return [], 0, 0
    batch_size = min(batch_size, n)
    batch = [(tail[(offset + i) % n], stmap[tail[(offset + i) % n]]) for i in range(batch_size)]
    return batch, (offset + batch_size) % n, n


def _proposal_queue_pairs(conn) -> list[tuple[str, str]]:
    """Active broker/paper proposals — always head of --priority ingest (fixes 60-cap starvation)."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT DISTINCT UPPER(symbol) AS symbol,
               COALESCE(strategy_id, 'watchlist') AS strategy_type
        FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'PROPOSED', 'MODIFIED', 'BROKER_SUBMITTED')
          AND symbol IS NOT NULL
        ORDER BY symbol
    """)
    return [(str(r["symbol"]).upper(), str(r["strategy_type"] or "watchlist")) for r in cur.fetchall() if r.get("symbol")]


def _priority_symbol_list(conn) -> list[tuple[str, str]]:
    proposal_first = _proposal_queue_pairs(conn)
    prop_set = {p[0].upper() for p in proposal_first}
    actionable = _get_actionable_pairs(conn)
    rest_actionable = [p for p in actionable if p[0].upper() not in prop_set]
    act_set = prop_set | {a[0].upper() for a in rest_actionable}
    rest = _get_full_universe_pairs(conn)
    merged = proposal_first + rest_actionable + [p for p in rest if p[0].upper() not in act_set]
    return merged


def _resolve_symbols(conn, mode: str) -> tuple[list[tuple[str, str]], dict]:
    meta = {"mode": mode, "offset": 0, "tail_size": 0}
    if mode == "priority":
        return _priority_symbol_list(conn), meta
    if mode == "tail_rotate":
        universe = _get_full_universe_pairs(conn)
        actionable = _get_actionable_pairs(conn)
        priority_syms = {a[0].upper() for a in actionable}
        batch_size = int(os.environ.get("NEWS_TAIL_BATCH", "500"))
        state = _load_rotation()
        offset = int(state.get("offset") or 0)
        batch, next_off, tail_n = select_tail_batch(universe, priority_syms, batch_size, offset)
        meta.update(offset=offset, next_offset=next_off, tail_size=tail_n, batch_size=batch_size)
        return batch, meta
    # legacy --full: full universe head (no rotation)
    return _get_full_universe_pairs(conn), meta


def _fetch_yahoo_rss(symbol: str) -> list:
    articles = []
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
            for item in root.findall(".//item"):
                articles.append({
                    "title": item.findtext("title", ""),
                    "summary": (item.findtext("description", "") or "")[:500],
                    "source": "yahoo_rss",
                    "source_url": item.findtext("link", ""),
                    "published_at": item.findtext("pubDate", ""),
                })
    except Exception:
        pass
    return articles


def _fetch_finnhub(symbol: str, api_key: str) -> list:
    articles = []
    try:
        from_date = datetime.now().strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={from_date}&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for item in data[:5]:
                articles.append({
                    "title": item.get("headline", ""),
                    "summary": (item.get("summary", "") or "")[:500],
                    "source": "finnhub",
                    "source_url": item.get("url", ""),
                    "published_at": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat()
                    if item.get("datetime") else None,
                })
    except Exception:
        pass
    return articles


def _fetch_google_news_rss(symbol: str) -> list:
    articles = []
    try:
        import urllib.parse
        url = f"https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TradeAI/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "")
                source_name = item.findtext("source", "")
                src_lower = source_name.lower()
                if "benzinga" in src_lower:
                    source_tag = "benzinga_rss"
                elif "seeking alpha" in src_lower:
                    source_tag = "seeking_alpha"
                elif "motley fool" in src_lower:
                    source_tag = "motley_fool"
                elif "barron" in src_lower:
                    source_tag = "barrons"
                elif "morningstar" in src_lower:
                    source_tag = "morningstar"
                elif "marketwatch" in src_lower:
                    source_tag = "marketwatch"
                else:
                    source_tag = f"google_news:{source_name[:30]}"
                articles.append({
                    "title": title,
                    "summary": f"[{source_name}] {title}",
                    "source": source_tag,
                    "source_url": item.findtext("link", ""),
                    "published_at": item.findtext("pubDate", ""),
                })
    except Exception:
        pass
    return articles


def _fetch_benzinga_api(symbol: str, api_key: str) -> list:
    articles = []
    try:
        import re
        from_date = datetime.now().strftime("%Y-%m-%d")
        url = (
            f"https://api.benzinga.com/api/v2/news?token={api_key}&tickers={symbol}"
            f"&dateFrom={from_date}&pageSize=5&displayOutput=full"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for item in data[:5]:
                body = item.get("body", item.get("teaser", ""))
                clean_body = re.sub(r"<[^>]+>", "", body or "")[:500]
                articles.append({
                    "title": item.get("title", ""),
                    "summary": clean_body,
                    "source": "benzinga_api",
                    "source_url": item.get("url", ""),
                    "published_at": item.get("created", item.get("updated", "")),
                })
    except Exception:
        pass
    return articles


def _feed_downstream(conn, symbol: str, strategy_type: str, article: dict, scores: dict, tags: dict):
    cur = conn.cursor()
    title = article.get("title", "")[:500]
    summary = article.get("summary", "")[:1000]
    source = article.get("source", "unknown")
    relevance = scores.get("relevance_score", 0)

    if relevance > 0.3:
        try:
            from news_to_catalyst import _classify, _severity_from_weight
            ctype = _classify(title, summary)
            severity = _severity_from_weight(float(relevance))
        except Exception:
            ctype, severity = "news", "low"
        try:
            cur.execute("SAVEPOINT ds_cat")
            cur.execute("""INSERT INTO catalyst_events
                    (symbol, strategy_type, catalyst_type, headline, description,
                     severity, confidence, impact_score, source, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, headline) DO NOTHING""",
                (symbol, strategy_type, ctype, title, summary,
                 severity, round(float(relevance), 2), round(float(relevance) * 10, 1),
                 source, article.get("published_at")))
            cur.execute("RELEASE SAVEPOINT ds_cat")
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT ds_cat")
            except Exception:
                pass

    try:
        from content_scoring import SENTIMENT_POSITIVE, SENTIMENT_NEGATIVE
        text_lower = f"{title} {summary}".lower()
        pos = sum(1 for s in SENTIMENT_POSITIVE if s in text_lower)
        neg = sum(1 for s in SENTIMENT_NEGATIVE if s in text_lower)
        sentiment = "positive" if pos > neg else "negative" if neg > pos else "neutral"
        cur.execute("SAVEPOINT ds_sent")
        cur.execute("""INSERT INTO sentiment_observations
                (symbol, strategy_type, source_type, overall_sentiment, sentiment_score, raw_text_snippet)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (symbol, strategy_type, source, sentiment, relevance, title[:500]))
        cur.execute("RELEASE SAVEPOINT ds_sent")
    except Exception:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT ds_sent")
        except Exception:
            pass


def _scan_symbols(conn, cur, symbols: list[tuple[str, str]], finnhub_key: str, benzinga_key: str) -> dict:
    total_new = 0
    total_scanned = 0
    source_counts: dict[str, int] = {}

    for sym, strategy_type in symbols:
        articles = _fetch_yahoo_rss(sym)
        if finnhub_key:
            articles.extend(_fetch_finnhub(sym, finnhub_key))
        articles.extend(_fetch_google_news_rss(sym))
        if benzinga_key:
            articles.extend(_fetch_benzinga_api(sym, benzinga_key))

        for a in articles:
            src = a.get("source", "")
            try:
                from hermes_source_policy import should_ingest
                ok, _why = should_ingest(src)
                if not ok:
                    continue
            except Exception:
                pass
            is_google = src.startswith("google_news:") or src in (
                "seeking_alpha", "motley_fool", "morningstar", "barrons", "marketwatch", "benzinga_rss"
            )
            if is_google:
                if not a.get("source_url"):
                    continue
                cur.execute("SELECT id FROM news_articles WHERE source_url=%s LIMIT 1", (a["source_url"][:500],))
                if cur.fetchone():
                    continue
            else:
                cur.execute(
                    "SELECT id FROM news_articles WHERE symbol=%s AND title=%s LIMIT 1",
                    (sym, a["title"][:500]),
                )
                if cur.fetchone():
                    continue

            from content_scoring import score_content, tag_content
            _scores = score_content(title=a["title"], text=a.get("summary", ""), source=a["source"], symbols=[sym])
            _tags = tag_content(text=a.get("summary", ""), title=a["title"])

            cur.execute("""
                INSERT INTO news_articles (symbol, strategy_type, title, summary, source, source_url, published_at,
                    relevance_score, strategy_tags, agent_tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (sym, strategy_type, a["title"][:500], a.get("summary", "")[:1000],
                  a["source"], a.get("source_url", "")[:500],
                  a.get("published_at"), _scores["relevance_score"],
                  json.dumps(_tags["strategy_tags"]), json.dumps(_tags["agent_tags"])))
            _feed_downstream(conn, sym, strategy_type, a, _scores, _tags)
            source_counts[a["source"]] = source_counts.get(a["source"], 0) + 1
            total_new += 1
        total_scanned += 1
        # Commit per symbol: the next iteration starts with 3-4 network fetches, and an
        # open transaction idling through them is killed at 120s — losing this symbol's
        # inserts and spamming "current transaction is aborted" (2026-07-04 audit, #2 offender).
        try:
            conn.commit()
        except Exception:
            conn.rollback()

    return {
        "scanned": total_scanned,
        "new_articles": total_new,
        "by_source": {s: c for s, c in source_counts.items() if c > 0},
    }


def _emit_heartbeat(mode: str, scanned: int, new: int, meta: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [HEARTBEAT_NEEDLE, f"mode={mode}", f"scanned={scanned}", f"new={new}", f"ts={ts}"]
    if meta.get("offset") is not None and mode == "tail_rotate":
        parts.append(f"offset={meta.get('offset')}")
        parts.append(f"next_offset={meta.get('next_offset')}")
        parts.append(f"tail_size={meta.get('tail_size')}")
    print(" ".join(parts), flush=True)


def ingest(mode: str = "priority") -> dict:
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    symbol_pairs, meta = _resolve_symbols(conn, mode)
    if mode == "priority":
        cap = int(os.environ.get("NEWS_INGEST_MAX", "60"))
        symbol_pairs = symbol_pairs[:cap]
    elif mode == "full":
        cap = int(os.environ.get("NEWS_INGEST_MAX", "60"))
        symbol_pairs = symbol_pairs[:cap]
        mode = "full"

    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    benzinga_key = os.environ.get("BENZINGA_API_KEY", "")
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if not finnhub_key and line.startswith("FINNHUB_API_KEY="):
            finnhub_key = line.split("=", 1)[1].strip()
        if not benzinga_key and line.startswith("BENZINGA_API_KEY="):
            benzinga_key = line.split("=", 1)[1].strip()

    stats = _scan_symbols(conn, cur, symbol_pairs, finnhub_key, benzinga_key)
    conn.commit()
    conn.close()

    if mode == "tail_rotate" and meta.get("next_offset") is not None:
        _save_rotation({
            "offset": meta["next_offset"],
            "tail_size": meta.get("tail_size", 0),
            "last_mode": mode,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "last_scanned": stats["scanned"],
            "last_new": stats["new_articles"],
        })

    src_summary = ", ".join(f"{s}:{c}" for s, c in stats.get("by_source", {}).items())
    print(f"[news] Scanned {stats['scanned']} symbols, {stats['new_articles']} new articles"
          + (f" — sources: {src_summary}" if src_summary else ""))
    _emit_heartbeat(mode, stats["scanned"], stats["new_articles"], meta)

    return {**stats, "mode": mode, **{k: meta[k] for k in ("offset", "next_offset", "tail_size") if k in meta}}


if __name__ == "__main__":
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start("news_ingestion")
    except Exception:
        pass

    try:
        if "--tail-rotate" in sys.argv:
            run_mode = "tail_rotate"
        elif "--full" in sys.argv:
            run_mode = "full"
        else:
            run_mode = "priority"
        result = ingest(mode=run_mode)
        if "--json" in sys.argv:
            print(json.dumps(result, indent=2, default=str))
        if _run_id:
            try:
                from pipeline_registry import run_complete
                run_complete(_run_id, rows_processed=result.get("new_articles", 0))
            except Exception:
                pass
    except Exception as _e:
        if _run_id:
            try:
                from pipeline_registry import run_fail
                run_fail(_run_id, str(_e))
            except Exception:
                pass
        raise