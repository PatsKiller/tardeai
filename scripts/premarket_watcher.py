"""
premarket_watcher.py — Pre-Market Catalyst Watcher
Runs every 15 min 5:30-9:30 AM weekdays. Watches for overnight catalysts
on known GO/WAIT symbols. Sends Telegram alerts on discovery.
"""
import json, logging, os, sys, time, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2, requests

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _load_env():
    for line in (PROJECT_ROOT / '.env').read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()

_load_env()

DB_CONFIG = dict(host='127.0.0.1', port=5432, dbname='trade_ai', user='trade_ai',
                 password=os.getenv('DB_PASSWORD', ''))


def get_watch_symbols(conn, limit=50):
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT symbol, MAX(score) as best
        FROM trade_ai_scans WHERE decision IN ('GO','WAIT')
        AND scanned_at > NOW() - INTERVAL '30 days'
        GROUP BY symbol ORDER BY best DESC LIMIT %s
    """, [limit])
    return [r[0] for r in cur.fetchall()]


def _insert_news_article(cur, title, url, symbol, source, quality):
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


def check_edgar_overnight(symbol, conn, dry_run=False):
    findings = []
    try:
        cutoff = (datetime.now() - timedelta(hours=18)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        resp = requests.get('https://efts.sec.gov/LATEST/search-index', params={
            'q': symbol, 'dateRange': 'custom', 'startdt': cutoff, 'enddt': today,
            'forms': '8-K,S-1,S-3,424B1,424B3,424B5',
        }, headers={'User-Agent': 'TradeAI/1.0 (john@jwwhiting.com)'}, timeout=8)
        if resp.status_code != 200:
            return []
        hits = resp.json().get('hits', {}).get('hits', [])
        if not hits:
            return []
        cur = conn.cursor() if not dry_run else None
        for hit in hits[:3]:
            src = hit.get('_source', {})
            form_type = src.get('form_type', '8-K')
            filed = src.get('file_date', today)
            title = f"{symbol} {form_type} Filed Pre-Market: {filed}"
            findings.append({'symbol': symbol, 'title': title, 'type': form_type, 'source': 'sec_edgar'})
            if not dry_run and cur:
                url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&type={form_type}"
                try:
                    _insert_news_article(cur, title, url, symbol, 'sec_edgar_premarket', 88)
                except Exception:
                    conn.rollback()
        if not dry_run and findings:
            conn.commit()
        return findings
    except Exception:
        return []


def check_stocktwits_premarket(symbol, conn, dry_run=False):
    try:
        resp = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json",
                           timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            return {}
        data = resp.json()
        messages = data.get('messages', [])
        now = datetime.now(timezone.utc)
        recent = [m for m in messages if _msg_recent(m, now, hours=2)]
        is_surging = len(recent) >= 3

        # Count sentiment
        bullish = sum(1 for m in recent if (m.get('entities', {}).get('sentiment', {}).get('basic') == 'Bullish'))
        bearish = sum(1 for m in recent if (m.get('entities', {}).get('sentiment', {}).get('basic') == 'Bearish'))
        total = len(recent)

        result = {
            'symbol': symbol,
            'recent_count': total,
            'is_surging': is_surging,
            'bullish': bullish,
            'bearish': bearish,
            'bullish_pct': round(bullish / total * 100, 1) if total > 0 else 0,
        }

        result["_messages"] = recent
        return result
    except Exception:
        return {}


def _persist_stocktwits_premarket(conn, symbol, result, messages, *, catalyst: str = ""):
    """Persist StockTwits pre-market data to social_posts and trade_ai_scans.

    Rows are tagged SOCIAL_AWARENESS (not tradeable) until Finviz enrichment runs.
    """
    try:
        from lib.social_awareness import awareness_fields, build_catalyst_text
    except Exception:
        from social_awareness import awareness_fields, build_catalyst_text
    cur = conn.cursor()
    total = result['recent_count']
    bullish = result.get('bullish', 0)
    bearish = result.get('bearish', 0)
    bullish_pct = result.get('bullish_pct', 0)

    # 1. Persist individual messages to social_posts (deduped by post_id)
    for msg in messages[:10]:  # cap at 10 per symbol per scan
        msg_id = f"st_{msg.get('id', '')}"
        body = msg.get('body', '')[:500]
        username = msg.get('user', {}).get('username', '')
        sentiment_raw = msg.get('entities', {}).get('sentiment', {}).get('basic', 'Neutral')
        sentiment_map = {'Bullish': 'bullish', 'Bearish': 'bearish'}
        sentiment = sentiment_map.get(sentiment_raw, 'neutral')
        created = msg.get('created_at', '')

        try:
            cur.execute("""
                INSERT INTO social_posts
                    (platform, post_id, username, text, sentiment, quality_score,
                     post_date, symbols_mentioned, strategy_tags, added_by)
                VALUES ('stocktwits', %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, 'premarket_watcher')
                ON CONFLICT (platform, post_id) DO NOTHING
            """, [
                msg_id, username, body, sentiment,
                70 if sentiment != 'neutral' else 50,
                created[:19] if created else datetime.now().isoformat(),
                json.dumps([symbol]), json.dumps(['premarket_social']),
            ])
        except Exception:
            pass

    # 2. Upsert surge data into trade_ai_scans (makes it visible on /v3/trading)
    run_date = datetime.now().date()
    run_id = f"premarket_{run_date.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M')}"
    sentiment_label = 'Very Bullish' if bullish_pct >= 70 else ('Bullish' if bullish_pct >= 55 else ('Bearish' if bearish > bullish else 'Neutral'))
    st_body = ""
    if messages:
        st_body = (messages[0].get("body") or "")[:200]
    cat_text = build_catalyst_text(
        news_title=catalyst,
        stocktwits_body=st_body,
        mention_count=total,
    )
    aware = awareness_fields(catalyst=cat_text, mention_count=total, source_detail="stocktwits_premarket")
    # Social awareness only — never promote to GO without Finviz enrichment.
    score = min(total * 3, 50)
    grade = 'B+' if total >= 10 else ('B' if total >= 5 else 'C')

    try:
        cur.execute("""
            INSERT INTO trade_ai_scans (
                run_id, run_date, run_label, run_type,
                symbol, score, grade, decision,
                social_stocktwits, social_score, social_sentiment,
                social_bullish_pct, mention_count, social_sources,
                catalyst, catalyst_verified, catalyst_source,
                awareness_status, setup_class,
                not_tradeable, not_validation_ready, manual_review_required,
                operator_pill, operator_subtitle, operator_color_token,
                source, scanned_at
            ) VALUES (
                %s, %s, 'Pre-Market StockTwits', 'premarket_social',
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                'premarket_social', NOW()
            )
            ON CONFLICT (symbol, run_date)
            DO UPDATE SET
                social_stocktwits = GREATEST(COALESCE(trade_ai_scans.social_stocktwits, 0), EXCLUDED.social_stocktwits),
                social_score = GREATEST(COALESCE(trade_ai_scans.social_score, 0), EXCLUDED.social_score),
                social_sentiment = CASE
                    WHEN EXCLUDED.social_stocktwits > COALESCE(trade_ai_scans.social_stocktwits, 0)
                    THEN EXCLUDED.social_sentiment
                    ELSE COALESCE(trade_ai_scans.social_sentiment, EXCLUDED.social_sentiment) END,
                social_bullish_pct = CASE
                    WHEN EXCLUDED.social_stocktwits > COALESCE(trade_ai_scans.social_stocktwits, 0)
                    THEN EXCLUDED.social_bullish_pct
                    ELSE COALESCE(trade_ai_scans.social_bullish_pct, EXCLUDED.social_bullish_pct) END,
                mention_count = GREATEST(COALESCE(trade_ai_scans.mention_count, 0), EXCLUDED.mention_count),
                catalyst = CASE
                    WHEN COALESCE(trade_ai_scans.catalyst, '') = '' THEN EXCLUDED.catalyst
                    WHEN EXCLUDED.social_stocktwits > COALESCE(trade_ai_scans.social_stocktwits, 0)
                    THEN EXCLUDED.catalyst
                    ELSE trade_ai_scans.catalyst END,
                catalyst_verified = EXCLUDED.catalyst_verified,
                catalyst_source = EXCLUDED.catalyst_source,
                awareness_status = EXCLUDED.awareness_status,
                setup_class = EXCLUDED.setup_class,
                not_tradeable = EXCLUDED.not_tradeable,
                not_validation_ready = EXCLUDED.not_validation_ready,
                operator_pill = EXCLUDED.operator_pill,
                operator_subtitle = EXCLUDED.operator_subtitle,
                operator_color_token = EXCLUDED.operator_color_token,
                decision = CASE
                    WHEN COALESCE(trade_ai_scans.price, 0) > 0 OR COALESCE(trade_ai_scans.rvol, 0) > 0
                    THEN trade_ai_scans.decision
                    ELSE EXCLUDED.decision END,
                source = CASE
                    WHEN trade_ai_scans.source IS NULL OR trade_ai_scans.source = ''
                    THEN 'premarket_social'
                    WHEN trade_ai_scans.source LIKE '%%premarket%%'
                    THEN trade_ai_scans.source
                    ELSE trade_ai_scans.source || '+premarket_social' END
        """, [
            run_id, run_date,
            symbol,
            score,
            grade,
            aware["decision"],
            total,
            min(total / 30.0, 1.0),
            sentiment_label,
            bullish_pct,
            total,
            ['stocktwits'],
            aware["catalyst"],
            aware["catalyst_verified"],
            aware["catalyst_source"],
            aware["awareness_status"],
            aware["setup_class"],
            aware["not_tradeable"],
            aware["not_validation_ready"],
            aware["manual_review_required"],
            aware["operator_pill"],
            aware["operator_subtitle"],
            aware["operator_color_token"],
        ])
    except Exception as e:
        log.warning(f"trade_ai_scans upsert failed for {symbol}: {e}")
        conn.rollback()
        return

    # 3. Upsert into scalp_scan_results for source attribution on dashboard
    try:
        cur.execute("""
            INSERT INTO scalp_scan_results
                (symbol, mention_count, score, grade, decision, sources, alerted, scanned_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, [
            symbol, total,
            min(total * 3, 50),
            'B+' if total >= 10 else ('B' if total >= 5 else 'C'),
            aware["decision"],
            ['stocktwits_premarket'],
            result.get('is_surging', False),
        ])
    except Exception:
        pass

    # Backfill float from internal data. This watcher is StockTwits-based and has
    # no fundamentals of its own, so every row it wrote had float_m NULL. Float is
    # a HARD scalp gate (micro-float <=20M), so a premarket mention without it
    # cannot be evaluated against the rule at all — and the missing values were
    # being misreported as a screener data-quality fault (2026-07-20).
    # Internal join only: no extra Finviz load.
    try:
        cur.execute("""UPDATE trade_ai_scans s
                       SET float_m = w.float_m
                       FROM watchlist_items w
                       WHERE upper(w.symbol) = upper(s.symbol)
                         AND s.symbol = %s
                         AND (s.float_m IS NULL OR s.float_m = 0)
                         AND w.float_m IS NOT NULL AND w.float_m > 0""", (symbol,))
    except Exception as _fe:
        log.warning(f"float backfill failed for {symbol}: {type(_fe).__name__}: {_fe}")

    try:
        conn.commit()
        log.info(f"Persisted StockTwits pre-market: {symbol} ({total} posts, {sentiment_label})")
    except Exception:
        conn.rollback()


