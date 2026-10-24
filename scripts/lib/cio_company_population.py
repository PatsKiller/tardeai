"""Populate company evidence on confirmed-GUID CIO memory, never mint judgments.

Existing InstrumentRecord facade/store only. All upstream reads are stored batches;
HTTP readers remain read-only. This module never promotes the prospect domain.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
from scripts.lib import cio_company_facts as facts
from scripts.lib import cio_instrument_record as ir
from scripts.lib.identity_carriage import resolve_security_identity

LANE_ID = 'cio-company-facts-populate'
RECEIPT_REL = 'data/runtime/cio-company-facts-populate_last.json'


def _json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def symbols_from(capture: dict) -> dict[str, list[str]]:
    return {k: sorted({str(s).strip().upper() for s in capture.get(k) or [] if str(s).strip()})
            for k in ('my_watchlist', 'held', 'formerly_held')}


def stored_catalysts(root: Path) -> dict:
    """Plain file reads only, no Hermes store loader/repair and no provider."""
    from scripts.lib.cio_prospect_builder import load_hermes_catalysts
    out = load_hermes_catalysts(root)
    scans = {}
    for value in _json(root / 'data/runtime/trade_ai_cache.json').values():
        for r in value if isinstance(value, list) else []:
            if isinstance(r, dict) and r.get('symbol') and r.get('decision'):
                sym = str(r['symbol']).upper()
                if str(r.get('observed_at') or '') >= str((scans.get(sym) or {}).get('observed_at') or ''):
                    scans[sym] = r
    out['scanner'] = {'rows': scans, 'status': 'ok' if scans else 'missing'}
    return out


def _coverage(records: list[dict], groups: dict, identities: dict, *, now: datetime) -> dict:
    from scripts.lib.data_broker.cio_company_facts import load_snapshot, for_security
    snapshot = load_snapshot(records=records)
    out = {}
    for name, syms in groups.items():
        fields = {k: 0 for k in facts.FIELDS}
        complete, gaps = 0, []
        catalysts = {'current': 0, 'missing': 0, 'gaps': []}
        for sym in syms:
            guid = (identities.get(sym) or {}).get('security_guid')
            public = for_security(snapshot, sym, guid, now=now)
            f = (public or {}).get('company_facts') or {}
            cat = f.get('catalyst') or {}
            if cat.get('status') == 'CURRENT' and cat.get('headline'):
                catalysts['current'] += 1
            else:
                catalysts['missing'] += 1
                catalysts['gaps'].append({'symbol': sym, 'reason': cat.get('missing_reason') or 'catalyst_not_on_cio_record'})
            missing = []
            for key in fields:
                if (f.get(key) or {}).get('value'): fields[key] += 1
                else: missing.append(key)
            if not missing: complete += 1
            else: gaps.append({'symbol': sym, 'missing_fields': missing,
                               'reason': f.get('missing_reason') or 'company_fields_not_on_cio_record',
                               'missing_reasons': {key: (f.get(key) or {}).get('missing_reason') for key in missing}})
        out[name] = {'total': len(syms), 'complete': complete, 'fields': fields, 'gaps': gaps,
                     'complete_pct': round(100*complete/len(syms), 2) if syms else None, 'catalysts': catalysts}
    return out


def populate(root: Path, capture: dict, *, apply=False, now=None, backend=None, registry=None, env=None) -> dict:
    """Plan in memory by default; explicit apply writes only through the existing facade.

    Capture identity is cross-checked against the root's actual identity registry.
    All original source clocks and sibling research/judgments are preserved.
    """
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    if not isinstance(capture, dict) or any(not isinstance(capture.get(k), list)
            for k in ('my_watchlist', 'held', 'formerly_held')) or not isinstance(capture.get('profiles'), dict):
        raise ValueError('membership_and_profiles_capture_required')
    groups = symbols_from(capture)
    symbols = sorted(set().union(*map(set, groups.values())))
    store = ir.InstrumentRecordStore(root / ir.DEFAULT_PATH)
    records = store.all()
    identities = {s: resolve_security_identity(s, root=root) for s in symbols}
    result = {'lane_id': LANE_ID, 'mode': 'apply' if apply else 'dry_run', 'captured_at': capture.get('captured_at'),
              'evaluated_at': now.isoformat(), 'target_count': len(symbols), 'created': 0, 'updated': 0,
              'would_create': 0, 'would_update': 0, 'unchanged': 0, 'gaps': [], 'identity_gaps': [], 'pg': [], 'writes': 0,
              'before': _coverage(records, groups, identities, now=now), 'source_gaps': deepcopy(capture.get('gaps') or []),
              'record_kind': 'FACTS_ONLY; judged records preserved', 'judgment_writes': 0, 'prospect_promotions': 0}
    inputs = facts.collect_inputs(root, symbols, now=now)
    inputs['profiles'] = capture.get('profiles') or {}
    inputs['errors'] = [e for e in inputs['errors'] if e != 'symbol_profiles:not_read_no_db']
    catalysts = stored_catalysts(root)
    captured_events = capture.get('catalyst_events')
    if isinstance(captured_events, dict) and isinstance(captured_events.get('rows'), dict):
        catalysts['catalyst_events'] = deepcopy(captured_events)
    else:
        catalysts['catalyst_events'] = {'status': 'not_captured', 'rows': {}}
    result['catalyst_sources'] = {k: {x: v.get(x) for x in ('status', 'as_of', 'path', 'count')}
                                  for k, v in catalysts.items() if isinstance(v, dict)}
    if catalysts['catalyst_events'].get('status') != 'ok':
        reason = catalysts['catalyst_events'].get('status') or 'source_status_missing'
        result['source_gaps'].append({'scope': 'catalyst_events', 'reason': reason})
        inputs.setdefault('errors', []).append('catalyst_events:' + str(reason))
    from scripts.lib.cio_prospect_builder import catalyst_facts
    projected = list(records)
    pg_requested = str((os.environ if env is None else env).get(ir.PROSPECT_DUAL_WRITE_ENV) or '').strip() == '1'
    seen = set()
    for sym in symbols:
        ident = identities[sym]
        guid = ident.get('security_guid')
        if not facts.confirmed(ident):
            result['gaps'].append({'symbol': sym, 'reason': 'identity_not_confirmed', 'identity_lookup': ident.get('identity_lookup')})
            continue
        if not ident.get('issuer_guid'):
            result['identity_gaps'].append({'symbol': sym, 'security_guid': guid, 'reason': 'issuer_guid_missing; confirmed security facts permitted'})
        captured_guid = (capture.get('identities', {}).get(sym) or {}).get('security_guid')
        if captured_guid and captured_guid != guid:
            result['gaps'].append({'symbol': sym, 'reason': 'capture_registry_identity_drift'})
            continue
        if guid in seen:
            continue  # one canonical record per security, aliases are not duplicate facts
        seen.add(guid)
        matches = [r for r in records if r.get('security_guid') == guid]
        if len(matches) > 1:
            result['gaps'].append({'symbol': sym, 'security_guid': guid, 'reason': 'multiple_cio_records_for_guid'})
            continue
        prior = matches[0] if matches else None
        if prior and ident.get('issuer_guid') and prior.get('issuer_guid') not in (None, ident['issuer_guid']):
            result['gaps'].append({'symbol': sym, 'reason': 'canonical_issuer_conflict'})
            continue
        rec = deepcopy(prior) if prior else ir.new_record('SECURITY', sym, symbols=[sym], **{
            k: ident[k] for k in ('security_guid','issuer_guid','subject_guid','identity_status') if ident.get(k)})
        rec.setdefault('identity_status', 'CONFIRMED')
        rec.setdefault('issuer_guid', ident.get('issuer_guid'))
        if rec.get('subject_key') in {r.get('subject_key') for r in records if r.get('security_guid') not in (None, guid)}:
            result['gaps'].append({'symbol': sym, 'reason': 'canonical_subject_key_identity_conflict'})
            continue
        catalyst, _, _ = catalyst_facts(sym, catalysts, ident, now=now)
        assembled = facts.assemble(sym, ident, inputs, catalyst=catalyst,
                                   prior=(rec.get('research') or {}).get('company_facts'), now=now)
        # Retained values can be identical to the freshly read winning evidence.
        # Preserve distinct values/sources/clocks, but do not append a duplicate
        # copy of that exact evidence to every conflict on every daily pass.
        for conflict in assembled.get('conflicts') or []:
            if isinstance(conflict.get('values'), list):
                unique = {}
                for value in conflict['values']:
                    unique.setdefault(json.dumps(value, sort_keys=True, default=str), value)
                conflict['values'] = list(unique.values())
        old_facts = (rec.get('research') or {}).get('company_facts')
        if old_facts and {k: v for k, v in old_facts.items() if k != 'assembled_at'} == {
                k: v for k, v in assembled.items() if k != 'assembled_at'}:
            result['unchanged'] += 1
            if apply and pg_requested:
                status = ir.prospect_store_status(registry=registry, env=env,
                    table_probe=backend.table_present if backend else None)
                pg = {**status, 'requested': True, 'symbol': sym, 'security_guid': guid}
                try:
                    if not status['live'] or backend is None:
                        raise ir.ProspectInvalid('PG preflight unavailable')
                    if ir.is_fact_only_record(rec) and not backend.fact_only_ready():
                        raise ir.ProspectInvalid('fact-only migration required')
                    pg['ok'] = backend.company_facts_equal(guid, old_facts)
                    pg['reason'] = 'same_guid_readback_verified' if pg['ok'] else 'unchanged_pg_divergence_owner_reconciliation_required'
                except Exception as exc:
                    pg.update(ok=False, reason='unchanged_pg_ack_not_measured', error=type(exc).__name__)
                result['pg'].append(pg)
                if not pg['ok']:
                    result['gaps'].append({'symbol': sym, 'reason': pg['reason']})
            continue
        try:
            updated, _ = ir.apply_prospect(rec, prospect={'research': {'company_facts': assembled}}, fact_only=True)
            key = 'create' if prior is None else 'update'
            result['would_'+key] += 1
            if apply:
                receipt = store.upsert_prospect(updated, fact_only=True, backend=backend, registry=registry, env=env)
                pg = deepcopy(receipt['pg'])
                if pg.get('error'): pg['error'] = str(pg['error']).split(':', 1)[0]
                result['pg'].append({'symbol': sym, 'security_guid': guid, **pg})
                if receipt.get('row') is None:
                    result['gaps'].append({'symbol': sym, 'reason': pg.get('reason') or 'pg_preflight_refused'})
                    continue
                updated = receipt['row']
                result['created' if prior is None else 'updated'] += 1
                result['writes'] += 1
                if pg.get('ok') is False:
                    result['gaps'].append({'symbol': sym, 'reason': pg.get('reason') or 'pg_write_failed_after_canonical_append'})
            projected = [r for r in projected if r.get('subject_key') != updated['subject_key']] + [updated]
        except (ir.ProspectInvalid, ir.BehaviorWriteRefused, ir.CognitionNoOp) as exc:
            result['gaps'].append({'symbol': sym, 'reason': type(exc).__name__, 'detail': str(exc)[:200]})
    result['after'] = _coverage(projected, groups, identities, now=now)
    result['ok'] = not [g for g in result['gaps'] if g.get('reason') != 'identity_not_confirmed'] and not [
        g for g in result['source_gaps'] if g.get('scope') in ('held', 'catalyst_events') or str(g.get('scope') or '').startswith('membership:')]
    result['quality_status'] = 'PARTIAL' if result['gaps'] or result['identity_gaps'] or any(
        g['complete'] < g['total'] for g in result['after'].values()) else 'COMPLETE'
    result['canonical_persisted'] = bool(apply and result['writes'])
    result['pg_requested'] = pg_requested
    result['pg_sync'] = ('READBACK_OR_WRITE_ACKNOWLEDGED' if result['pg'] and all(p.get('ok') for p in result['pg'])
                         else 'NOT_MEASURED_OR_PARTIAL') if pg_requested else 'NOT_REQUESTED_FLAG_OFF'
    return result


def capture_readonly_inputs(root: Path, query, *, now=None) -> dict:
    """Existing membership/profiles plus all available sell history, SELECT only.

    Caller must inject a server-enforced READ ONLY query. Held set is the approved
    stored holdings accessor, not positions_current and never a live broker.
    """
    from scripts.lib.data_broker.watch_domains import membership_operator
    from scripts.lib.data_broker.symbol_profile import get_symbol_profiles
    from scripts.lib import portfolio_positions
    now = now or datetime.now(timezone.utc)
    membership = membership_operator(query)
    gaps = [{'scope': 'membership:'+k, 'reason': v.get('error') or v.get('status')}
            for k, v in membership['sources'].items() if v.get('status') != 'ok']
    held_doc = portfolio_positions.load_store(portfolio_positions.store_path(root))
    held = sorted({str(r.get('symbol') or '').upper() for r in held_doc.get('holdings') or []
                   if r.get('symbol') and float(r.get('shares', r.get('quantity')) or 0) > 0})
    if not held_doc:
        gaps.append({'scope': 'held', 'reason': 'holdings_accounts_snapshot_missing'})
    former = query("SELECT upper(symbol) AS symbol, max(coalesce(trade_time, trade_date::timestamptz)) AS last_sell_at "
                   "FROM trade_transactions WHERE lower(action) LIKE 'sell%%' GROUP BY 1") or []
    formerly = sorted({str(r['symbol']) for r in former if r.get('symbol')} - set(held))
    bounds = query('SELECT min(trade_date) AS first_trade_date, max(trade_date) AS last_trade_date, count(*) AS ledger_rows FROM trade_transactions')
    syms = sorted(set(membership['names']) | set(held) | set(formerly))
    from scripts.lib.cio_prospect_builder import load_catalyst_inputs
    catalyst_events = load_catalyst_inputs(query)['catalyst_events']
    return {'catalyst_events': catalyst_events, 'captured_at': now.isoformat(), 'database_read_only': True,
            'snapshot_coherence': 'PER_QUERY_TRANSACTIONS; original observation clocks retained',
            'my_watchlist': sorted(membership['names']), 'held': held, 'formerly_held': formerly,
            'profiles': get_symbol_profiles(query, syms), 'ledger_coverage': bounds,
            'membership_sources': membership['sources'], 'gaps': gaps,
            'held_source': {'source': 'holdings_accounts.holdings_json', 'as_of': held_doc.get('as_of') or held_doc.get('data_as_of')}}
