#!/usr/bin/env python3
"""
social_scalp_scanner.py

Reads overnight social mentions → Finviz lookup → 6-pillar score → Telegram on GO/A+.

Schedule: 6:00 AM every 30 min until 10:00 AM, then hourly until 4:00 PM M-F.
Triggered by cron — each run is stateless (dedup via scalp_scan_results table).
"""

import csv, io, json, logging, os, sys, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import requests
from psycopg2.extras import RealDictCursor

# --- Setup ---
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from finviz_enrichment import enrich_tickers
from scoring import score_ticker, _load_weights
from telegram_alert import send_telegram
from scalp_ws_client import broadcast_scalp_update
from social_route_policy import route_social_candidate
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SCALP] %(message)s")
logger = logging.getLogger(__name__)

# --- Config (env-tunable; defaults preserve prior behavior) ---
LOOKBACK_HOURS      = int(os.getenv("SCALP_LOOKBACK_HOURS", "18"))       # social_posts window
MIN_MENTIONS        = int(os.getenv("SCALP_MIN_MENTIONS", "2"))          # min ticker mentions to consider
GO_THRESHOLD        = int(os.getenv("SCALP_GO_THRESHOLD", "40"))         # GO alert floor (of 55)
APLUS_THRESHOLD     = int(os.getenv("SCALP_APLUS_THRESHOLD", "48"))      # A+ alert floor
DEDUP_MINUTES       = int(os.getenv("SCALP_DEDUP_MINUTES", "90"))        # suppress re-alert window
MAX_CANDIDATES      = int(os.getenv("SCALP_MAX_CANDIDATES", "15"))       # top-N by mentions per run

SKIP_IF_PRICE_ABOVE = float(os.getenv("SCALP_SKIP_IF_PRICE_ABOVE", "50.0"))   # $ — above → route to portfolio
SKIP_IF_FLOAT_ABOVE = float(os.getenv("SCALP_SKIP_IF_FLOAT_ABOVE", "200"))    # millions of shares

PORTFOLIO_ROUTE_TAGS = {"retirement_income", "dividend_growth"}

CATALYST_KEYWORDS = [
    "fda", "approval", "earnings", "beat", "m&a", "merger", "acquisition",
    "partnership", "contract", "deal", "upgrade", "buyout", "8-k", "patent",
    "phase", "trial", "breakthrough", "guidance", "raised",
]


