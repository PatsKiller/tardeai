"""
symbol_enrichment.py
Trade AI v12 — Multi-Source Symbol Enrichment Engine

Tiered enrichment for any symbol that surfaces as GO/WAIT:
  Tier 1: Finviz Elite (primary — 70+ columns)
  Tier 2: Free on-demand (Yahoo RSS, Google News, StockTwits, Reddit, Finnhub, SEC)
  Tier 3: YouTube Intelligence (auto-discover channels)
  Tier 4: Keyed APIs (Alpha Vantage, Polygon — when Tier 2 thin)
  Tier 5: Brave Search (A+ only, max 3/day)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    """Load .env vars into os.environ if not already set."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()


_load_env()


# ─────────────────────────────────────────────
# TIER 1 — FINVIZ ELITE (primary data source)
# Uses same URL/auth pattern as finviz_enrichment.py
# ─────────────────────────────────────────────

FINVIZ_EXPORT = "https://elite.finviz.com/export"

def fetch_finviz_deep(symbol: str) -> Optional[dict]:
    """
    Fetch all views from Finviz Elite for a single symbol.
    Returns merged dict with technicals, fundamentals, ownership.
    """
    try:
        token = os.getenv('FINVIZ_API_TOKEN', '').strip()
        cookie = os.getenv('FINVIZ_COOKIE', '').strip()
        ua = os.getenv('FINVIZ_USER_AGENT',
                       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

        if not token and not cookie:
            log.error("[enrichment] No Finviz auth (need FINVIZ_API_TOKEN or FINVIZ_COOKIE)")
            return None

        # View definitions matching finviz_enrichment.py exactly
        views = {
            111: {1: "ticker", 2: "company", 3: "sector", 4: "industry",
                  5: "country", 6: "market_cap_b", 7: "pe",
                  8: "volume_base", 9: "price", 10: "change_pct"},
            131: {1: "ticker", 4: "float_m", 7: "inst_own_pct",
                  9: "short_float_pct", 10: "short_ratio",
                  11: "avg_vol_m", 12: "price"},
            141: {1: "ticker", 10: "recom", 12: "rvol", 13: "price"},
            171: {1: "ticker", 2: "beta", 3: "atr",
                  4: "sma20_pct", 5: "sma50_pct", 6: "sma200_pct",
                  7: "week52_high_pct", 8: "week52_low_pct",
                  9: "rsi", 10: "price", 11: "change_pct",
                  12: "change_from_open_pct", 13: "gap_pct", 14: "volume"},
            121: {1: "ticker", 3: "pe2", 4: "forward_pe", 5: "peg",
                  10: "eps_ttm", 18: "price2"},
        }

        merged = {'symbol': symbol, 'source': 'finviz_elite'}
        pct_fields = {"change_pct", "sma20_pct", "sma50_pct", "sma200_pct",
                      "week52_high_pct", "week52_low_pct", "change_from_open_pct",
                      "gap_pct", "short_float_pct", "inst_own_pct"}

        for view, col_map in views.items():
            if token:
                url = f"{FINVIZ_EXPORT}?v={view}&t={symbol}&auth={token}"
                headers = {"User-Agent": ua}
            else:
                url = f"{FINVIZ_EXPORT}?v={view}&t={symbol}"
                headers = {"User-Agent": ua, "Cookie": cookie,
                           "Referer": "https://elite.finviz.com/"}

            try:
                resp = finviz_get(url, headers=headers, timeout=15, raise_on_429=False)
                if not resp.ok:
                    continue

                lines = resp.text.strip().split("\n")
                if len(lines) < 2:
                    continue

                # Parse CSV — header row + data row
                parts = [p.strip().strip('"') for p in lines[1].split(",")]

                for idx, field in col_map.items():
                    if idx >= len(parts):
                        continue
                    val = parts[idx].strip()
                    if not val or val == '-':
                        continue

                    # Skip duplicate fields from secondary views
                    if field in merged and field not in ('ticker',):
                        continue

                    # Parse value
                    if field in pct_fields:
                        try:
                            merged[field] = float(val.replace('%', ''))
                        except ValueError:
                            pass
                    elif field in ('price', 'price2', 'atr', 'beta', 'rvol',
                                   'float_m', 'avg_vol_m', 'market_cap_b',
                                   'recom', 'rsi', 'eps_ttm', 'forward_pe',
                                   'pe', 'pe2', 'peg', 'short_ratio'):
                        try:
                            merged[field] = float(val.replace(',', '')
                                                  .replace('B', 'e9')
                                                  .replace('M', 'e6')
                                                  .replace('K', 'e3'))
                        except ValueError:
                            pass
                    elif field in ('volume', 'volume_base'):
                        try:
                            merged[field] = int(val.replace(',', ''))
                        except ValueError:
                            pass
                    else:
                        merged[field] = val

                time.sleep(0.3)  # Rate limit between views
            except Exception as e:
                log.debug(f"[enrichment] Finviz view {view} failed for {symbol}: {e}")
                continue

        # Normalize output
        price = merged.get('price') or merged.get('price2')
        result = {
            'symbol': symbol,
            'source': 'finviz_elite',
            'price': price,
            'change_pct': merged.get('change_pct'),
            'gap_pct': merged.get('gap_pct'),
            'volume': merged.get('volume') or merged.get('volume_base'),
            'rvol': merged.get('rvol'),
            'market_cap_b': merged.get('market_cap_b'),
            'float_m': merged.get('float_m'),
            'short_float_pct': merged.get('short_float_pct'),
            'inst_own_pct': merged.get('inst_own_pct'),
            'pe': merged.get('pe') or merged.get('pe2'),
            'forward_pe': merged.get('forward_pe'),
            'eps_ttm': merged.get('eps_ttm'),
            'rsi': merged.get('rsi'),
            'sma20_pct': merged.get('sma20_pct'),
            'sma50_pct': merged.get('sma50_pct'),
            'sma200_pct': merged.get('sma200_pct'),
            'atr': merged.get('atr'),
            'beta': merged.get('beta'),
            'recom': merged.get('recom'),
            'sector': merged.get('sector'),
            'industry': merged.get('industry'),
            'company': merged.get('company'),
            'fetched_at': datetime.now(timezone.utc).isoformat(),
        }

        # Analyst rating interpretation
        recom = result.get('recom')
        if recom:
            if recom <= 1.5: result['analyst_rating'] = 'Strong Buy'
            elif recom <= 2.5: result['analyst_rating'] = 'Buy'
            elif recom <= 3.5: result['analyst_rating'] = 'Hold'
            elif recom <= 4.5: result['analyst_rating'] = 'Sell'
            else: result['analyst_rating'] = 'Strong Sell'

        if price:
            log.info(f"[enrichment] Finviz: {symbol} price=${price} "
                     f"RSI={result.get('rsi')} RVOL={result.get('rvol')}")

        return result if price else None

    except Exception as e:
        log.error(f"[enrichment] fetch_finviz_deep failed for {symbol}: {e}")
        return None


# ─────────────────────────────────────────────
# TIER 2 — FREE ON-DEMAND SOURCES
# ─────────────────────────────────────────────

def _report_source(key: str, ok: bool, rows=None, error=None) -> None:
    """Passive liveness ping into data_source_health (see lib/data_source_report)."""
    try:
        from lib.data_source_report import report_source
        report_source(key, ok, rows=rows, error=error)
    except Exception:
        pass


def _insert_news_article(cur, title: str, url: str, symbol: str, source: str, quality: int) -> bool:
    """Insert into news_articles using the canonical schema (source_url/relevance_score).

    Dedup matches news_ingestion.py: skip when source_url already exists.
    Returns True when a row was written.
    """
    if not url or not title:
        return False
    cur.execute("SELECT 1 FROM news_articles WHERE source_url=%s LIMIT 1", (url[:500],))
    if cur.fetchone():
        return False
    cur.execute("""INSERT INTO news_articles (symbol, title, source, source_url, relevance_score, published_at)
                   VALUES (%s, %s, %s, %s, %s, NOW())""",
                (symbol, title[:300], source, url[:500], quality))
    return True


def pull_sec_edgar(symbol: str, conn) -> int:
    """SEC EDGAR full-text search. Free, no API key. 8-K = catalyst source for micro-caps."""
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        resp = requests.get('https://efts.sec.gov/LATEST/search-index', params={
            'q': symbol, 'dateRange': 'custom', 'startdt': start_date, 'enddt': end_date,
            'forms': '8-K,S-1,S-3,424B1,424B3,424B5',
        }, headers={'User-Agent': 'TradeAI/1.0 (john@jwwhiting.com)'}, timeout=10)
        if resp.status_code != 200:
            _report_source('sec_edgar', False, error=f'HTTP {resp.status_code}')
            return 0
        _report_source('sec_edgar', True)
        hits = resp.json().get('hits', {}).get('hits', [])
        if not hits:
            return 0
        cur = conn.cursor()
        added = 0
        for hit in hits[:5]:
            src = hit.get('_source', {})
            form_type = src.get('form_type', '8-K')
            filed = src.get('file_date', '')
            if form_type == '8-K':
                title = f"{symbol} 8-K Material Event Filed: {filed}"
            elif '424' in form_type:
                title = f"{symbol} {form_type} Prospectus Filed: {filed} — dilution risk"
            else:
                title = f"{symbol} SEC {form_type}: {filed}"
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&type={form_type}"
            quality = {'8-K': 85, 'S-1': 70, 'S-3': 70}.get(form_type, 75)
            try:
                if _insert_news_article(cur, title, url, symbol, 'sec_edgar_filing', quality):
                    added += 1
            except Exception:
                conn.rollback()
        if added:
            conn.commit()
            log.info(f"[enrichment] SEC EDGAR: {added} filings for {symbol}")
        return added
    except Exception:
        return 0


def pull_yahoo_rss(symbol: str, conn) -> int:
    """Yahoo Finance RSS — per-symbol news. No key needed."""
    try:
        url = f"https://finance.yahoo.com/rss/headline?s={symbol}"
        resp = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            return 0
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        cur = conn.cursor()
        added = 0
        for item in root.findall('.//item')[:10]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            if not title or not link:
                continue
            try:
                if _insert_news_article(cur, title, link, symbol, 'yahoo_rss', 65):
                    added += 1
            except Exception:
                conn.rollback()
        conn.commit()
        return added
    except Exception:
        return 0


def pull_google_news_rss(symbol: str, conn) -> int:
    """Google News RSS — per-symbol. No key needed."""
    try:
        url = f"https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            return 0
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        cur = conn.cursor()
        added = 0
        for item in root.findall('.//item')[:8]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            if not title or not link:
                continue
            try:
                if _insert_news_article(cur, title, link, symbol, 'google_news_rss', 70):
                    added += 1
            except Exception:
                conn.rollback()
        conn.commit()
        return added
    except Exception:
        return 0


def pull_stocktwits(symbol: str, conn) -> dict:
    """StockTwits symbol stream — real-time social sentiment."""
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        resp = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            return {'mentions': 0, 'bullish': 0, 'bearish': 0}
        data = resp.json()
        messages = data.get('messages', [])
        bullish = sum(1 for m in messages
                     if m.get('entities', {}).get('sentiment', {}).get('basic') == 'Bullish')
        bearish = sum(1 for m in messages
                     if m.get('entities', {}).get('sentiment', {}).get('basic') == 'Bearish')
        return {'mentions': len(messages), 'bullish': bullish, 'bearish': bearish,
                'bullish_pct': bullish / len(messages) * 100 if messages else 0}
    except Exception:
        return {'mentions': 0, 'bullish': 0, 'bearish': 0}


def pull_finnhub_news(symbol: str, conn) -> int:
    """Finnhub company news — existing API key."""
    try:
        api_key = os.getenv('FINNHUB_API_KEY', '')
        if not api_key:
            return 0
        from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        to_date = datetime.now().strftime('%Y-%m-%d')
        url = (f"https://finnhub.io/api/v1/company-news"
               f"?symbol={symbol}&from={from_date}&to={to_date}&token={api_key}")
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            _report_source('finnhub', False, error=f'HTTP {resp.status_code}')
            return 0
        _report_source('finnhub', True)
        articles = resp.json()
        if not isinstance(articles, list):
            return 0
        cur = conn.cursor()
        added = 0
        for art in articles[:10]:
            try:
                if _insert_news_article(cur, art.get('headline') or '', art.get('url') or '',
                                        symbol, 'finnhub_live', 72):
                    added += 1
            except Exception:
                conn.rollback()
        conn.commit()
        return added
    except Exception:
        return 0


# ─────────────────────────────────────────────
# TIER 3 — YOUTUBE INTELLIGENCE
# ─────────────────────────────────────────────

def search_youtube(symbol: str, conn) -> dict:
    """Search YouTube for recent videos about this symbol. Queue transcripts."""
    result = {'videos_found': 0, 'new_channels': 0, 'queued': 0}
    try:
        api_key = os.getenv('YOUTUBE_API_KEY', '')
        if not api_key:
            return result
        published_after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
        resp = requests.get('https://www.googleapis.com/youtube/v3/search', params={
            'q': f'{symbol} stock analysis', 'type': 'video',
            'publishedAfter': published_after, 'order': 'relevance',
            'maxResults': 5, 'key': api_key, 'part': 'snippet',
            'relevanceLanguage': 'en',
        }, timeout=10)
        if resp.status_code != 200:
            _report_source('youtube_api', False, error=f'HTTP {resp.status_code}')
            return result
        _report_source('youtube_api', True)
        videos = resp.json().get('items', [])
        result['videos_found'] = len(videos)
        cur = conn.cursor()

        # Ensure backfill queue table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS youtube_backfill_queue (
                id SERIAL PRIMARY KEY, video_id TEXT UNIQUE NOT NULL,
                channel_id TEXT, symbol_trigger TEXT, priority TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'pending', created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        for video in videos:
            channel_id = video['snippet']['channelId']
            channel_name = video['snippet']['channelTitle']
            video_id = video['id']['videoId']
            # Check if known channel
            cur.execute("SELECT id FROM youtube_channels WHERE channel_id=%s LIMIT 1", [channel_id])
            if cur.fetchone():
                # Known — queue transcript
                cur.execute("SELECT id FROM youtube_transcripts WHERE video_id=%s", [video_id])
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO youtube_backfill_queue (video_id, channel_id, symbol_trigger, priority, status)
                        VALUES (%s, %s, %s, 'high', 'pending') ON CONFLICT (video_id) DO NOTHING
                    """, [video_id, channel_id, symbol])
                    result['queued'] += 1
            else:
                # Unknown — propose to Iris
                result['new_channels'] += 1
                cur.execute("""
                    SELECT id FROM iris_taxonomy_proposals
                    WHERE proposal_type='new_channel_discovery' AND target=%s LIMIT 1
                """, [channel_id])
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO iris_taxonomy_proposals (proposal_type, target, reasoning, confidence, status, created_at)
                        VALUES ('new_channel_discovery', %s, %s, 0.7, 'pending', NOW())
                    """, [channel_id, f"Channel '{channel_name}' has video about {symbol} GO signal"])

        conn.commit()
        if result['videos_found'] > 0:
            log.info(f"[enrichment] YouTube: {result['videos_found']} videos for {symbol}, "
                     f"{result['queued']} queued, {result['new_channels']} new channels")
        return result
    except Exception as e:
        log.debug(f"[enrichment] YouTube search failed for {symbol}: {e}")
        return result


