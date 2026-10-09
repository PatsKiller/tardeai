#!/usr/bin/env python3
"""Read-only current host/queue audit; filtered metadata, no payloads or mutations."""
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008')
OUT = Path('/tmp/tradeai-all-task-audit-20261009T131239Z')
STATE = Path('/home/johnclaw/trade-ai-releases/persistent-state')
sys.path.insert(0, str(ROOT))
from scripts.lib.scheduler_operations import collect_host, redact_command


def command(argv, timeout=20):
    try:
        run = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {'command': argv, 'exit': run.returncode, 'stdout': redact_command(run.stdout),
                'evidence_class': 'OBSERVED_HOST' if run.returncode == 0 else 'BLOCKED'}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'command': argv, 'exit': None, 'error_class': type(exc).__name__, 'evidence_class': 'BLOCKED'}


def save(name, value):
    with (OUT / name).open('x') as target:
        json.dump(value, target, indent=2, default=str)
        target.write('\n')


result = {'schema': 'AllTaskCurrentRuntimeAudit@v1', 'as_of': datetime.now(timezone.utc).isoformat(),
          'evidence_class': 'OBSERVED_HOST', 'no_runtime_mutations': True, 'no_broker_requests': True}
commands = {'date': ['date', '--iso-8601=seconds'], 'hostname': ['hostname'], 'uptime': ['uptime'],
            'disk': ['df', '-h', '/'], 'memory': ['free', '-m'],
            'docker_ps': ['docker', 'ps', '--format', '{{json .}}'],
            'compose': ['docker', 'compose', 'ls', '--format', 'json'],
            'timers': ['systemctl', '--user', 'list-timers', '--all', '--no-pager', '--plain'],
            'ports': ['ss', '-ltnpH'],
            'ollama': ['systemctl', 'show', 'ollama.service', '--property=Id,LoadState,UnitFileState,ActiveState,SubState,MainPID,ActiveEnterTimestamp']}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    pairs = pool.map(lambda item: (item[0], command(item[1])), commands.items())
    result['host'] = dict(pairs)
result['scheduler_observations'] = collect_host()
pin = Path('/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT').resolve()
result['CURRENT'] = str(pin)
result['CURRENT_SHA'] = (pin / 'GIT_SHA').read_text().strip()
result['registry_counts'] = {}
for label, location in [('served_release_source', pin), ('corrective_candidate_source', ROOT)]:
    registry = json.loads((location / 'config/lane_registry.json').read_bytes())
    active = [row for row in registry['lanes'] if row.get('state') == 'ACTIVE']
    result['registry_counts'][label] = {'evidence_class': 'SOURCE_ONLY', 'total': len(registry['lanes']),
                                     'active': len(active), 'active_by_kind': dict(Counter(row.get('scheduler', {}).get('kind', 'UNKNOWN') for row in active))}
backup_rows = []
for p in (STATE / 'backups/n8n').glob('**/*'):
    if p.is_file():
        row = {'path': str(p), 'size_bytes': p.stat().st_size,
               'mtime': datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}
        if p.suffix == '.json':
            try:
                d = json.loads(p.read_bytes())
                row['receipt'] = {k: d[k] for k in ['schema','ok','started_at','finished_at','dump_file','size_bytes','sha256','exit_code','restored','checked_at','counts_match'] if k in d}
            except (ValueError, OSError):
                row['receipt'] = {'evidence_class': 'NOT_MEASURED'}
        backup_rows.append(row)
result['backups'] = backup_rows
save('host-and-schedulers.json', result)

db = {'schema': 'CurrentQueueAndEmbeddingAudit@v1', 'as_of': datetime.now(timezone.utc).isoformat(),
      'evidence_class': 'NOT_MEASURED', 'transactions_read_only': True, 'queries': {}, 'file_queues': []}