def fetch_finviz_base(symbols: list[str]) -> dict[str, dict]:
    """
    Fetch base data (price, change%, volume) from Finviz Elite view 111.
    The enrichment module skips price/change_pct/volume (SKIP_DUPLICATES),
    so we fetch them directly here.
    """
    token = os.getenv("FINVIZ_API_TOKEN", "").strip()
    cookie = os.getenv("FINVIZ_COOKIE", "").strip()
    ua = os.getenv("FINVIZ_USER_AGENT", "Mozilla/5.0")

    results: dict[str, dict] = {}
    batch_size = 20

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        ticker_str = ",".join(batch)

        if token:
            url = f"https://elite.finviz.com/export?v=111&t={ticker_str}&auth={token}"
            headers = {"User-Agent": ua}
        elif cookie:
            url = f"https://elite.finviz.com/export?v=111&t={ticker_str}"
            headers = {"User-Agent": ua, "Cookie": cookie, "Referer": "https://elite.finviz.com/"}
        else:
            logger.error("No Finviz auth configured")
            return results

        try:
            # finviz_get publishes a GLOBAL cooldown on 429; the retry then
            # waits on the shared throttle rather than sleeping locally.
            resp = finviz_get(url, headers=headers, timeout=20, raise_on_429=False)
            if resp.status_code == 429:
                logger.warning("Finviz 429 — global cooldown set, retrying")
                resp = finviz_get(url, headers=headers, timeout=20, raise_on_429=False)
            if not resp.ok:
                logger.warning("Finviz v=111 HTTP %d", resp.status_code)
                continue

            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                sym = (row.get("Ticker") or "").upper()
                if not sym:
                    continue
                price_raw = (row.get("Price") or "").strip()
                change_raw = (row.get("Change") or "").replace("%", "").strip()
                vol_raw = (row.get("Volume") or "").replace(",", "").strip()
                try:
                    price = float(price_raw) if price_raw else None
                except ValueError:
                    price = None
                try:
                    change = float(change_raw) if change_raw else None
                except ValueError:
                    change = None
                try:
                    volume = int(vol_raw) if vol_raw else None
                except ValueError:
                    volume = None
                results[sym] = {"price": price, "change_pct": change, "volume": volume}
        except Exception as e:
            logger.error("Finviz base fetch error: %s", e)

        time.sleep(0.5)

    return results


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_social_candidates(conn) -> list[dict]:
    """
    Aggregate ticker mentions from social_posts in last LOOKBACK_HOURS.
    Returns list of {symbol, mention_count, sources, bull, bear, strategy_tags, sample_content}
    sorted by mention_count desc.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    cur.execute(
        """
        SELECT platform, symbols_mentioned, sentiment, text, post_date, strategy_tags
        FROM social_posts
        WHERE post_date > %s
          AND symbols_mentioned IS NOT NULL
          AND jsonb_array_length(symbols_mentioned) > 0
        ORDER BY post_date DESC
        """,
        [cutoff],
    )

    posts = cur.fetchall()
    if not posts:
        logger.info("No social posts with ticker mentions in last %dh", LOOKBACK_HOURS)
        return []

    ticker_data: dict[str, dict] = {}
    for post in posts:
        symbols = post["symbols_mentioned"]
        if isinstance(symbols, str):
            symbols = json.loads(symbols)

        for sym in symbols:
            sym = sym.upper().strip()
            # Skip non-equity symbols (crypto .X, too long, non-alpha)
            if not sym or len(sym) > 5 or not sym.isalpha():
                continue
            if sym not in ticker_data:
                ticker_data[sym] = {
                    "symbol": sym,
                    "mention_count": 0,
                    "sources": set(),
                    "bull": 0,
                    "bear": 0,
                    "strategy_tags": set(),
                    "sample_content": (post.get("text") or "")[:200],
                }
            ticker_data[sym]["mention_count"] += 1
            ticker_data[sym]["sources"].add(post.get("platform", "unknown"))
            stags = post.get("strategy_tags") or []
            if isinstance(stags, str):
                stags = json.loads(stags)
            for t in stags:
                ticker_data[sym]["strategy_tags"].add(t)
            sent = (post.get("sentiment") or "").lower()
            if sent == "bullish":
                ticker_data[sym]["bull"] += 1
            elif sent == "bearish":
                ticker_data[sym]["bear"] += 1

    candidates = [
        {**v, "sources": list(v["sources"]), "strategy_tags": list(v["strategy_tags"])}
        for v in ticker_data.values()
        if v["mention_count"] >= MIN_MENTIONS
    ]
    candidates.sort(key=lambda x: x["mention_count"], reverse=True)
    return candidates[:MAX_CANDIDATES]


def already_alerted(conn, symbol: str) -> bool:
    """Check if we've already fired a GO/A+ alert for this symbol within DEDUP_MINUTES."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM scalp_scan_results
        WHERE symbol = %s
          AND score >= %s
          AND scanned_at > NOW() - make_interval(mins => %s)
        LIMIT 1
        """,
        [symbol, GO_THRESHOLD, DEDUP_MINUTES],
    )
    return cur.fetchone() is not None


def build_catalyst_enrichment(conn, symbol: str, sample_content: str) -> dict:
    """
    Build an enrichment dict compatible with scoring.py's score_ticker().
    Checks social content keywords + news_articles for catalyst data.
    """
    content_lower = sample_content.lower()
    keyword_hits = sum(1 for k in CATALYST_KEYWORDS if k in content_lower)

    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT title, summary, published_at
        FROM news_articles
        WHERE symbol = %s AND published_at > NOW() - INTERVAL '18 hours'
        ORDER BY published_at DESC
        LIMIT 5
        """,
        [symbol],
    )
    news = cur.fetchall()
    news_count = len(news)

    # Determine catalyst tier
    if keyword_hits >= 2 or news_count >= 3:
        tier = "high_impact"
    elif keyword_hits >= 1 or news_count >= 1:
        tier = "medium_impact"
    else:
        tier = "none"

    catalysts = []
    top_catalyst = None
    for n in news:
        age_hours = 0
        if n.get("published_at"):
            age_hours = (datetime.now(timezone.utc) - n["published_at"]).total_seconds() / 3600
        cat = {
            "title": n.get("title", ""),
            "summary": n.get("summary", ""),
            "hours_old": round(age_hours, 1),
            "recency_multiplier": max(0.5, 1.0 - (age_hours / 48)),
        }
        catalysts.append(cat)
        if top_catalyst is None:
            top_catalyst = cat

    return {
        "catalyst_tier": tier,
        "catalyst_count": news_count + keyword_hits,
        "has_fresh_catalyst": any(c["hours_old"] < 6 for c in catalysts) if catalysts else keyword_hits > 0,
        "top_catalyst": top_catalyst,
        "catalysts": catalysts,
    }


_HERMES_CATALYST_CACHE = {"path": None, "mtime": 0.0, "data": {}}


def load_hermes_catalysts() -> dict:
    """Load the latest Hermes momentum-catalyst research (data/hermes/momentum_catalysts/*_catalysts.jsonl),
    indexed by UPPER(symbol). Hermes researches catalysts via SearXNG (advisory-only); wiring it here lets a
    Hermes-confirmed catalyst satisfy the social-only cap so genuine setups can reach GO. mtime-cached."""
    import glob as _glob
    try:
        files = sorted(_glob.glob(str(ROOT / "data" / "hermes" / "momentum_catalysts" / "*_catalysts.jsonl")))
        if not files:
            return {}
        latest = files[-1]
        mt = os.path.getmtime(latest)
        if latest == _HERMES_CATALYST_CACHE["path"] and mt == _HERMES_CATALYST_CACHE["mtime"]:
            return _HERMES_CATALYST_CACHE["data"]
        data = {}
        with open(latest) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    sym = str(r.get("symbol", "")).upper()
                    if sym:
                        data[sym] = r
                except Exception:
                    continue
        _HERMES_CATALYST_CACHE.update({"path": latest, "mtime": mt, "data": data})
        return data
    except Exception:
        return {}


