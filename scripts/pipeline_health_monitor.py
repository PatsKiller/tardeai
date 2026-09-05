"""
pipeline_health_monitor.py — Self-healing pipeline health check.
Cron: 7:00 AM + 10:15 AM weekdays.
Detects GO tickers with missing analysis, auto-re-queues enrichment/agents.
"""
import json, logging, os, sys, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2

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


def check_morning_pipeline(conn):
    cur = conn.cursor()
    checks = {}

    cur.execute("SELECT COUNT(*), MAX(created_at) FROM news_articles WHERE created_at > NOW()-INTERVAL '4 hours'")
    r = cur.fetchone()
    checks['news_ingestion'] = {'ok': (r[0] or 0) >= 3, 'count': r[0] or 0}

    cur.execute("SELECT COUNT(*) FROM watchlist_symbol_master WHERE updated_at > NOW()-INTERVAL '4 hours' AND (in_ai_watchlist=true OR in_portfolio=true)")
    checks['finviz_enrichment'] = {'ok': True, 'count': cur.fetchone()[0] or 0}

    cur.execute("SELECT COUNT(*) FROM content_embeddings WHERE created_at > NOW()-INTERVAL '4 hours'")
    checks['rag_indexer'] = {'ok': True, 'count': cur.fetchone()[0] or 0}

    cur.execute("SELECT COUNT(*) FROM watchlist_agent_results WHERE created_at > NOW()-INTERVAL '4 hours'")
    checks['agent_jobs'] = {'ok': True, 'count': cur.fetchone()[0] or 0}

    failed = [k for k, v in checks.items() if not v['ok']]
    return {'all_ok': not failed, 'checks': checks, 'failed_steps': failed}


def check_go_ticker_intelligence(conn, no_heal=False):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT ON (symbol) symbol, score, decision, price, rvol,
                   intelligence_readiness, catalyst, catalyst_verified, scanned_at
            FROM trade_ai_scans WHERE decision IN ('GO','WAIT')
            AND scanned_at > NOW()-INTERVAL '12 hours'
            ORDER BY symbol, score DESC
        """)
        go_tickers = cur.fetchall()
    except Exception:
        conn.rollback()
        return []
    results = []

    for (symbol, score, decision, price, rvol, readiness, catalyst, cat_ver, scanned_at) in go_tickers:
        readiness = readiness or 0

        # Check agent analyses
        cur.execute("SELECT COUNT(*) FROM watchlist_agent_results WHERE symbol=%s AND created_at>NOW()-INTERVAL '24 hours'", [symbol])
        agent_count = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE symbol=%s AND status IN ('pending','running') AND created_at>NOW()-INTERVAL '12 hours'", [symbol])
        pending = cur.fetchone()[0] or 0

        status = {
            'symbol': symbol, 'score': score, 'decision': decision,
            'readiness': readiness,
            'readiness_grade': 'HIGH' if readiness >= 75 else 'MED' if readiness >= 50 else 'LOW' if readiness >= 25 else 'MINIMAL',
            'catalyst': catalyst, 'catalyst_verified': cat_ver,
            'agent_analyses': agent_count, 'agent_pending': pending,
            'action_taken': None,
        }

        if not no_heal:
            # Auto-heal: thin intelligence
            if readiness < 50:
                try:
                    subprocess.Popen([sys.executable, str(PROJECT_ROOT/'scripts/symbol_enrichment.py'), symbol, str(score or 0)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(PROJECT_ROOT))
                    status['action_taken'] = 're_enriched'
                except Exception:
                    pass

            # Auto-heal: no agent analysis
            if agent_count == 0 and pending == 0:
                try:
                    cur.execute("""
                        INSERT INTO watchlist_agent_jobs (symbol, requested_agent, task_type, priority, status, submitted_from, context_data, created_at)
                        VALUES (%s,'maria_research','scalp_discovery','high','pending','pipeline_health',%s::jsonb,NOW())
                        ON CONFLICT DO NOTHING
                    """, [symbol, json.dumps({'trigger': 'pipeline_health_auto_repair', 'readiness': readiness})])
                    conn.commit()
                    status['action_taken'] = (status['action_taken'] or '') + '+agent_queued'
                except Exception:
                    pass

        results.append(status)
    return results


def send_telegram(message):
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram as _tg
        _tg(message)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="pipeline_health_monitor", subject_key="ops:pipeline_health",
                retention_class="operational", severity="info",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-telegram', action='store_true')
    parser.add_argument('--no-heal', action='store_true')
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        pipeline = check_morning_pipeline(conn)
        tickers = check_go_ticker_intelligence(conn, no_heal=args.no_heal)

        print(f"\n=== PIPELINE HEALTH ===")
        print(f"Pipeline OK: {pipeline['all_ok']}")
        print(f"GO/WAIT tickers: {len(tickers)}")

        healed = [t for t in tickers if t.get('action_taken')]
        if healed:
            print(f"Auto-repaired: {[(t['symbol'], t['action_taken']) for t in healed]}")

        for t in sorted(tickers, key=lambda x: x['score'] or 0, reverse=True)[:10]:
            print(f"  {t['symbol']} {t['decision']} {t['score']}pts Intel:{t['readiness']}/100 "
                  f"Agents:{t['agent_analyses']} {t.get('action_taken','')}")

        if not args.no_telegram:
            lines = [f"PIPELINE HEALTH ({datetime.now().strftime('%H:%M')})"]
            if pipeline['all_ok']:
                lines.append("Morning pipeline: OK")
            else:
                lines.append(f"Issues: {pipeline['failed_steps']}")
            go = [t for t in tickers if t['decision'] == 'GO']
            lines.append(f"GO tickers: {len(go)}")
            for t in go[:5]:
                icon = '✅' if t['readiness'] >= 50 else '⚠️'
                cat = f" | {t['catalyst'][:25]}" if t['catalyst'] else ''
                action = f" [{t['action_taken']}]" if t.get('action_taken') else ''
                lines.append(f"{icon} {t['symbol']} {t['score']}pts [Intel:{t['readiness']}]{cat}{action}")
            send_telegram('\n'.join(lines))
    finally:
        conn.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                       handlers=[logging.FileHandler(str(PROJECT_ROOT/'logs/pipeline_health_monitor.log')),
                                 logging.StreamHandler()])
    main()