def _msg_recent(msg, now, hours=2):
    try:
        created = msg.get('created_at', '')
        if created:
            t = datetime.fromisoformat(created.replace('Z', '+00:00'))
            return (now - t).total_seconds() < hours * 3600
    except Exception:
        pass
    return False


def check_news_rss(symbol, conn, dry_run=False):
    findings = []
    try:
        resp = requests.get(f"https://finance.yahoo.com/rss/headline?s={symbol}",
                           headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
            cur = conn.cursor() if not dry_run else None
            for item in root.findall('.//item')[:3]:
                title = (item.findtext('title') or '').strip()
                link = (item.findtext('link') or '').strip()
                if title and link:
                    findings.append({'symbol': symbol, 'title': title, 'source': 'yahoo_rss'})
                    if not dry_run and cur:
                        try:
                            _insert_news_article(cur, title, link, symbol, 'yahoo_premarket', 65)
                        except Exception:
                            conn.rollback()
            if not dry_run and findings:
                conn.commit()
    except Exception:
        pass
    return findings


def run_premarket_scan(symbols, conn, dry_run=False):
    all_findings = {}
    alerts = []
    for symbol in symbols:
        edgar = check_edgar_overnight(symbol, conn, dry_run)
        time.sleep(0.3)
        social = check_stocktwits_premarket(symbol, conn, dry_run)
        time.sleep(0.3)
        news = check_news_rss(symbol, conn, dry_run)

        if edgar or (social and social.get('recent_count', 0) > 0) or news:
            all_findings[symbol] = {'edgar': edgar, 'social': social, 'news': news}

        if not dry_run and social and social.get('recent_count', 0) > 0:
            catalyst = ""
            if news:
                catalyst = (news[0].get("title") or "")[:200]
            elif edgar:
                catalyst = (edgar[0].get("title") or "")[:200]
            _persist_stocktwits_premarket(
                conn, symbol, social, social.get("_messages") or [],
                catalyst=catalyst,
            )

        if edgar or (social and social.get('is_surging')):
            parts = [f"PRE-MARKET: {symbol}"]
            for f in edgar:
                parts.append(f"  SEC {f['type']}: {f['title'][:60]}")
            if social and social.get('is_surging'):
                parts.append(f"  StockTwits: {social['recent_count']} posts/2hr")
            alerts.append('\n'.join(parts))

        time.sleep(0.5)

    return {'findings': all_findings, 'alerts': alerts,
            'symbols_checked': len(symbols), 'symbols_with_activity': len(all_findings)}


def send_telegram(message):
    """Route through central alert router (no raw Bot API fallback)."""
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram as _central_send
        _central_send(message)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="premarket_watcher", subject_key="ops:premarket",
                retention_class="operational", severity="info",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception as e:
        log.warning(f"telegram send failed: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbols', help='Comma-separated symbols')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        symbols = [s.strip().upper() for s in args.symbols.split(',')] if args.symbols else get_watch_symbols(conn)
        log.info(f"Pre-market scan: {len(symbols)} symbols")

        results = run_premarket_scan(symbols, conn, dry_run=args.dry_run)

        print(f"\n=== PRE-MARKET SCAN ===")
        print(f"Checked: {results['symbols_checked']} | Activity: {results['symbols_with_activity']}")
        for sym, f in results['findings'].items():
            print(f"  {sym}: edgar={len(f['edgar'])} social_surge={f['social'].get('is_surging',False)} news={len(f['news'])}")

        if not args.dry_run and results['alerts']:
            header = f"PRE-MARKET CATALYST ({datetime.now().strftime('%H:%M')})"
            msg = header + '\n\n' + '\n\n'.join(results['alerts'])
            send_telegram(msg)
    finally:
        conn.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                       handlers=[logging.FileHandler(str(PROJECT_ROOT/'logs/premarket_watcher.log')),
                                 logging.StreamHandler()])
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('premarket_watcher')
    except Exception:
        pass
    try:
        main()
        try:
            if _run_id: run_complete(_run_id)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