def hermes_catalyst_for(symbol: str) -> dict | None:
    """Return a Hermes-confirmed catalyst record for `symbol` if it clears the credibility bar
    (strength high/medium with ≥2 corroborating sources), else None."""
    rec = load_hermes_catalysts().get(str(symbol or "").upper())
    if not rec:
        return None
    strength = str(rec.get("catalyst_strength", "")).lower()
    if strength in ("high", "medium") and int(rec.get("source_count") or 0) >= 2:
        return rec
    return None


def route_to_portfolio_agents(conn, symbol: str, mention_count: int, strategy_tags: list):
    """Retirement/income/ETF tickers → agent queue instead of scalp pipeline."""
    cur = conn.cursor()
    job_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO watchlist_agent_jobs
            (id, symbol, requested_agent, request_type, priority, status, submitted_from, payload, created_at)
        VALUES (%s, %s, 'maria', 'social_discovery', 5, 'queued', 'social_scalp_scanner', %s, NOW())
        ON CONFLICT DO NOTHING
        """,
        [
            job_id,
            symbol,
            json.dumps({
                "mention_count": mention_count,
                "strategy_tags": strategy_tags,
                "source": "social_discovery",
                "note": f"Social mentions: {mention_count}x — routed to portfolio agents (not scalp)",
            }),
        ],
    )
    conn.commit()
    logger.info("Routed %s to portfolio agents (%d mentions)", symbol, mention_count)


def ensure_results_table(conn):
    """Create scalp_scan_results table if it doesn't exist."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS scalp_scan_results (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            scanned_at TIMESTAMPTZ DEFAULT NOW(),
            mention_count INTEGER,
            score INTEGER,
            grade TEXT,
            decision TEXT,
            rvol NUMERIC,
            volume BIGINT,
            gap_pct NUMERIC,
            price NUMERIC,
            float_mm NUMERIC,
            change_pct NUMERIC,
            sector TEXT,
            sources TEXT[],
            alerted BOOLEAN DEFAULT false
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scalp_scan_symbol_time
        ON scalp_scan_results(symbol, scanned_at DESC)
        """
    )
    conn.commit()


def apply_social_only_cap(decision: str, grade: str, catalyst_enrichment: dict):
    """P0-2: cap an unverified social-only setup. A social surge with no credible catalyst
    (news / SEC / analyst / RAG- or Hermes-confirmed) can never be GO or A+/A — it is downgraded
    to WAIT / B. Pure and DB-free. Returns (decision, grade, capped: bool).

    NOTE (2026-07-08 fix): this previously read `catalyst_verified`/`catalyst`/`catalyst_source`,
    which build_catalyst_enrichment never sets — so verified/has_news were ALWAYS False and EVERY
    GO/A+ was silently capped to WAIT (scalp GO went to 0 on 07-01). Read the keys the enrichment
    actually produces: `catalysts` (news_articles rows found for the symbol) → has_news;
    `rag_catalyst_confirmed` / `hermes_catalyst_confirmed` → verified."""
    ce = catalyst_enrichment or {}
    verified = bool(ce.get("catalyst_verified") or ce.get("rag_catalyst_confirmed")
                    or ce.get("hermes_catalyst_confirmed"))
    # Credible catalyst articles were actually found for this symbol (news_articles / Hermes),
    # not merely social keyword hits.
    has_news = bool(ce.get("catalysts")) or ce.get("catalyst_tier") in ("high_impact", "medium_impact")
    if not verified and not has_news and (decision == "GO" or grade in ("A+", "A")):
        return "WAIT", ("B" if grade in ("A+", "A") else grade), True
    return decision, grade, False


def alert_action_for(decision: str, grade: str = None) -> str:
    """P0-2: which alert a FINAL (post-cap) decision warrants. Only a final GO fires the
    GO-style scalp alert (and proposals-channel mirror); WAIT fires the soft wait alert;
    everything else (AVOID) is store-only. Returns 'GO' | 'WAIT' | 'NONE'.

    Alerting MUST key off this final decision, never the raw score — a capped social-only
    WAIT with a high raw score must not look like an actionable GO."""
    d = (decision or "").strip().upper()
    if d == "GO":
        return "GO"
    if d == "WAIT":
        return "WAIT"
    return "NONE"


# ── P0-6: end-to-end discovery traceability ────────────────────────────────────────────
import hashlib as _hashlib
import uuid as _uuid
from datetime import datetime as _dt_trace, timezone as _tz_trace

_TRACE_COL_CACHE: dict = {}


def gen_discovery_trace_id(symbol: str) -> str:
    """Stable, unique per-candidate discovery trace id: soc-YYYYMMDD-SYMBOL-<rand8>.
    Threaded scan → scalp_scan_results → trade_ai_scans → proposal → paper trade."""
    day = _dt_trace.now(_tz_trace.utc).strftime("%Y%m%d")
    return f"soc-{day}-{(symbol or 'NA').upper()}-{_uuid.uuid4().hex[:8]}"


def discovery_source_meta(candidate: dict, catalyst_enrichment: dict, route: dict | None = None) -> dict:
    """Source metadata for a social candidate — platforms, mention count, a content HASH (not
    raw text), catalyst evidence source, route decision, final decision. Privacy-safe."""
    candidate = candidate or {}
    ce = catalyst_enrichment or {}
    sample = str(candidate.get("sample_content") or "")
    return {
        "source_platforms": candidate.get("sources") or [],
        "mention_count": candidate.get("mention_count"),
        "sample_content_sha256": _hashlib.sha256(sample.encode("utf-8")).hexdigest()[:16] if sample else None,
        "catalyst_evidence_source": ce.get("catalyst_source"),
        "catalyst_verified": bool(ce.get("catalyst_verified") or ce.get("rag_catalyst_confirmed")),
        "route": (route or {}).get("route"),
        "route_actionability": (route or {}).get("actionability"),
        "route_reason_codes": (route or {}).get("reason_codes"),
    }


def _has_trace_col(conn, table: str) -> bool:
    """Cached check: does `table` have a discovery_trace_id column? (backward-compatible writes)."""
    if table in _TRACE_COL_CACHE:
        return _TRACE_COL_CACHE[table]
    has = False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM information_schema.columns "
                    "WHERE table_name=%s AND column_name='discovery_trace_id'", (table,))
        has = cur.fetchone() is not None
    except Exception:
        has = False
    _TRACE_COL_CACHE[table] = has
    return has


def stamp_discovery_trace(conn, table: str, symbol: str, trace_id: str) -> None:
    """Set discovery_trace_id on the just-written row for `symbol` IF the column exists.
    No-op (safe) when the column is missing — preserves backward compatibility."""
    if not trace_id or not _has_trace_col(conn, table):
        return
    try:
        cur = conn.cursor()
        if table == "scalp_scan_results":
            cur.execute("""UPDATE scalp_scan_results SET discovery_trace_id=%s
                           WHERE id=(SELECT id FROM scalp_scan_results WHERE symbol=%s
                                     ORDER BY scanned_at DESC LIMIT 1)
                             AND discovery_trace_id IS NULL""", (trace_id, symbol))
        elif table == "trade_ai_scans":
            cur.execute("""UPDATE trade_ai_scans SET discovery_trace_id=%s
                           WHERE symbol=%s AND run_date=CURRENT_DATE
                             AND discovery_trace_id IS NULL""", (trace_id, symbol))
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug("discovery_trace stamp skipped (%s/%s): %s", table, symbol, e)


def _has_col(conn, table: str, col: str) -> bool:
    key = f"{table}.{col}"
    if key in _TRACE_COL_CACHE:
        return _TRACE_COL_CACHE[key]
    has = False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                    (table, col))
        has = cur.fetchone() is not None
    except Exception:
        has = False
    _TRACE_COL_CACHE[key] = has
    return has


def stamp_route_fields(conn, table: str, symbol: str, route: dict, catalyst_enrichment: dict = None) -> None:
    """P0-3: persist durable route/actionability fields on the just-written row IF columns exist.
    No-op (safe, logged) when columns are missing — backward-compatible. Privacy-safe: no raw text."""
    import json as _json
    if not route or not _has_col(conn, table, "route"):
        return
    ce = catalyst_enrichment or {}
    try:
        cur = conn.cursor()
        sets = ["route=%s", "route_actionability=%s", "route_strategy_id=%s", "route_reason_codes=%s"]
        vals = [route.get("route"), route.get("actionability"), route.get("strategy_id"),
                _json.dumps(route.get("reason_codes") or [])]
        if table == "scalp_scan_results":
            if _has_col(conn, table, "catalyst_verified"):
                sets.append("catalyst_verified=%s"); vals.append(bool(ce.get("catalyst_verified")
                            or ce.get("rag_catalyst_confirmed") or ce.get("hermes_catalyst_confirmed")))
            if _has_col(conn, table, "catalyst_source"):
                sets.append("catalyst_source=%s")
                vals.append(ce.get("catalyst_source") or ("hermes" if ce.get("hermes_catalyst_confirmed")
                            else ("rag" if ce.get("rag_catalyst_confirmed") else ("news" if ce.get("catalysts") else None))))
            cur.execute(f"""UPDATE scalp_scan_results SET {', '.join(sets)}
                            WHERE id=(SELECT id FROM scalp_scan_results WHERE symbol=%s
                                      ORDER BY scanned_at DESC LIMIT 1)""", vals + [symbol])
        elif table == "trade_ai_scans":
            cur.execute(f"""UPDATE trade_ai_scans SET {', '.join(sets)}
                            WHERE symbol=%s AND run_date=CURRENT_DATE""", vals + [symbol])
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug("route stamp skipped (%s/%s): %s", table, symbol, e)


def stamp_scout_fields(conn, table: str, symbol: str, route: dict) -> None:
    """P0-3: persist Social Scout operator-awareness metadata on the just-written row IF columns
    exist. No-op (safe, logged) when columns are missing — backward-compatible. Privacy-safe: only
    derived pillar metadata + the operator pill are stored, never raw social-post text.

    HARD invariant mirrored into storage: a persisted Social Scout row is ALWAYS not_tradeable +
    not_validation_ready. The pill is awareness only and can never flip a row tradeable."""
    import json as _json
    if not route or not _has_col(conn, table, "scout_status"):
        return
    try:
        cur = conn.cursor()
        sets = ["scout_status=%s", "scout_pillar_count=%s", "scout_pillars_met=%s",
                "scout_pillars_missing=%s", "operator_pill=%s", "operator_subtitle=%s",
                "operator_color_token=%s", "not_validation_ready=%s", "not_tradeable=%s"]
        vals = [route.get("scout_status"), route.get("scout_pillar_count"),
                _json.dumps(route.get("pillars_met") or []),
                _json.dumps(route.get("pillars_missing") or []),
                route.get("operator_pill"), route.get("operator_subtitle"),
                route.get("operator_color_token"),
                bool(route.get("not_validation_ready", True)),
                bool(route.get("not_tradeable", True))]
        if table == "scalp_scan_results":
            cur.execute(f"""UPDATE scalp_scan_results SET {', '.join(sets)}
                            WHERE id=(SELECT id FROM scalp_scan_results WHERE symbol=%s
                                      ORDER BY scanned_at DESC LIMIT 1)""", vals + [symbol])
        elif table == "trade_ai_scans":
            cur.execute(f"""UPDATE trade_ai_scans SET {', '.join(sets)}
                            WHERE symbol=%s AND run_date=CURRENT_DATE""", vals + [symbol])
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug("scout stamp skipped (%s/%s): %s", table, symbol, e)


def save_scan_result(conn, symbol: str, mention_count: int, finviz_data: dict,
                     score: int, grade: str, decision: str, sources: list):
    """Store result in scalp_scan_results."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO scalp_scan_results
            (symbol, mention_count, score, grade, decision, rvol, volume, gap_pct,
             price, float_mm, change_pct, sector, sources, alerted, scanned_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        [
            symbol, mention_count, score, grade, decision,
            finviz_data.get("rvol"),
            finviz_data.get("volume_base") or finviz_data.get("volume"),
            finviz_data.get("gap_pct"),
            finviz_data.get("price"),
            finviz_data.get("float_m"),
            finviz_data.get("change_pct"),
            finviz_data.get("sector"),
            sources,
            decision == "GO",   # P0-2: alerted reflects the FINAL capped decision, not raw score
        ],
    )
    conn.commit()