try:
    from scripts.lib.env_bootstrap import load_env
    load_env()
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
                            dbname=os.getenv('DB_NAME','tradeai'), user=os.getenv('DB_USER','johnclaw'),
                            password=os.getenv('DB_PASS') or os.getenv('DB_PASSWORD'), connect_timeout=5)
    conn.set_session(readonly=True, autocommit=False)
    db['evidence_class'] = 'OBSERVED_DB'

    def query(name, sql):
        started = time.perf_counter()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout='5s'")
                cursor.execute(sql)
                rows = [dict(r) for r in cursor.fetchall()]
            conn.rollback()
            db['queries'][name] = {'sql': sql, 'rows': rows, 'elapsed_s': round(time.perf_counter()-started, 4)}
            return rows
        except psycopg2.Error as exc:
            conn.rollback()
            db['queries'][name] = {'sql': sql, 'evidence_class': 'BLOCKED', 'error_class': type(exc).__name__}
            return []

    query('identity', 'SELECT version(), pg_database_size(current_database()) AS size_bytes')
    columns = query('queue_columns', "SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_name ~ '(queue|outbox|wake|jobs|proposal)' ORDER BY table_schema,table_name,ordinal_position")
    tables = {}
    for row in columns:
        tables.setdefault((row['table_schema'],row['table_name']), {})[row['column_name']] = row['data_type']
    for (schema, table), cols in tables.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',schema) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',table):
            continue
        status = next((name for name in ['status','state'] if name in cols), None)
        stamp = next((name for name in ['created_at','requested_at','enqueued_at','ts'] if 'timestamp' in cols.get(name,'')), None)
        if status:
            times = f',min("{stamp}") AS oldest,max("{stamp}") AS newest' if stamp else ''
            query('queue:'+schema+'.'+table, f'SELECT "{status}" AS status,count(*) AS n{times} FROM "{schema}"."{table}" GROUP BY "{status}"')
    query('pipeline_24h_metrics', "SELECT pipeline_key,trigger_source,status,count(*) AS n,min(started_at) AS first,max(finished_at) AS last,percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds) AS p50_s,percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_seconds) AS p95_s FROM pipeline_runs WHERE started_at>NOW()-INTERVAL '1 day' GROUP BY pipeline_key,trigger_source,status")
    query('embedding_storage', "SELECT count(*) AS rows,min(created_at) AS oldest,max(created_at) AS newest,count(*) FILTER(WHERE created_at>NOW()-INTERVAL '1 day') AS writes_24h,pg_total_relation_size('content_embeddings') AS bytes FROM content_embeddings")
    query('vector_extension', "SELECT extname,extversion FROM pg_extension WHERE extname='vector'")
    query('embedding_columns', "SELECT table_schema,table_name,column_name,data_type,udt_name FROM information_schema.columns WHERE table_name IN ('content_embeddings','embedding') ORDER BY table_schema,table_name,ordinal_position")
    query('embedding_indexes', "SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE tablename IN ('content_embeddings','embedding')")
    query('native_vectors', "SELECT count(*) AS total_rows,count(*) FILTER(WHERE vec IS NOT NULL) AS vector_rows,pg_total_relation_size('intelligence.embedding') AS bytes FROM intelligence.embedding")
    conn.close()
except Exception as exc:
    db['error_class'] = type(exc).__name__
for rel in ['data/cio/hermes_research_requests.jsonl','data/cio/hermes_challenge_queue.jsonl','data/cio/agent_handoffs.jsonl','data/cio/persistent_agent_wake.jsonl','data/cio/approval_queue.jsonl','logs/claude_escalation_queue.json','data/watchlist_research_queue.json','data/runtime/hermes_embedding_queue.json']:
    p = STATE / rel
    row = {'path': rel, 'exists': p.exists(), 'evidence_class': 'NOT_MEASURED'}
    if p.is_file() and p.stat().st_size < 8*1024*1024:
        try:
            raw = p.read_text()
            entries = [json.loads(line) for line in raw.splitlines() if line.strip()] if p.suffix=='.jsonl' else json.loads(raw)
            if isinstance(entries, dict): entries=entries.get('items',entries.get('jobs',[]))
            if not isinstance(entries,list): raise ValueError()
            row.update(evidence_class='OBSERVED_HOST', record_count=len(entries), status_counts=dict(Counter(str(item.get('status') or item.get('state') or 'UNKNOWN') for item in entries if isinstance(item,dict))), mtime=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(), note='Event history counts do not prove materialized queue length or consumer health; payloads omitted.')
        except Exception as exc:
            row['error_class']=type(exc).__name__
    db['file_queues'].append(row)
save('queues-and-embeddings.json', db)
print(json.dumps({'as_of':result['as_of'],'CURRENT_SHA':result['CURRENT_SHA'],'cron_entries':len(result['scheduler_observations']['cron'].get('entries',[])),'systemd_units':len(result['scheduler_observations']['systemd'].get('units',{})),'openclaw_jobs':len(result['scheduler_observations']['openclaw'].get('jobs',[])),'db_evidence':db['evidence_class'],'queue_tables':sum(k.startswith('queue:') for k in db['queries']),'failed_queries':[k for k,v in db['queries'].items() if v.get('evidence_class')=='BLOCKED']}))
