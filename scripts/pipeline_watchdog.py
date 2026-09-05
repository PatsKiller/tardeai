"""
pipeline_watchdog.py — The nervous system. Runs every 5 min weekdays.
1. Detects missed/failed pipeline runs, retries critical scripts
2. Detects GO tickers with no agent analysis, auto-queues
3. Acts on stale IER entities
4. Daily summary at 8:30 AM
"""
import json, logging, os, subprocess, sys, time
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2

log = logging.getLogger(__name__)
PROJECT_ROOT = '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild'
MAX_RETRIES = 3
# Enrichment attempts per entity per week before backing off to weekly.
MAX_ENRICH_ATTEMPTS = int(os.getenv('WATCHDOG_MAX_ENRICH_ATTEMPTS', '6'))

def _load_env():
    for line in Path(PROJECT_ROOT, '.env').read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()

_load_env()

DB_CONFIG = dict(host='127.0.0.1', port=5432, dbname='trade_ai', user='trade_ai',
                 password=os.getenv('DB_PASSWORD', ''))


def send_telegram(message, urgent=False):
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram as _tg
        prefix = '🚨' if urgent else '⚠️'
        text = f"{prefix} WATCHDOG: {message}"
        _tg(text)
        try:
            root = str(Path(__file__).resolve().parents[1])
            if root not in sys.path:
                sys.path.insert(0, root)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="pipeline_watchdog", subject_key="ops:pipeline_watchdog",
                retention_class="operational",
                severity="critical" if urgent else "warning",
                sanitized_body=text[:500], short_summary=text[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def log_action(conn, action_type, target, reason, success, result=''):
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO watchdog_actions (action_type,target,reason,success,result,created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                   [action_type, target, reason, success, result[:200]])
        conn.commit()
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def was_alerted_recently(conn, target, hours=1.0):
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM watchdog_actions WHERE action_type='alert' AND target=%s AND created_at > NOW() - INTERVAL '%s hours'", [target, hours])
        return (cur.fetchone()[0] or 0) > 0
    except Exception:
        return False



def _runs_today(run_days, now) -> bool:
    """Does a cron-style day-of-week spec include today?

    Accepts '1-5', '0', '0,6', '*' (cron DOW: 0=Sunday). Unparseable or empty
    means 'every day' — the previous behaviour — so a bad value can never make a
    job invisible to the watchdog.
    """
    spec = (run_days or "*").strip()
    if spec in ("*", ""):
        return True
    dow = (now.weekday() + 1) % 7          # Python Mon=0 -> cron Sun=0
    try:
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if a <= dow <= b:
                    return True
            elif part.isdigit() and int(part) % 7 == dow:
                return True
    except (ValueError, TypeError):
        return True
    return False


# ── FUNCTION 1: Pipeline Execution Monitor ──

def check_pipeline_execution(conn):
    issues = []
    now = datetime.now()
    cur = conn.cursor()
    # run_days exists in the schema but was never read: the check simply skipped
    # Sat/Sun and treated every entry as weekday-daily. Sunday-only jobs
    # (agent_outcome_scorer, strategy_weekly_review) were therefore expected on
    # weekdays they never run — and never checked on the day they DO run
    # (2026-07-20 sweep).
    cur.execute("""SELECT script_name, display_name, expected_hour, expected_min,
        max_latency_min, min_rows, critical, command, run_days
        FROM pipeline_schedule WHERE active=true""")
    for (script, display, exp_h, exp_m, latency, min_rows, critical, command,
         run_days) in cur.fetchall():
        if exp_h is None: continue
        if not _runs_today(run_days, now): continue
        expected = now.replace(hour=exp_h, minute=exp_m, second=0, microsecond=0)
        deadline = expected + timedelta(minutes=latency)
        if now < deadline: continue  # Not yet overdue

        window_start = expected - timedelta(minutes=5)
        cur.execute("""SELECT id, status, summary FROM pipeline_runs
            WHERE pipeline_key=%s AND started_at BETWEEN %s AND NOW()
            ORDER BY started_at DESC LIMIT 1""", [script, window_start])
        run = cur.fetchone()

        if not run:
            issues.append({'script': script, 'display': display, 'issue': 'not_started',
                          'critical': critical, 'command': command})
        elif run[1] == 'failed':
            issues.append({'script': script, 'display': display, 'issue': 'failed',
                          'critical': critical, 'command': command})
    return issues


def handle_pipeline_issues(conn, issues, no_telegram=False):
    for issue in issues:
        script = issue['script']
        if not issue.get('critical'): continue

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_runs WHERE pipeline_key=%s AND run_label LIKE 'retry%%' AND started_at>NOW()-INTERVAL '24 hours'", [script])
        retries_today = cur.fetchone()[0] or 0

        if retries_today < MAX_RETRIES and issue.get('command'):
            log.info(f"[watchdog] Retrying {script} (attempt {retries_today+1})")
            try:
                from pipeline_registry import run_start, run_complete, run_fail
                rid = run_start(script, run_label=f'retry_{retries_today+1}', triggered_by='watchdog')
                result = subprocess.run(issue['command'], shell=True, timeout=300,
                                       capture_output=True, text=True, cwd=PROJECT_ROOT)
                if result.returncode == 0:
                    run_complete(rid)
                    log_action(conn, 'retry', script, issue['issue'], True, 'success')
                else:
                    run_fail(rid, result.stderr[-200:])
                    log_action(conn, 'retry', script, issue['issue'], False, result.stderr[-100:])
                    if retries_today + 1 >= MAX_RETRIES and not no_telegram:
                        if not was_alerted_recently(conn, script):
                            send_telegram(f"CRITICAL: {script} failed {MAX_RETRIES}x. Manual check needed.", urgent=True)
                            log_action(conn, 'alert', script, 'max_retries', True, '')
            except Exception as e:
                log.error(f"[watchdog] Retry failed for {script}: {e}")


# ── FUNCTION 2: GO Signal Coverage ──

def check_go_coverage(conn):
    now = datetime.now()
    if now.hour < 10 or now.hour >= 18 or now.weekday() >= 5: return 0

    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (t.symbol) t.symbol, t.score, t.decision, t.scanned_at, t.intelligence_readiness
        FROM trade_ai_scans t
        WHERE t.decision IN ('GO','WAIT') AND t.scanned_at > NOW()-INTERVAL '48 hours'
        AND NOT EXISTS (SELECT 1 FROM watchlist_agent_jobs j WHERE j.symbol=t.symbol
            AND j.created_at > t.scanned_at - INTERVAL '30 minutes'
            AND j.status IN ('pending','running','completed'))
        ORDER BY t.symbol, t.score DESC LIMIT 20
    """)
    missing = cur.fetchall()
    fixed = 0

    for (symbol, score, decision, scanned_at, readiness) in missing:
        age_h = (datetime.now(timezone.utc) - scanned_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        try:
            cur.execute("""INSERT INTO watchlist_agent_jobs
                (symbol, requested_agent, task_type, priority, status, submitted_from, context_data, created_at)
                VALUES (%s,'maria_research','scalp_discovery','high','pending','pipeline_watchdog',%s::jsonb,NOW())
                ON CONFLICT DO NOTHING""",
                [symbol, json.dumps({'score': score, 'trigger': 'watchdog_coverage', 'age_h': round(age_h, 1)})])
            conn.commit()
            fixed += 1
            log_action(conn, 'queue_agent', symbol, f'GO {score}pts {age_h:.1f}hr no analysis', True, '')

            if age_h > 4 and not was_alerted_recently(conn, f'go_{symbol}', hours=4):
                send_telegram(f"{symbol} {decision} {score}pts for {age_h:.1f}hr with 0 analyses. Queued.")
                log_action(conn, 'alert', f'go_{symbol}', f'{age_h:.1f}hr gap', True, '')
        except Exception:
            pass

    return fixed


# ── FUNCTION 3: IER Action Engine ──

def run_ier_engine(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT e.entity_id, e.entity_type, e.intelligence_score, e.iris_freshness,
               e.screener_decision
        FROM intelligence_entities e
        WHERE e.active=true
        AND (e.iris_freshness IN ('CRITICAL','STALE') OR e.intelligence_score < 25)
        AND (e.last_enriched IS NULL OR e.last_enriched < NOW()-INTERVAL '4 hours')
        -- BOUNDED RETRY (2026-07-20). Selection is score-based, but enrichment
        -- does not necessarily RAISE the score: an entity stuck at 7.0 stays
        -- below 25 forever and was re-triggered every 4h indefinitely (61 times
        -- in 14 days for the worst case, 2752 entities permanently eligible).
        -- After MAX_ENRICH_ATTEMPTS tries with no improvement, back off to one
        -- attempt per week so genuinely recoverable entities still retry while
        -- un-enrichable ones stop burning the queue.
        AND (
              (SELECT count(*) FROM watchdog_actions w
                WHERE w.action_type='trigger_enrichment' AND w.target=e.entity_id
                  AND w.created_at > NOW()-INTERVAL '7 days') < %s
              OR e.last_enriched IS NULL
              OR e.last_enriched < NOW()-INTERVAL '7 days'
            )
        ORDER BY e.intelligence_score NULLS FIRST LIMIT 15
    """, [MAX_ENRICH_ATTEMPTS])
    actions = 0
    for (eid, etype, score, freshness, decision) in cur.fetchall():
        if was_alerted_recently(conn, f'ier_{eid}', hours=4): continue

        if etype == 'market':
            try:
                subprocess.Popen([sys.executable, 'scripts/symbol_enrichment.py', eid, str(int(score or 0))],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=PROJECT_ROOT)
                cur.execute("UPDATE intelligence_entities SET last_enriched=NOW() WHERE entity_id=%s", [eid])
                conn.commit()
                log_action(conn, 'trigger_enrichment', eid, f'score={score} fresh={freshness}', True, '')
                actions += 1
            except Exception:
                pass
        elif etype == 'subject' and freshness == 'CRITICAL':
            try:
                cur.execute("""INSERT INTO watchdog_actions (action_type,target,reason,success,result,created_at)
                    VALUES ('queue_alex_refresh',%s,'subject CRITICAL',true,'queued',NOW())""", [eid])
                conn.commit()
                actions += 1
            except Exception:
                pass
    return actions


# ── MAIN ──

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-telegram', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True  # Prevent transaction state issues between functions
    try:
        # Function 1: Pipeline monitoring
        issues = check_pipeline_execution(conn)
        if issues and not args.dry_run:
            handle_pipeline_issues(conn, issues, no_telegram=args.no_telegram)
        elif issues:
            for i in issues: log.info(f"[DRY] Would handle: {i['script']} ({i['issue']})")

        # Function 2: GO coverage
        if not args.dry_run:
            fixed = check_go_coverage(conn)
            if fixed: log.info(f"[watchdog] GO coverage: fixed {fixed}")

        # Function 3: IER engine
        if not args.dry_run:
            actions = run_ier_engine(conn)
            if actions: log.info(f"[watchdog] IER: {actions} actions")

    finally:
        conn.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                       handlers=[logging.FileHandler(os.path.join(PROJECT_ROOT, 'logs/pipeline_watchdog.log')),
                                 logging.StreamHandler()])
    main()