def _upsert_trade_ai_scans(conn, symbol: str, mention_count: int, finviz_data: dict,
                           score: int, grade: str, decision: str, sources: list):
    """Upsert social scan result into trade_ai_scans for pipeline harmonization."""
    from datetime import datetime
    cur = conn.cursor()
    run_date = datetime.now().date()
    run_id = f"social_{run_date.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M')}"
    try:
        cur.execute("""
            INSERT INTO trade_ai_scans (
                run_id, run_date, run_label, run_type,
                symbol, score, grade, decision,
                price, rvol, float_m, volume,
                gap_pct, change_pct, sector,
                social_reddit, social_stocktwits, social_score,
                social_sentiment,
                mention_count, social_sources,
                source, scanned_at
            ) VALUES (
                %s, %s, 'Social Scalp', 'social',
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s,
                %s, %s,
                'social', NOW()
            )
            ON CONFLICT (symbol, run_date)
            DO UPDATE SET
                social_reddit = EXCLUDED.social_reddit,
                social_stocktwits = EXCLUDED.social_stocktwits,
                social_score = EXCLUDED.social_score,
                social_sentiment = EXCLUDED.social_sentiment,
                mention_count = EXCLUDED.mention_count,
                social_sources = EXCLUDED.social_sources,
                score = CASE
                    WHEN EXCLUDED.score > trade_ai_scans.score
                    THEN EXCLUDED.score ELSE trade_ai_scans.score END,
                decision = CASE
                    WHEN EXCLUDED.score > trade_ai_scans.score
                    THEN EXCLUDED.decision ELSE trade_ai_scans.decision END,
                source = CASE
                    WHEN trade_ai_scans.source IS NULL OR trade_ai_scans.source = ''
                    THEN 'social'
                    WHEN trade_ai_scans.source LIKE '%%social%%'
                    THEN trade_ai_scans.source
                    ELSE trade_ai_scans.source || '+social' END
        """, [
            run_id, run_date,
            symbol, score, grade, decision,
            finviz_data.get("price"), finviz_data.get("rvol"),
            finviz_data.get("float_m"), finviz_data.get("volume_base") or finviz_data.get("volume"),
            finviz_data.get("gap_pct"), finviz_data.get("change_pct"),
            finviz_data.get("sector"),
            sum(1 for s in sources if s == 'reddit'),
            sum(1 for s in sources if s == 'stocktwits'),
            min(mention_count / 10.0, 1.0),
            'bullish' if score >= 40 else 'neutral',
            mention_count, sources,
        ])
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"trade_ai_scans upsert failed for {symbol}: {e}")