# ─────────────────────────────────────────────
# TIER 5 — BRAVE SEARCH (strategic reserve)
# ─────────────────────────────────────────────

def pull_brave_aplus(symbol: str, score: int, conn) -> bool:
    """Brave Search — A+ signals only (score>=55), max 3/day."""
    if score < 55:
        return False
    try:
        brave_key = os.getenv('BRAVE_SEARCH_API_KEY', '')
        if not brave_key:
            return False
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE source='brave_search' AND created_at > NOW() - INTERVAL '24 hours'
        """)
        if cur.fetchone()[0] >= 3:
            return False
        resp = requests.get('https://api.search.brave.com/res/v1/news/search',
            headers={'Accept': 'application/json', 'X-Subscription-Token': brave_key},
            params={'q': f'{symbol} stock news', 'count': 5, 'freshness': 'pd'}, timeout=10)
        if resp.status_code in (402, 429):
            _report_source('brave_search', False, error=f'HTTP {resp.status_code} (budget/rate-limit)')
            return False
        if resp.status_code != 200:
            _report_source('brave_search', False, error=f'HTTP {resp.status_code}')
            return False
        _report_source('brave_search', True)
        results = resp.json().get('results', [])
        added = 0
        for r in results:
            try:
                if _insert_news_article(cur, r.get('title') or '', r.get('url') or '',
                                        symbol, 'brave_search', 75):
                    added += 1
            except Exception:
                conn.rollback()
        conn.commit()
        log.info(f"[enrichment] Brave A+: {added} articles for {symbol}")
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# INTELLIGENCE READINESS SCORING
# ─────────────────────────────────────────────

def compute_intelligence_readiness(symbol: str, conn) -> dict:
    """
    Score 0-100 how well-equipped agents are to analyze this ticker.
    Components: scan_data(30) + catalyst(25) + news(20) + social(15) + edgar(10)
    Bonus: agent_analyses(+20, capped at 100)
    """
    score = 0
    components = {}
    try:
        cur = conn.cursor()

        # Component 1: trade_ai_scans row (30 pts)
        cur.execute("""
            SELECT score, decision, catalyst, catalyst_verified
            FROM trade_ai_scans WHERE symbol=%s AND scanned_at > NOW()-INTERVAL '7 days'
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        scan = cur.fetchone()
        if scan:
            score += 30
            components['scan_data'] = True
            if scan[2]:  # catalyst
                score += 25 if scan[3] else 10
                components['catalyst_score'] = 25 if scan[3] else 10
            else:
                components['catalyst_score'] = 0
        else:
            components['scan_data'] = False
            components['catalyst_score'] = 0

        # Component 3: news articles last 24h (20 pts)
        cur.execute("SELECT COUNT(*) FROM news_articles WHERE symbol=%s AND created_at>NOW()-INTERVAL '24 hours'", [symbol])
        news_count = cur.fetchone()[0] or 0
        if news_count >= 3: score += 20; components['news_score'] = 20
        elif news_count >= 1: score += 10; components['news_score'] = 10
        else: components['news_score'] = 0
        components['news_count'] = news_count

        # Component 4: social (15 pts) — check trade_ai_scans social columns
        cur.execute("""
            SELECT COALESCE(social_reddit,0)+COALESCE(social_stocktwits,0)+COALESCE(mention_count,0)
            FROM trade_ai_scans WHERE symbol=%s AND scanned_at>NOW()-INTERVAL '24 hours'
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        social_row = cur.fetchone()
        social_count = social_row[0] if social_row else 0
        if social_count >= 5: score += 15; components['social_score'] = 15
        elif social_count >= 1: score += 8; components['social_score'] = 8
        else: components['social_score'] = 0
        components['social_count'] = social_count

        # Component 5: EDGAR filing (10 pts)
        cur.execute("SELECT COUNT(*) FROM news_articles WHERE symbol=%s AND source IN ('sec_edgar_filing','sec_edgar_premarket') AND created_at>NOW()-INTERVAL '7 days'", [symbol])
        edgar = cur.fetchone()[0] or 0
        if edgar >= 1: score += 10; components['edgar_score'] = 10
        else: components['edgar_score'] = 0
        components['edgar_count'] = edgar

        # Bonus: agent analyses (20 pts, cap at 100)
        cur.execute("SELECT COUNT(*) FROM watchlist_agent_results WHERE symbol=%s AND created_at>NOW()-INTERVAL '24 hours'", [symbol])
        agents = cur.fetchone()[0] or 0
        if agents >= 2: score = min(100, score + 20); components['agent_score'] = 20
        elif agents >= 1: score = min(100, score + 10); components['agent_score'] = 10
        else: components['agent_score'] = 0
        components['agent_analyses'] = agents

        score = min(100, score)
        grade = 'HIGH' if score >= 75 else 'MED' if score >= 50 else 'LOW' if score >= 25 else 'MINIMAL'
        components['score'] = score
        components['grade'] = grade

        # Write back to trade_ai_scans
        cur.execute("""
            UPDATE trade_ai_scans SET intelligence_readiness=%s, intel_components=%s::jsonb
            WHERE symbol=%s AND scanned_at=(SELECT MAX(scanned_at) FROM trade_ai_scans WHERE symbol=%s)
        """, [score, json.dumps(components), symbol, symbol])
        conn.commit()

        return components
    except Exception as e:
        log.error(f"compute_intelligence_readiness failed for {symbol}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return {'score': 0, 'grade': 'UNKNOWN'}


# ─────────────────────────────────────────────
# ORCHESTRATOR — MAIN ENTRY POINT
# ─────────────────────────────────────────────

def enrich_symbol(symbol: str, score: int, conn, force_full: bool = False) -> dict:
    """
    Main entry point. Orchestrates all enrichment tiers.
    Called from trade_ai_orchestrator on_symbol_surfaced() for GO signals.
    """
    start = time.time()
    summary = {'symbol': symbol, 'score': score, 'finviz': None,
               'articles': 0, 'social': 0, 'youtube': 0, 'sources': []}

    # Tier 1: Finviz Elite
    fv = fetch_finviz_deep(symbol)
    if fv:
        summary['finviz'] = fv
        summary['sources'].append('finviz_elite')
        # Write to IER
        try:
            from intelligence_entity_manager import upsert_entity
            upsert_entity(conn, symbol, 'market', {
                'current_price': fv.get('price'),
                'rvol': fv.get('rvol'),
                'float_m': fv.get('float_m'),
                'gap_pct': fv.get('gap_pct'),
                'change_pct': fv.get('change_pct'),
                'atr_value': fv.get('atr'),
                'sector': fv.get('sector'),
                'industry': fv.get('industry'),
                'price_updated_at': datetime.now(timezone.utc),
            }, source='symbol_enrichment')
        except Exception:
            pass

    # Tier 2: Free sources — EDGAR first (most likely catalyst source for micro-caps)
    n = pull_sec_edgar(symbol, conn)
    if n > 0: summary['articles'] += n; summary['sources'].append('sec_edgar')

    n = pull_yahoo_rss(symbol, conn)
    if n > 0: summary['articles'] += n; summary['sources'].append('yahoo_rss')

    n = pull_google_news_rss(symbol, conn)
    if n > 0: summary['articles'] += n; summary['sources'].append('google_news')

    st = pull_stocktwits(symbol, conn)
    if st['mentions'] > 0:
        summary['social'] += st['mentions']
        summary['sources'].append('stocktwits')
        try:
            from intelligence_entity_manager import upsert_entity
            upsert_entity(conn, symbol, 'market', {
                'social_mentions': st['mentions'],
                'social_sentiment': 'bullish' if st.get('bullish_pct', 0) > 55 else 'neutral',
                'social_updated': datetime.now(timezone.utc),
            }, source='stocktwits_live')
        except Exception:
            pass

    n = pull_finnhub_news(symbol, conn)
    if n > 0: summary['articles'] += n; summary['sources'].append('finnhub')

    # Tier 3: YouTube
    yt = search_youtube(symbol, conn)
    if yt['videos_found'] > 0:
        summary['youtube'] = yt['videos_found']
        summary['sources'].append('youtube')

    # Tier 5: Brave (A+ only)
    if score >= 55:
        if pull_brave_aplus(symbol, score, conn):
            summary['sources'].append('brave_aplus')

    # Compute intelligence readiness after all enrichment
    try:
        readiness = compute_intelligence_readiness(symbol, conn)
        summary['intelligence_readiness'] = readiness.get('score', 0)
        summary['intelligence_grade'] = readiness.get('grade', 'UNKNOWN')
    except Exception:
        summary['intelligence_readiness'] = 0

    summary['duration_s'] = round(time.time() - start, 2)
    log.info(f"[enrichment] {symbol} (score={score}): "
             f"{summary['articles']} articles, {summary['social']} social, "
             f"{summary['youtube']} YT | Intel:{summary.get('intelligence_readiness',0)} "
             f"| {summary['sources']} | {summary['duration_s']}s")
    return summary


if __name__ == '__main__':
    with PipelineRun("symbol_enrichment") as _run:
        import sys, psycopg2
        logging.basicConfig(level=logging.INFO)
        symbol = sys.argv[1].upper() if len(sys.argv) > 1 else 'AMD'
        score = int(sys.argv[2]) if len(sys.argv) > 2 else 45
        pw = ''
        for line in (PROJECT_ROOT / '.env').read_text().splitlines():
            if line.startswith('DB_PASSWORD='): pw = line.split('=', 1)[1].strip()
        conn = psycopg2.connect(host='127.0.0.1', port=5432, dbname='trade_ai', user='trade_ai', password=pw)
        result = enrich_symbol(symbol, score, conn, force_full=True)
        print(f"\n=== ENRICHMENT: {symbol} (score={score}) ===")
        for k, v in result.items():
            if k != 'finviz': print(f"  {k}: {v}")
        if result.get('finviz'):
            fv = result['finviz']
            print(f"  Finviz: price=${fv.get('price')} RSI={fv.get('rsi')} RVOL={fv.get('rvol')} analyst={fv.get('analyst_rating','?')}")
        conn.close()

