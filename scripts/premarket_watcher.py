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
                    cur.execute("""INSERT INTO news_articles (title, url, symbol, source, quality_score, created_at)
                        VALUES (%s, %s, %s, 'sec_edgar_premarket', 88, NOW()) ON CONFLICT (url) DO NOTHING""",
                        [title[:300], url, symbol])
                except Exception:
                    pass
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
        return {'symbol': symbol, 'recent_count': len(recent), 'is_surging': is_surging}
    except Exception:
        return {}


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
                            cur.execute("""INSERT INTO news_articles (title, url, symbol, source, quality_score, created_at)
                                VALUES (%s,%s,%s,'yahoo_premarket',65,NOW()) ON CONFLICT (url) DO NOTHING""",
                                [title[:300], link[:500], symbol])
                        except Exception:
                            pass
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

        if edgar or (social and social.get('is_surging')) or news:
            all_findings[symbol] = {'edgar': edgar, 'social': social, 'news': news}

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
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_ids = [c.strip() for c in os.getenv('TELEGRAM_CHAT_ID', '').split(',') if c.strip()]
    if not bot_token or not chat_ids:
        return
    for cid in chat_ids:
        try:
            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                         json={'chat_id': cid, 'text': message}, timeout=10)
        except Exception:
            pass


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