def send_scalp_alert(symbol: str, score: int, grade: str, decision: str,
                     finviz_data: dict, mention_count: int, sources: list,
                     bull: int, bear: int):
    """Send GO or A+ Telegram alert."""
    grade_emoji = "\U0001f525 A+" if grade == "A+" else "\u2705 GO"
    bull_bear = ""
    if bull or bear:
        bull_bear = f" | \U0001f7e2{bull} \U0001f534{bear}"

    rvol = finviz_data.get("rvol") or 0
    gap = finviz_data.get("gap_pct") or 0
    price = finviz_data.get("price") or 0
    float_m = finviz_data.get("float_m") or 0
    vol = finviz_data.get("volume_base") or finviz_data.get("volume") or 0
    sector = finviz_data.get("sector") or "?"
    try:
        from lib.scalp_alert_format import format_scalp_meta_line
        meta = format_scalp_meta_line(
            source="social",
            source_detail=", ".join(str(s) for s in (sources or [])[:2]),
            country=finviz_data.get("country") or "",
            symbol=symbol,
        )
    except Exception:
        meta = f"💬 Social {', '.join(str(s) for s in (sources or [])[:2])}".strip()

    vol_str = f"{int(vol):,}" if vol else "?"

    msg = (
        f"{grade_emoji} *{symbol}* — Social Scalp Setup\n"
        f"{meta}\n"
        f"Score: {score}/55 | RVOL: {rvol:.1f}x | "
        f"Gap: {gap:.1f}% | Price: ${price:.2f}\n"
        f"Float: {float_m:.1f}M | Vol: {vol_str}\n"
        f"Mentions: {mention_count}x ({', '.join(sources)}){bull_bear}\n"
        f"Sector: {sector}\n"
        f"Decision: {decision}"
    )
    send_telegram(msg)
    try:
        from lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="ops",
            producer="social_scalp_scanner", subject_key=f"scalp:{symbol}",
            retention_class="operational", severity="info",
            sanitized_body=msg[:500], short_summary=msg[:120],
        ))
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def _send_wait_alert(symbol: str, score: int, finviz_data: dict, mention_count: int):
    """WAIT tier — watching but not acting. Softer tone, no setup details."""
    rvol = finviz_data.get("rvol") or 0
    price = finviz_data.get("price") or 0
    try:
        from lib.scalp_alert_format import format_scalp_meta_line
        meta = format_scalp_meta_line(
            source="social",
            source_detail="mention",
            country=finviz_data.get("country") or "",
            symbol=symbol,
        )
    except Exception:
        meta = "💬 Social"
    msg = (
        f"\U0001f440 WAIT *{symbol}* \u2014 Social Mention\n"
        f"{meta}\n"
        f"Score: {score}/55 | RVOL: {rvol:.1f}x | "
        f"Price: ${price:.2f}\n"
        f"Mentions: {mention_count}x \u2014 watching, not acting\n"
        f"Needs: higher RVOL or catalyst to reach GO"
    )
    send_telegram(msg)


