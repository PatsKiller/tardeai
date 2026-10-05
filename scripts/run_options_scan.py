#!/usr/bin/env python3
"""Single-owner options scan worker. Default is an offline, non-mutating plan.

--apply is for the authorized runtime scheduler. Agents use injected providers/tests;
this command is never a grant to call live broker endpoints from a coding session.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NO_CONSUMER_REASON = "Standalone worker CLI; scheduled activation is NOT installed pending approved provider capacity (config/options_scan.json)."

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib.options_scan import ScanStore, due_profiles, load_config, run_slice


def collect(profile, *, engine, store, config):
    from lib.options_universe_census import build_coverage
    from lib.options_research_universe import merge_research_rows
    holdings, meta = engine._load_holdings()
    engine.SOURCE_RECEIPTS.clear()
    rows = engine._research_universe_rows()
    sources = dict(engine.SOURCE_RECEIPTS)
    observed = meta.get('_observed_at')
    sources['holdings'] = {'status': 'COMPLETE' if meta.get('_holdings_path') and observed else 'UNAVAILABLE',
                           'observed_at': observed}
    discovery = None
    if profile == 'full':
        from lib.options_discovery import fetch_discovery
        discovery = fetch_discovery(max_pages=int(config.get('discovery_max_pages', 1000)))
    else:
        discovery = store.latest_full_discovery()
    discovery = discovery or {'status': 'UNAVAILABLE', 'rows': [], 'reason': 'no broad discovery receipt'}
    sources['market_discovery'] = {k: v for k, v in discovery.items() if k != 'rows'}
    rows = merge_research_rows([*rows, *discovery.get('rows', [])])
    # Read existing shortlist, never mint conviction from discovery membership.
    shortlisted = {p.get('symbol') for p in engine.read_proposals().get('proposals', [])
                   if p.get('approvable') is True}
    inventory = build_coverage(holdings=meta.get('_inventory_holdings', holdings), convictions=rows,
                              proposals=[], drops=[], chains={})['rows']
    for row in inventory:
        row['shortlisted'] = row['symbol'] in shortlisted
    return {'inventory': inventory, 'holdings': holdings, 'holdings_meta': meta, 'convictions': rows,
            'source_receipts': sources, 'discovery': discovery}


def tick(*, root=ROOT, apply=False):
    config = load_config(root)
    import options_engine as engine
    store = ScanStore(engine.STATE_DIR)
    now = datetime.now(timezone.utc)
    from lib.cio_market_session import get_session_service
    opened, closed, _ = get_session_service().official_bounds(now.astimezone(ZoneInfo('America/New_York')).date())
    due = due_profiles(now, open_at=opened, close_at=closed)
    plan = {'schema': 'OptionsScanPlan@v1', 'apply': apply, 'enabled': config.get('enabled', False),
            'due': due, 'active_runs': [{k: r[k] for k in ('id', 'profile', 'status')} for r in store.runs(active=True)],
            'requests_per_minute': config.get('provider_requests_per_minute'),
            'status': 'CONFIG_REQUIRED' if not config.get('enabled') else 'READY'}
    if not apply or not config.get('enabled'):
        return plan
    if not due and not any(r['payload'].get('projection_state') == 'PENDING' for r in store.runs(active=True)):
        return {**plan, 'status': 'SESSION_CLOSED'}
    engine.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (engine.STATE_DIR / 'options_scan.worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**plan, 'status': 'WORKER_BUSY'}
        for profile, key in due:
            store.request(profile, key)
        runs = store.runs(active=True)
        # Alternate profiles by the last checkpoint, avoiding starvation of either lane.
        runs.sort(key=lambda r: r['updated_at'])
        if not runs:
            return {**plan, 'status': 'IDLE'}
        import schwab_transport
        if not due:
            runs = [r for r in runs if r['payload'].get('projection_state') == 'PENDING']
        run = runs[0]
        if run['payload'].get('projection_state') != 'PENDING':
            run = run_slice(store, run, collect=lambda p: collect(p, engine=engine, store=store, config=config),
                            fetch_chain=lambda symbol: schwab_transport.get_option_chain(symbol, full_chain=True),
                            max_requests=int(config.get('max_requests_per_slice', 5)),
                            min_interval=60 / float(config['provider_requests_per_minute']))
        payload = run['payload']
        if run['status'] == 'RUNNING':
            return {**plan, 'status': 'RUNNING', 'run_id': run['id'],
                    'completed': len(payload['results']), 'inventory_count': len(payload['inventory'])}
        from lib.options_scan import CapturedChains
        receipts = {r['symbol']: payload.get('results', {}).get(r['symbol'], {'status': 'PENDING'})
                    for r in payload['inventory']}
        chains = CapturedChains(store, receipts)
        coverage_receipts = {s: v['receipt'] for s, v in store.latest_receipts().items()}
        coverage_receipts.update(receipts)
        scan_inputs = {**payload, 'chains': chains, 'chain_receipts': receipts,
                       'coverage_receipts': coverage_receipts, 'run_id': run['id'],
                       'run_status': run['status'], 'profile': run['profile']}
        projection = engine.generate_proposals(force=True, scan_inputs=scan_inputs)
        from lib.options_scan import request_missing_research
        from lib.symbol_thesis_priority import open_requests, request
        from lib.options_thesis_lifecycle import settings
        payload['research_requests'] = request_missing_research(
            projection.get('coverage', {}).get('rows', []), pending=set(open_requests(root=root)),
            limit=int(settings(engine._desk_cfg())['research_drain_per_tick']),
            request=lambda sym, **kw: request(sym, root=root, **kw), run_id=run['id'])
        payload['projection_state'] = 'COMPLETE'
        store.update(run['id'], run['status'], payload, event='PROJECTED')
        return {**plan, 'status': run['status'], 'run_id': run['id'],
                'inventory_count': len(payload['inventory']), 'completed': len(payload['results']),
                'request_count': payload.get('request_count'), 'response_bytes': payload.get('response_bytes'),
                'proposal_count': projection.get('count')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = tick(apply=args.apply and not args.dry_run)
    print(json.dumps(result, default=str))
    return 1 if result.get('status') in {'ERROR', 'PARTIAL'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
