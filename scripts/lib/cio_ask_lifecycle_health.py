"""Read-only Ask lifecycle business health; no DB, models, sends or store writes.

Scheduler RUN_DONE is transport evidence only. Business freshness is a canonical
per-thread check, independently of the six-hour answer cooldown. Missing or old
receipt schemas remain UNAVAILABLE, never a healthy zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

LANE = 'cio-ask-lifecycle'
EVENT_LANE = 'cio-ask-material-events'
SCHEMA = 'CioAskLifecycleHealth@v1'
RECEIPT_SCHEMA = 'CioAskLifecycleReceipt@v1'
AUTHORITY = 'READ_ONLY_ADVISORY'
HOURLY_GRACE = timedelta(minutes=15)
EVENT_MAX_AGE = timedelta(minutes=15)
COUNTERS = ('checked_count', 'research_count', 'no_change_count', 'blocked_count',
            'failed_count', 'deferred_count', 'tracked_threads')


def _at(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _state(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get('state') or value.get('outcome') or value.get('status')
    return str(value or '').lower()


def _base(now: datetime, conditions: list[dict], **extra) -> dict:
    unknown = any(c['severity'] == 'UNAVAILABLE' for c in conditions)
    return {'schema': SCHEMA, 'lane': LANE, 'authority': AUTHORITY,
            'as_of': now.isoformat(), 'ok': not conditions,
            'status': 'UNAVAILABLE' if unknown else 'WARN' if conditions else 'OK',
            'firing': [c['code'] + (':' + c['thread_id'] if c.get('thread_id') else '') for c in conditions],
            'conditions': conditions, 'reads_raw_store': True, 'filters_last_real': False,
            'provider_calls': False, 'sends': False, 'writes': False, **extra}


def unavailable(*, now: datetime, code='evidence_unavailable') -> dict:
    return _base(now, [{'code': code, 'severity': 'UNAVAILABLE'}], tracked_threads=0,
                 chain={'trigger': False, 'host_receipt': False, 'thread_check': False,
                        'memory_sync': False, 'consumer_readback': False, 'delivery': False})


def _receipt(doc: Any, attempt: Any, lane: str, now: datetime, conditions: list[dict], *, freshness=True):
    def issue(code, severity='UNAVAILABLE'):
        conditions.append({'code': lane + '.' + code, 'severity': severity})
    if not isinstance(doc, Mapping):
        issue('receipt_missing')
        return None
    summary = doc.get('summary') if doc.get('schema') in {'LaneRunReceipt@v1', 'LaneRunReceipt@v2'} else doc
    if not isinstance(summary, Mapping) or summary.get('schema') != RECEIPT_SCHEMA:
        issue('receipt_schema_unavailable')
        return None
    run_id = summary.get('run_id') or doc.get('run_id')
    if (not isinstance(run_id, str) or not run_id
            or summary.get('dry_run') is not False or summary.get('mode') != 'live'):
        issue('not_live_business_evidence')
        return None
    if any(type(summary.get(key)) is not int or summary[key] < 0 for key in COUNTERS):
        issue('receipt_counts_unavailable')
        return None
    if (not isinstance(summary.get('threads'), list) or not isinstance(summary.get('source_errors'), list)
            or type(summary.get('ok')) is not bool):
        issue('receipt_fields_unavailable')
        return None
    observed = _at(summary.get('observed_at'))
    if observed is None or observed > now:
        issue('receipt_clock_unavailable')
        return None
    # Server-minted dispatcher slots bind the trigger to this exact host attempt.
    # Both native schedules use d: keys; a manual success cannot prove scheduling.
    key = re.fullmatch(r'd:' + re.escape(lane) + r':live:([0-9]{8}T[0-9]{4})(?::a[2-9])?', run_id)
    try:
        slot = datetime.strptime(key[1], '%Y%m%dT%H%M') if key else None
    except ValueError:
        slot = None
    if slot is None or (slot.minute != 0 if lane == LANE else slot.minute % 5 != 0):
        issue('trigger_identity_unverified')
    v2 = (isinstance(attempt, Mapping)
          and (attempt.get('schema') == 'LaneRunReceipt@v2' or attempt.get('output_fields') == 'LaneRunReceipt@v2'))
    if not (v2 and attempt.get('lane_id') == lane and attempt.get('run_id') == run_id
            and attempt.get('mode') == 'live' and attempt.get('run_mode', 'live') == 'live'
            and type(attempt.get('exit')) is int and attempt['exit'] == 0
            and attempt.get('status') == 'ok'):
        issue('host_attempt_unverified')
    else:
        started, finished = _at(attempt.get('started_at')), _at(attempt.get('finished_at'))
        if started is None or finished is None or not started <= observed <= finished <= now:
            issue('host_attempt_clock_unverified')
        produced = attempt.get('produced_count')
        if type(produced) is not int or produced < 0 or produced < summary['checked_count']:
            issue('host_output_unverified')
        elif produced == 0 and attempt.get('empty_reason') not in {
                'no_tracked_threads', 'no_new_events', 'no_due_threads'}:
            issue('host_empty_reason_unverified')
        at_summary = attempt.get('summary')
        if not isinstance(at_summary, Mapping) or dict(at_summary) != dict(summary):
            issue('host_attempt_summary_mismatch')
    if not summary['ok'] or summary['failed_count']:
        issue('host_run_failed', 'WARN')
    if summary['source_errors']:
        issue('source_errors', 'WARN')
    max_age = timedelta(hours=1) + HOURLY_GRACE if lane == LANE else EVENT_MAX_AGE
    if freshness and now - observed > max_age:
        issue('receipt_late', 'WARN')
    return summary


def evaluate(*, receipt: Any, material_receipt: Any, threads: Any,
             attempt_receipt: Any = None, material_attempt_receipt: Any = None,
             now: datetime, thread_attempt_receipts=()) -> dict:
    """Evaluate supplied evidence only; every adapter is injected at collection."""
    now = _at(now)
    if now is None:
        raise ValueError('timezone-aware now is required')
    conditions: list[dict] = []
    hourly = _receipt(receipt, attempt_receipt, LANE, now, conditions)
    events = _receipt(material_receipt, material_attempt_receipt, EVENT_LANE, now, conditions)
    if isinstance(threads, Mapping):
        rows = list(threads.values())
    elif isinstance(threads, list):
        rows = threads
    else:
        return unavailable(now=now, code='canonical_threads_unavailable')
    projected = {}
    proofs = [hourly, events]
    # A later no-event receipt may contain no thread rows. Its previous real
    # per-thread check remains provable by the immutable executor attempt.
    for archived in thread_attempt_receipts:
        lane = archived.get('lane_id') if isinstance(archived, Mapping) else None
        if lane not in {LANE, EVENT_LANE}:
            continue
        defects: list[dict] = []
        summary = _receipt(archived, archived, lane, now, defects, freshness=False)
        if summary is not None and not defects:
            proofs.append(summary)
    for summary in proofs:
        for row in summary.get('threads', []) if summary else []:
            if not isinstance(row, Mapping) or not isinstance(row.get('thread_id'), str):
                conditions.append({'code': 'receipt_thread_unavailable', 'severity': 'UNAVAILABLE'})
                continue
            tid = row['thread_id']
            prior = projected.get(tid)
            checked = _at((row.get('lifecycle') or {}).get('last_checked_at')) if isinstance(row.get('lifecycle'), Mapping) else None
            old = _at((prior.get('lifecycle') or {}).get('last_checked_at')) if prior else None
            if prior is None or (checked and (old is None or checked >= old)):
                projected[tid] = row
    active, results = [], []
    for thread in rows:
        if not isinstance(thread, Mapping):
            conditions.append({'code': 'canonical_thread_unavailable', 'severity': 'UNAVAILABLE'})
            continue
        lifecycle = thread.get('lifecycle')
        entities = thread.get('entities') or []
        tracked = any(isinstance(e, Mapping) and (e.get('tracking') or {}).get('state') == 'tracked'
                      for e in entities if isinstance(entities, list))
        if not tracked and not (isinstance(lifecycle, Mapping) and lifecycle.get('monitoring_active') is True):
            continue
        tid = str(thread.get('thread_id') or '')
        active.append(tid)
        local: list[str] = []
        def issue(code, severity='WARN'):
            conditions.append({'code': code, 'severity': severity, 'thread_id': tid})
            local.append(code)
        if not isinstance(lifecycle, Mapping) or not tid:
            issue('lifecycle_unavailable', 'UNAVAILABLE')
            continue
        checked = _at(lifecycle.get('last_checked_at'))
        due = _at(lifecycle.get('next_check_at'))
        if due is None and checked is not None:
            due = checked + timedelta(hours=1)
        if checked is not None and due is not None:
            due = min(due, checked + timedelta(hours=1))
        if checked is None or checked > now or due is None:
            issue('hourly_check_unavailable', 'UNAVAILABLE')
        elif now > due + HOURLY_GRACE:
            # next_eligible_at gates another ANSWER, never the evidence check.
            issue('hourly_check_late')
        outcome = lifecycle.get('last_check_outcome')
        outcome_state = _state(outcome)
        if not outcome_state:
            issue('check_outcome_unavailable', 'UNAVAILABLE')
        if outcome_state in {'blocked', 'failed', 'error'}:
            issue('check_' + outcome_state)
        proof = projected.get(tid)
        evidence_lifecycle = proof.get('lifecycle') if proof else None
        if (not isinstance(evidence_lifecycle, Mapping)
                or _at(evidence_lifecycle.get('last_checked_at')) != checked
                or evidence_lifecycle.get('last_check_outcome') != outcome
                or evidence_lifecycle.get('last_answer_at') != lifecycle.get('last_answer_at')):
            issue('thread_check_readback_unverified', 'UNAVAILABLE')
        memory = _state(lifecycle.get('memory_sync'))
        if memory not in {'synced', 'verified', 'ok', 'not_required', 'ledger_only'}:
            issue('memory_sync_pending' if memory in {'pending', 'queued', 'retry'} else 'memory_sync_unverified')
        readback = proof.get('consumer_readback') if proof else None
        if _state(readback) not in {'verified', 'matched', 'visible', 'ok'}:
            issue('consumer_readback_unverified')
        elif isinstance(readback, Mapping):
            latest_id = next((answer.get('answer_id') for turn in reversed(thread.get('turns') or [])
                              for answer in reversed(turn.get('answers') or []) if answer.get('answer_id')), None)
            if latest_id is not None and readback.get('answer_id') != latest_id:
                issue('consumer_answer_readback_mismatch')
            measured_at = readback.get('checked_at') or readback.get('last_checked_at')
            if measured_at is not None and _at(measured_at) != checked:
                issue('consumer_check_readback_mismatch')
        delivery = _state(lifecycle.get('delivery'))
        if delivery not in {'delivered', 'verified', 'not_required', 'not_applicable'}:
            issue('delivery_pending' if delivery in {'pending', 'queued', 'accepted', 'deferred'} else 'delivery_unverified')
        results.append({'thread_id': tid, 'last_checked_at': checked.isoformat() if checked else None,
                        'next_check_at': due.isoformat() if due else None,
                        'answer_cooldown': _at(lifecycle.get('next_eligible_at')) is not None
                        and _at(lifecycle['next_eligible_at']) > now,
                        'check_outcome': outcome_state,
                        'cooldown_deferred': outcome_state in {'cooldown', 'cooldown_deferred', 'deferred_cooldown'}
                        or (outcome_state == 'deferred' and str(
                            outcome.get('reason') if isinstance(outcome, Mapping) else lifecycle.get('reason')
                            ).lower() in {'cooldown', 'answer_cooldown'}),
                        'memory_sync': memory,
                        'consumer_readback': _state(readback), 'delivery': delivery, 'conditions': local})
    codes = [c['code'] for c in conditions]
    chain = {
        'trigger': hourly is not None and events is not None and not any('trigger_identity' in c for c in codes),
        'host_receipt': hourly is not None and events is not None and not any('host_' in c or 'receipt_' in c or 'not_live_' in c for c in codes),
        'thread_check': not any(c.startswith(('hourly_', 'check_', 'thread_check_', 'lifecycle_')) for c in codes),
        'memory_sync': not any(c.startswith('memory_') for c in codes),
        'consumer_readback': not any(c.startswith('consumer_') for c in codes),
        'delivery': not any(c.startswith('delivery_') for c in codes),
    }
    return _base(now, conditions, tracked_threads=len(active), threads=results, chain=chain,
                 hourly_run_id=hourly.get('run_id') if hourly else None,
                 material_run_id=events.get('run_id') if events else None,
                 cooldown_deferred=sum(r['cooldown_deferred'] for r in results),
                 last_checked_at=max((r['last_checked_at'] for r in results if r['last_checked_at']), default=None))


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('object required')
    return value


def collect_cio_ask_lifecycle_health(*, now=None, root=None, thread_reader=None, receipt_reader=None) -> dict:
    """Read canonical Ask projection and immutable host attempt receipts only.

    CI without an explicit fixture root returns UNAVAILABLE without inspecting a
    host store. Callers can inject readers and root for full isolated collection.
    """
    now = _at(now or datetime.now(timezone.utc))
    if now is None:
        raise ValueError('timezone-aware now is required')
    supplied = root or os.environ.get('TRADEAI_STATE_ROOT') or os.environ.get('PROJECT_ROOT')
    if supplied is None and os.environ.get('TRADE_AI_CI') == '1':
        return unavailable(now=now, code='fixture_root_required')
    try:
        if supplied is None:
            from scripts.lib.lane_registry import state_root
            supplied = state_root()
        root = Path(supplied)
        if thread_reader is None:
            from scripts.lib.cio_ask_store import AskEventStore
            store = AskEventStore(root / 'data/cio/cio_ask_events.jsonl')
            # Reject torn/non-object evidence before the canonical replay, which
            # otherwise skips malformed lines for interactive availability.
            if not store.path.is_file():
                raise ValueError('canonical ledger missing')
            for line in store.path.read_text(encoding='utf-8').splitlines():
                if line.strip() and not isinstance(json.loads(line), dict):
                    raise ValueError('canonical ledger row is not an object')
            thread_reader = store.threads
        read = receipt_reader or _read
        docs, attempts, historical = [], [], []
        for lane in (LANE, EVENT_LANE):
            try:
                doc = read(root / f'data/runtime/{lane}_last.json')
            except (OSError, ValueError, TypeError):
                doc = None
            summary = doc.get('summary', doc) if isinstance(doc, Mapping) else {}
            rid = str(summary.get('run_id') or (doc.get('run_id') if isinstance(doc, Mapping) else '') or '')
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', rid)[:160]
            try:
                attempt = read(root / f'data/runtime/lane_attempts/{lane}/{safe}.json') if safe and not safe.startswith('.') else None
            except (OSError, ValueError, TypeError):
                attempt = None
            docs.append(doc)
            attempts.append(attempt)
            # At five-minute cadence, 32 copies cover more than the 75-minute
            # healthy business window. Names bind server slot identity; never
            # follow arbitrary refs from a receipt or enumerate another store.
            directory = root / f'data/runtime/lane_attempts/{lane}'
            for path in sorted(directory.glob('*.json'))[-32:]:
                try:
                    historical.append(read(path))
                except (OSError, ValueError, TypeError):
                    continue
        return evaluate(receipt=docs[0], material_receipt=docs[1], threads=thread_reader(),
                        attempt_receipt=attempts[0], material_attempt_receipt=attempts[1], now=now,
                        thread_attempt_receipts=historical)
    except Exception:
        return unavailable(now=now, code='evidence_read_failed')