def run_scan():
    conn = get_db()
    logger.info("=== Social Scalp Scan starting ===")

    ensure_results_table(conn)

    candidates = get_social_candidates(conn)
    if not candidates:
        logger.info("No candidates — exiting")
        conn.close()
        return

    logger.info("Candidates: %d tickers from social posts", len(candidates))

    # Collect symbols that pass initial filters for batch Finviz enrichment
    symbols_to_enrich = []
    symbol_candidates = {}
    for candidate in candidates:
        symbol = candidate["symbol"]
        strategy_tags = candidate.get("strategy_tags", [])

        # Route retirement/income tickers to portfolio agents
        if any(t in PORTFOLIO_ROUTE_TAGS for t in strategy_tags):
            route_to_portfolio_agents(conn, symbol, candidate["mention_count"], strategy_tags)
            continue

        # Skip if already alerted recently
        if already_alerted(conn, symbol):
            logger.info("SKIP %s — already alerted within %d min", symbol, DEDUP_MINUTES)
            continue

        symbols_to_enrich.append(symbol)
        symbol_candidates[symbol] = candidate

    if not symbols_to_enrich:
        logger.info("No symbols to enrich after filters — exiting")
        conn.close()
        return

    # Fetch base price/change/volume (not in enrichment module's output)
    logger.info("Fetching base data for %d symbols", len(symbols_to_enrich))
    base_data = fetch_finviz_base(symbols_to_enrich)

    # Batch Finviz enrichment — adds rvol, float, gap, RSI, etc.
    logger.info("Enriching %d symbols via Finviz", len(symbols_to_enrich))
    enriched = enrich_tickers(symbols_to_enrich, project_root=str(ROOT))

    weights = _load_weights(str(ROOT))
    go_count = 0

    for symbol in symbols_to_enrich:
        candidate = symbol_candidates[symbol]
        mention_count = candidate["mention_count"]
        strategy_tags = candidate.get("strategy_tags", [])

        # Merge base data (price/change/volume) with enrichment (rvol/float/gap/etc.)
        finviz_data = {**enriched.get(symbol, {}), **base_data.get(symbol, {})}
        if not finviz_data.get("price"):
            logger.info("SKIP %s — no Finviz data", symbol)
            continue

        price = float(finviz_data.get("price") or 999)
        float_m = float(finviz_data.get("float_m") or 999)

        # Scalp filters — route large/expensive tickers to portfolio agents
        if price > SKIP_IF_PRICE_ABOVE:
            logger.info("SKIP %s — price $%.2f > $%.0f (route to portfolio)", symbol, price, SKIP_IF_PRICE_ABOVE)
            route_to_portfolio_agents(conn, symbol, mention_count, strategy_tags)
            continue

        if float_m > SKIP_IF_FLOAT_ABOVE:
            logger.info("SKIP %s — float %.0fM > %.0fM (route to portfolio)", symbol, float_m, SKIP_IF_FLOAT_ABOVE)
            route_to_portfolio_agents(conn, symbol, mention_count, strategy_tags)
            continue

        # Build ticker_row in the format scoring.py expects
        ticker_row = {
            "symbol": symbol,
            "price": finviz_data.get("price", 0),
            "change_percent": finviz_data.get("change_pct", 0),
            "gap_percent": finviz_data.get("gap_pct", 0),
            "relative_volume": finviz_data.get("rvol", 0),
            "float_m": finviz_data.get("float_m", 0),
            "float_shares": 0,  # float_m is already in millions
            "sector": finviz_data.get("sector", ""),
            "company": finviz_data.get("company", ""),
            "volume": finviz_data.get("volume_base") or finviz_data.get("volume", 0),
            "avg_volume": finviz_data.get("avg_vol_m", 0),
            "sector_momentum_score": 0,  # not available in this pipeline
        }

        # Build catalyst enrichment from social content + news
        catalyst_enrichment = build_catalyst_enrichment(
            conn, symbol, candidate.get("sample_content", "")
        )

        # RAG catalyst confirmation — check if intelligence library has supporting evidence
        try:
            from rag_retrieval import get_rag_context
            rag_items = get_rag_context(symbol, limit=3, conn=conn)
            catalyst_evidence = [r for r in rag_items if any(
                kw in str(r.get("title", "")).lower()
                for kw in ("catalyst", "fda", "earnings", "upgrade", "contract", "merger")
            )]
            if catalyst_evidence:
                catalyst_enrichment["rag_catalyst_confirmed"] = True
                catalyst_enrichment["rag_evidence"] = catalyst_evidence[0].get("title", "")[:200]
        except Exception as e:
            logger.debug(f"RAG check failed for {symbol}: {e}")

        # Hermes catalyst research (SearXNG, advisory) — a credible Hermes-confirmed catalyst satisfies
        # the social-only cap so the setup can reach GO instead of being downgraded to WAIT.
        try:
            _hc = hermes_catalyst_for(symbol)
            if _hc:
                catalyst_enrichment["hermes_catalyst_confirmed"] = True
                catalyst_enrichment["catalyst_source"] = "hermes"
                catalyst_enrichment["hermes_catalyst"] = {
                    "type": _hc.get("catalyst_type"), "strength": _hc.get("catalyst_strength"),
                    "summary": str(_hc.get("catalyst_summary", ""))[:200],
                    "sources": _hc.get("source_count"), "confidence": _hc.get("confidence")}
                logger.info(f"[SCALP] {symbol} — Hermes catalyst confirmed: "
                            f"{_hc.get('catalyst_type')} ({_hc.get('source_count')} sources)")
        except Exception as e:
            logger.debug(f"Hermes catalyst check failed for {symbol}: {e}")

        # Scar factor — penalize symbols with poor past scalp outcomes
        try:
            scur = conn.cursor()
            scur.execute("""
                SELECT count(*) as total,
                       count(*) FILTER (WHERE outcome_status IN ('loss_5pct','loss_10pct')) as losses
                FROM scalp_decision_outcomes
                WHERE symbol = %s AND scored_at > NOW() - INTERVAL '90 days'
            """, (symbol,))
            srow = scur.fetchone()
            if srow and srow[0] >= 3:
                loss_rate = srow[1] / srow[0]
                catalyst_enrichment["scar_factor"] = max(0.5, 1.0 - (loss_rate * 0.5))
        except Exception as e:
            logger.debug(f"Scar factor check failed for {symbol}: {e}")

        # Score using the 6-pillar engine
        score_result = score_ticker(ticker_row, catalyst_enrichment, weights, use_llm=False)
        score = score_result.get("score", 0)
        grade = score_result.get("grade", "D")
        decision = score_result.get("decision", "AVOID")

        # Social-only catalyst cap (P0-2): an unverified social surge can never be GO/A+ —
        # downgraded to WAIT/B unless confirmed by a credible source (SEC/news/analyst/RAG).
        _raw_decision, _raw_grade = decision, grade
        decision, grade, _capped = apply_social_only_cap(decision, grade, catalyst_enrichment)
        if _capped:
            logger.info("%s — SOCIAL_ONLY_CATALYST cap: %s/%s → %s/%s (no confirmed catalyst)",
                        symbol, _raw_grade, _raw_decision, grade, decision)

        # P0-6: stable per-candidate discovery trace id (scan → row → proposal → trade).
        discovery_trace_id = gen_discovery_trace_id(symbol)

        # P0-5: explicit, deterministic routing to the correct strategy family.
        _route_candidate = {
            "symbol": symbol, "mention_count": mention_count,
            "sources": candidate.get("sources", []), "strategy_tags": strategy_tags,
            "sample_content": candidate.get("sample_content"),
            "bull": candidate.get("bull", 0), "bear": candidate.get("bear", 0),
        }
        route = route_social_candidate(_route_candidate, finviz_data, catalyst_enrichment,
                                       trace_id=discovery_trace_id)
        # Surface the social-only catalyst cap explicitly so the operator/UI can see a
        # GO/A+ was downgraded for lack of a verified catalyst (rather than a silent cap).
        # The route policy already emits SOCIAL_ONLY_UNVERIFIED; this adds the cap marker
        # that distinguishes "capped after scoring GO" from a plain watch-only candidate.
        if _capped:
            _rc = route.setdefault("reason_codes", [])
            if "SOCIAL_ONLY_CATALYST_CAP" not in _rc:
                _rc.append("SOCIAL_ONLY_CATALYST_CAP")
        logger.info("%s — route=%s actionability=%s reasons=%s trace=%s",
                    symbol, route["route"], route["actionability"],
                    ",".join(route["reason_codes"]), discovery_trace_id)

        logger.info(
            "%s — score %d (%s/%s) | RVOL %.1fx | mentions %d",
            symbol, score, grade, decision,
            float(finviz_data.get("rvol") or 0), mention_count,
        )

        save_scan_result(
            conn, symbol, mention_count, finviz_data,
            score, grade, decision, candidate["sources"],
        )
        stamp_discovery_trace(conn, "scalp_scan_results", symbol, discovery_trace_id)
        stamp_route_fields(conn, "scalp_scan_results", symbol, route, catalyst_enrichment)
        stamp_scout_fields(conn, "scalp_scan_results", symbol, route)

        # Harmonize: also upsert into trade_ai_scans
        _upsert_trade_ai_scans(
            conn, symbol, mention_count, finviz_data,
            score, grade, decision, candidate["sources"],
        )
        stamp_discovery_trace(conn, "trade_ai_scans", symbol, discovery_trace_id)
        stamp_route_fields(conn, "trade_ai_scans", symbol, route, catalyst_enrichment)
        stamp_scout_fields(conn, "trade_ai_scans", symbol, route)

        # === IER WRITE-BACK (non-fatal) ===
        try:
            from intelligence_entity_manager import upsert_entity as _iem_upsert
            from datetime import datetime as _dt, timezone as _tz
            _iem_upsert(conn, symbol, 'market', {
                'social_mentions': mention_count,
                'social_sources': candidate.get("sources", []),
                'social_sentiment': 'bullish' if candidate.get("bull", 0) > candidate.get("bear", 0) else 'bearish',
                'social_updated': _dt.now(_tz.utc),
                'screener_score': score,
                'screener_decision': decision,
            }, source='social_scalp')
        except Exception:
            pass
        # === END WRITE-BACK ===

        # Live WS broadcast — non-fatal
        try:
            broadcast_scalp_update({
                "symbol": symbol,
                "grade": grade,
                "score": score,
                "decision": decision,
                "change_percent": str(finviz_data.get("change_pct", "")),
                "rvol": float(finviz_data.get("rvol") or 0),
                "catalyst_verified": bool(route["evidence"].get("catalyst_verified")),
                "source": "social",
                "mention_count": mention_count,
                "route": route["route"],
                "actionability": route["actionability"],
                # Social Scout operator-awareness fields (P0-5) — surfaced live so the UI can render
                # the pill without recomputing pillars. Awareness only: never tradeable/validation.
                "scout_status": route.get("scout_status"),
                "scout_pillar_count": route.get("scout_pillar_count"),
                "scout_pillars_met": route.get("pillars_met"),
                "scout_pillars_missing": route.get("pillars_missing"),
                "operator_pill": route.get("operator_pill"),
                "operator_subtitle": route.get("operator_subtitle"),
                "operator_color_token": route.get("operator_color_token"),
                "operator_tooltip_hints": route.get("operator_tooltip_hints"),
                "not_validation_ready": route.get("not_validation_ready"),
                "not_tradeable": route.get("not_tradeable"),
                "discovery_trace_id": discovery_trace_id,
            })
        except Exception as e:
            logger.warning("WS broadcast skipped for %s: %s", symbol, e)

        # P0-2 + P0-5: alerting keys off the FINAL capped decision, NOT the raw score, AND the
        # route's actionability is authoritative. A social-only / watch_only / manual-review route
        # can NEVER fire a GO-style alert or mirror to the proposals channel, even if the score is high.
        _action = alert_action_for(decision, grade)
        if _action == "GO" and route["actionability"] != "GO":
            logger.info("%s — GO alert suppressed: route=%s actionability=%s (not auto-tradeable)",
                        symbol, route["route"], route["actionability"])
            _action = "WAIT"
        if _action == "GO":
            send_scalp_alert(
                symbol, score, grade, decision, finviz_data,
                mention_count, candidate["sources"],
                candidate.get("bull", 0), candidate.get("bear", 0),
            )
            go_count += 1
        elif _action == "WAIT":
            # WAIT — softer notification, no trade action, no proposals-channel mirror
            _send_wait_alert(symbol, score, finviz_data, mention_count)
        # AVOID — stored only, no alert. Dashboard reads scalp_scan_results to show the AVOID list.

    logger.info("=== Scan complete: %d GO/A+ alerts fired ===", go_count)
    conn.close()


if __name__ == "__main__":
    run_scan()
