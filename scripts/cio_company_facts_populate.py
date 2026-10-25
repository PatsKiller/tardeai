#!/usr/bin/env python3
"""Confirmed-security company facts in existing CIO memory; dry-run by default.

--apply is an operator/state-write action (plus db-write when PG dual-write is
already authorized). n8n uses this same apply path only after reviewed admission.
No schema migration, scheduler activation, provider or sender lives in this CLI.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT/'scripts'):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
from scripts.lib import cio_company_population as pop


def readonly_query():
    from scripts.session13_db import get_conn
    from psycopg2.extras import RealDictCursor
    conn = get_conn()
    conn.set_session(readonly=True, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('transaction_read_only')")
        if cur.fetchone()[0] != 'on':
            conn.close()
            raise RuntimeError('database_readonly_not_proven')
    conn.rollback()
    observations = []
    def q(sql, params=None):
        if not sql.lstrip().upper().startswith('SELECT') or ';' in sql:
            raise ValueError('readonly_select_required')
        start = datetime.now(timezone.utc).isoformat()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
            observations.append({'query_sha256': hashlib.sha256(sql.encode()).hexdigest(), 'rows': len(rows),
                                 'observed_start': start, 'observed_finish': datetime.now(timezone.utc).isoformat()})
            return rows
        finally:
            conn.rollback()
    return q, conn, observations


def write_result(root, result, start):
    from scripts.lib.atomic_json_store import atomic_write_json
    from scripts.lib import lane_last_receipt as receipt
    atomic_write_json(root/'data/runtime/cio_company_facts_populate_report_latest.json', result)
    receipt.write_lane_receipt(pop.LANE_ID, ok=result['ok'], exit_code=0 if result['ok'] else 1,
                              started_at=start, script='scripts/cio_company_facts_populate.py',
                              path=root/pop.RECEIPT_REL, produced_count=result.get('produced_count', 0),
                              attempted_count=result.get('target_count', 0),
                              output_evidence=[{'kind': 'file', 'path': 'data/runtime/cio_company_facts_populate_report_latest.json'}],
                              empty_reason=result.get('reason') if not result.get('produced_count') else None,
                              summary={
                                  'produced_count': result.get('produced_count', 0),
                                  **{k: result.get(k) for k in ('reason', 'created', 'updated', 'unchanged', 'gaps', 'identity_gaps', 'pg_sync', 'quality_status')},
                                  'watch_coverage': (result.get('after') or {}).get('my_watchlist'),
                                  'catalyst_sources': result.get('catalyst_sources'),
                                  'judgment_writes': 0, 'prospect_promotions': 0})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    inp = ap.add_mutually_exclusive_group(required=True)
    inp.add_argument('--input-capture', type=Path)
    inp.add_argument('--with-db', action='store_true')
    ap.add_argument('--state-root', type=Path, required=True)
    ap.add_argument('--now', help='pinned aware fixture clock')
    args = ap.parse_args(argv)
    start = datetime.now(timezone.utc)
    now = datetime.fromisoformat(args.now.replace('Z','+00:00')) if args.now else start
    if now.tzinfo is None: ap.error('--now requires a timezone')
    conn = None
    try:
        if args.input_capture:
            raw = args.input_capture.read_bytes()
            capture = json.loads(raw)
            capture['input_sha256'] = hashlib.sha256(raw).hexdigest()
        else:
            q, conn, observations = readonly_query()
            capture = pop.capture_readonly_inputs(args.state_root, q, now=now)
            capture['sources'] = observations
        backend = None
        if args.apply:
            from scripts.lib.cio_instrument_record import ProspectPgBackend
            from scripts.session13_db import get_conn
            backend = ProspectPgBackend(get_conn)  # lazy; flag-off makes no PG connection
        result = pop.populate(args.state_root, capture, apply=args.apply, now=now, backend=backend)
        produced = result['created'] + result['updated'] + result['unchanged'] if args.apply else result['would_create'] + result['would_update'] + result['unchanged']
        result['produced_count'] = produced
        if not produced:
            result.update(ok=False, reason='empty_output')
        if args.apply:
            # Latest-only files: bounded retention; immutable source observations
            # and canonical history stay on their existing owner stores.
            write_result(args.state_root, result, start)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result['ok'] and produced else 1
    except Exception as exc:
        # Never echo connection strings, SQL values or credential-bearing errors.
        result = {'ok': False, 'reason': type(exc).__name__, 'mode': 'apply' if args.apply else 'dry_run', 'produced_count': 0}
        if args.apply:
            try:
                write_result(args.state_root, result, start)
            except Exception as receipt_exc:
                result['receipt_status'] = 'NOT_WRITTEN'
                result['receipt_error'] = type(receipt_exc).__name__
        print(json.dumps(result))
        return 1
    finally:
        if conn: conn.rollback(); conn.close()


if __name__ == '__main__': raise SystemExit(main())
