"""Read-only Anthropic credit/usage projection shared by provider health and CC.

No credential material, database, prompt, provider probe, or notification send.
Remaining credit is an estimate: out-of-router console/SDK calls are not authorized
by this journal. Missing/corrupt evidence never becomes a healthy zero.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from .anthropic_credit import CreditBook, CreditDenied, amount, utc
from .anthropic_transport import load_policy


def _events(path: Path):
    if not path.exists():
        return [], 'NO_EVENTS'
    rows = []
    try:
        with path.open() as handle:
            for line in handle:
                row = json.loads(line)
                if row.get('provider') == 'anthropic' and not row.get('is_test'):
                    rows.append(row)
        return rows, 'COMPLETE_FILE'
    except (OSError, ValueError, TypeError):
        return rows, 'INCOMPLETE'


def snapshot(root: Path, *, policy=None, now=None, configured=None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    policy = policy or load_policy()
    configured = bool(os.environ.get('ANTHROPIC_API_KEY')) if configured is None else configured
    try:
        book = CreditBook(root, policy)
        credit = book.snapshot(now=now)
        # Read-only shared lock; the writer never publishes partial lines while locked.
        if book.path.exists():
            import fcntl
            with book.path.with_suffix('.lock').open('r') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                records = book._read()
        else:
            records = []
    except (CreditDenied, OSError, ValueError, KeyError, TypeError):
        credit, records = {'status':'UNAVAILABLE','as_of':now.isoformat(),
                           'remaining_is_estimated':True}, []
    events, coverage = _events(Path(root) / 'data/runtime/provider_cost/events.jsonl')
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = {'today': start, 'seven_days':now-timedelta(days=7)}
    usage, models = {}, defaultdict(lambda: {'calls':0,'usd':0.0})
    failures = [row for row in records if row['event']=='failure']
    success_times = []
    for label, since in windows.items():
        selected=[]
        for event in events:
            try:
                at=utc(event['usage_start'])
            except (ValueError, KeyError, TypeError, CreditDenied):
                coverage='INCOMPLETE'
                continue
            if since <= at <= now:
                selected.append(event)
        errors=[row for row in failures if since <= utc(row['at']) <= now]
        missing_cost=any(row.get('calculated_cost_usd') is None for row in selected)
        if missing_cost: coverage='INCOMPLETE'
        total=None if missing_cost else sum(float(row['calculated_cost_usd']) for row in selected)
        usage[label]={'calls':len(selected),'usd':total,'failure_attempts':len(errors),
                      'error_rate':len(errors)/(len(selected)+len(errors)) if selected or errors else None}
        if label=='seven_days':
            for row in selected:
                m=models[str(row.get('model') or 'unknown')]
                m['calls']+=1
                if row.get('calculated_cost_usd') is None or m['usd'] is None:
                    m['usd']=None
                else:
                    m['usd']+=float(row['calculated_cost_usd'])
                success_times.append(row['usage_start'])
    fallbacks=[row for row in records if row['event']=='fallback']
    last_error=failures[-1] if failures else None
    last_success=max(success_times,default=None)
    continuous=[row for row in failures if row['reason'] in {'auth_failure','billing_error'}
                and (last_success is None or utc(row['at']) > utc(last_success))]
    critical=(policy.get('enabled') is True and policy.get('provider_enabled',True) is True
              and policy.get('provider_order',[None])[0]=='anthropic' and bool(configured)
              and (len(continuous)>=3 or credit.get('exhausted_reason')=='billing_error'))
    status=credit['status']
    if not configured:
        status='NOT_CONFIGURED'
    elif (critical or last_success is None) and status=='OK':
        status='DEGRADED'
    return {'schema':'AnthropicProviderStatus@v1','provider':'anthropic','status':status,
            'configured':bool(configured),'credit':credit,'usage':usage,
            'models':dict(models),'last_success_at':last_success,
            'last_error':({'code':last_error['reason'],'at':last_error['at']} if last_error else None),
            'fallback_count':len(fallbacks),'fallback_reasons':dict(Counter(r['reason'] for r in fallbacks)),
            'last_fallback_reason':fallbacks[-1]['reason'] if fallbacks else credit.get('last_fallback_reason'),
            'routing_order':policy['provider_order'] if status in {'OK','DEGRADED'} else policy['provider_order'][1:],
            'measurement_basis':'canonical response events plus HTTP failure attempts; retries are attempts, not additional logical requests',
            'ledger_coverage':coverage,'p1_continuous_failure':critical,'as_of':now.isoformat(),
            'offpeak':'Promotional credit exempt; DeepSeek deferral unchanged',
            'note':policy.get('external_credit_note'),
            'digest_line':f"Anthropic {status} · credit used ${credit.get('credit_used_usd','?')} · remaining estimate ${credit.get('estimated_credit_remaining_usd','?')} · UTC daily ${credit.get('today_used_usd','?')}/${policy['daily_cap_usd']} · expires {policy['expires_at']}"}


def due_notes(status: dict, policy: dict) -> list[dict]:
    credit=status['credit']
    result=[]
    if credit.get('credit_used_usd') is not None:
        percentage=amount(credit['credit_used_usd']) / amount(policy['credit_usd']) * 100
        for threshold in policy['threshold_notes']:
            if percentage >= threshold:
                result.append({'key':f'credit-{threshold}','priority':'P2','message':f'Anthropic promotional credit: {threshold}% used. '+status['digest_line']})
    if credit['status']=='EXHAUSTED':
        result.append({'key':'exhausted','priority':'P2','message':status['digest_line']})
    if 0 < credit.get('days_to_expiry',1000) <= policy['expiry_notice_days']:
        result.append({'key':'expiry-3-days','priority':'P2','message':status['digest_line']})
    if status['p1_continuous_failure']:
        result.append({'key':'continuous-auth-billing','priority':'P1','message':'Anthropic first choice continuously failing auth/billing. '+status['digest_line']})
    return result
