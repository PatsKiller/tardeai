"""Read-only Anthropic credit/usage projection shared by health and Command Center.

No credential values, database, prompt, provider probe, or notification send.
Malformed evidence produces UNAVAILABLE/INCOMPLETE without breaking other reports.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
from threading import Lock

from .anthropic_credit import CreditBook, amount, utc
from .anthropic_transport import load_policy

# Cache only Anthropic rows. Fingerprints detect append, rewrite and replacement;
# a changed file during a read is never published as complete or cached.
_EVENT_CACHE: OrderedDict = OrderedDict()
_EVENT_CACHE_LOCK = Lock()
_EVENT_CACHE_LIMIT = 8


def _fingerprint(path: Path) -> tuple:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _events(path: Path):
    key = str(path.absolute())
    try:
        fingerprint = _fingerprint(path)
    except FileNotFoundError:
        return (), 'NO_EVENTS'
    except OSError:
        return (), 'INCOMPLETE'
    with _EVENT_CACHE_LOCK:
        cached = _EVENT_CACHE.get(key)
        if cached and cached[0] == fingerprint:
            _EVENT_CACHE.move_to_end(key)
            return cached[1], cached[2]
    rows, coverage = [], 'COMPLETE_FILE'
    try:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('event is not an object')
                    if row.get('provider') == 'anthropic' and not row.get('is_test'):
                        rows.append(row)
                except (ValueError, TypeError):
                    coverage = 'INCOMPLETE'
        if _fingerprint(path) != fingerprint:
            return tuple(rows), 'INCOMPLETE'
    except (OSError, UnicodeError):
        return tuple(rows), 'INCOMPLETE'
    result = (fingerprint, tuple(rows), coverage)
    with _EVENT_CACHE_LOCK:
        _EVENT_CACHE[key] = result
        _EVENT_CACHE.move_to_end(key)
        while len(_EVENT_CACHE) > _EVENT_CACHE_LIMIT:
            _EVENT_CACHE.popitem(last=False)
    return result[1], result[2]


def configuration_evidence(manifest_path: Path | None = None) -> tuple[bool, str]:
    """Use renderer key NAMES, including for services without EnvironmentFile.

    This never reads the rendered env, resolves a secret, or returns manifest
    hashes. A valid shared manifest is authoritative over a process's stale env.
    """
    if manifest_path is None:
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
        manifest_path = runtime / 'tradeai/env.manifest.json'
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        names = manifest.get('shell_keys') if isinstance(manifest, dict) else None
        if isinstance(names, list) and all(isinstance(name, str) for name in names):
            return 'ANTHROPIC_API_KEY' in names, 'rendered_manifest_names'
    except (OSError, ValueError, TypeError):
        pass
    # Presence only: do not access, load, log, or return a credential value.
    return 'ANTHROPIC_API_KEY' in os.environ, 'process_environment_names'


def unavailable_snapshot(*, now=None, configured=False, reason='MONITOR_UNAVAILABLE') -> dict:
    """Complete, non-secret fallback shape for independent report call sites."""
    try:
        at = utc(now or datetime.now(timezone.utc)).isoformat()
    except Exception:
        at = datetime.now(timezone.utc).isoformat()
    return {
        'schema': 'AnthropicProviderStatus@v1', 'provider': 'anthropic',
        'status': 'UNAVAILABLE', 'configured': bool(configured),
        'configuration_basis': 'unavailable', 'credit': {
            'status': 'UNAVAILABLE', 'as_of': at, 'remaining_is_estimated': True},
        'usage': {period: {'calls': 0, 'usd': None, 'failure_attempts': 0, 'error_rate': None}
                  for period in ('today', 'seven_days')},
        'models': {}, 'models_by_period': {'today': {}, 'seven_days': {}},
        'last_success_at': None, 'last_error': {'code': reason, 'at': at},
        'fallback_count': 0, 'fallback_reasons': {}, 'last_fallback_reason': None,
        'routing_order': [], 'ledger_coverage': 'UNAVAILABLE',
        'p1_continuous_failure': False, 'p1_auth_failure': False,
        'p1_billing_failure': False, 'as_of': at,
        'probe': {'basis': 'last_real_call', 'active_probe_performed': False},
        'digest_line': 'Anthropic UNAVAILABLE · monitoring evidence unavailable; review LLM Spend.',
    }



def _manifest_for_root(root: Path) -> Path | None:
    # Temporary PROJECT_ROOT proofs and isolated readers must stay within their
    # supplied evidence tree. Only the real, un-overridden state root discovers
    # the host renderer manifest by default.
    local = root / 'data/runtime/env.manifest.json'
    if os.environ.get('PROJECT_ROOT') or os.environ.get('TRADEAI_STATE_ROOT'):
        return local
    try:
        from .lane_registry import state_root
        if root.resolve() == Path(state_root()).resolve():
            return None
    except Exception:
        pass
    return local


def snapshot(root: Path, *, policy=None, now=None, configured=None, manifest_path=None) -> dict:
    # This projection is optional enrichment for native reports. No malformed
    # policy, ledger row, timestamp or credit journal may escape into a consumer.
    try:
        now = utc(now or datetime.now(timezone.utc))
        if configured is None:
            configured, basis = configuration_evidence(
                manifest_path if manifest_path is not None else _manifest_for_root(Path(root)))
        else:
            configured, basis = bool(configured), 'explicit'
        policy = load_policy() if policy is None else policy
        return _snapshot(Path(root), policy, now, configured, basis)
    except Exception:
        return unavailable_snapshot(now=now, configured=configured)


def _snapshot(root: Path, policy: dict, now: datetime, configured: bool, basis: str) -> dict:
    order = policy['provider_order']
    if not isinstance(order, list) or not order or not all(isinstance(p, str) for p in order):
        raise ValueError('invalid provider order')
    book = CreditBook(root, policy)
    try:
        credit = book.snapshot(now=now)
        if book.path.exists():
            import fcntl
            with book.path.with_suffix('.lock').open('r') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                # Only this promotion's rows belong in its monitoring projection.
                records = [row for row in book._read()
                           if row.get('promotion_id') == policy['promotion_id']]
        else:
            records = []
    except Exception:
        credit, records = unavailable_snapshot(now=now)['credit'], []
    events, coverage = _events(root / 'data/runtime/provider_cost/events.jsonl')
    windows = {'today': now.replace(hour=0, minute=0, second=0, microsecond=0),
               'seven_days': now - timedelta(days=7)}
    failures, fallbacks = [], []
    for row in records:
        try:
            at = utc(row['at'])
            if at > now:
                continue
            if row.get('event') == 'failure' and isinstance(row.get('reason'), str):
                failures.append((at, row))
            elif row.get('event') == 'fallback' and isinstance(row.get('reason'), str):
                fallbacks.append((at, row))
        except Exception:
            coverage = 'INCOMPLETE'
    failures.sort(key=lambda item: item[0])
    fallbacks.sort(key=lambda item: item[0])
    measured = []
    for event in events:
        try:
            at = utc(event['usage_start'])
            cost = event.get('calculated_cost_usd')
            if cost is not None:
                if isinstance(cost, bool):
                    raise ValueError('invalid cost')
                cost = float(cost)
                if not math.isfinite(cost) or cost < 0:
                    raise ValueError('invalid cost')
            measured.append((at, event, cost))
        except Exception:
            coverage = 'INCOMPLETE'
            # Preserve a valid timestamp/call when its cost is unmeasured.
            try:
                measured.append((utc(event['usage_start']), event, None))
            except Exception:
                pass
    usage, models_by_period = {}, {}
    success_times = []
    for label, since in windows.items():
        selected = [(at, event, cost) for at, event, cost in measured if since <= at <= now]
        errors = [row for at, row in failures if since <= at <= now]
        missing_cost = any(cost is None for _, _, cost in selected)
        if missing_cost:
            coverage = 'INCOMPLETE'
        attempts = sum(event.get('outcome', 'success') == 'success' for _, event, _ in selected) + len(errors)
        usage[label] = {
            'calls': len(selected), 'usd': None if missing_cost else sum(cost for _, _, cost in selected),
            'failure_attempts': len(errors), 'error_rate': len(errors) / attempts if attempts else None,
        }
        models = defaultdict(lambda: {'calls': 0, 'usd': 0.0})
        for at, event, cost in selected:
            model = models[str(event.get('model') or 'unknown')]
            model['calls'] += 1
            model['usd'] = None if cost is None or model['usd'] is None else model['usd'] + cost
            if label == 'seven_days' and event.get('outcome', 'success') == 'success':
                success_times.append(at)
        models_by_period[label] = dict(models)
    last_error = failures[-1][1] if failures else None
    last_success = max(success_times, default=None)
    continuous_auth = [row for at, row in failures if row['reason'] == 'auth_failure'
                       and (last_success is None or at > last_success)]
    active = (policy.get('enabled') is True and policy.get('provider_enabled', True) is True
              and order[0] == 'anthropic' and bool(configured)
              and credit['status'] not in {'EXPIRED', 'NOT_STARTED', 'DISABLED'})
    auth_failure = active and len(continuous_auth) >= 3
    billing_failure = active and credit.get('exhausted_reason') == 'billing_error'
    critical = auth_failure or billing_failure
    status = credit['status']
    if not configured:
        status = 'NOT_CONFIGURED'
    elif status == 'OK' and (critical or last_success is None
                            or (last_error and utc(last_error['at']) > last_success)):
        status = 'DEGRADED'
    return {
        'schema': 'AnthropicProviderStatus@v1', 'provider': 'anthropic', 'status': status,
        'configured': bool(configured), 'configuration_basis': basis, 'credit': credit, 'usage': usage,
        # Preserve existing consumers of the seven-day models mapping.
        'models': models_by_period['seven_days'], 'models_by_period': models_by_period,
        'last_success_at': last_success.isoformat() if last_success else None,
        'last_error': {'code': last_error['reason'], 'at': last_error['at']} if last_error else None,
        'fallback_count': len(fallbacks),
        'fallback_reasons': dict(Counter(row['reason'] for _, row in fallbacks)),
        'last_fallback_reason': fallbacks[-1][1]['reason'] if fallbacks else credit.get('last_fallback_reason'),
        'routing_order': order if status in {'OK', 'DEGRADED'} else order[1:],
        'measurement_basis': 'canonical response events plus HTTP failure attempts; retries are attempts, not additional logical requests',
        'ledger_coverage': coverage, 'p1_continuous_failure': critical,
        'p1_auth_failure': auth_failure, 'p1_billing_failure': billing_failure,
        'probe': {'basis': 'last_real_call', 'active_probe_performed': False,
                  'last_evidence_at': max([at for at, _ in failures] + success_times, default=None).isoformat()
                  if failures or success_times else None},
        'as_of': now.isoformat(), 'offpeak': 'Promotional credit exempt; DeepSeek deferral unchanged',
        'note': policy.get('external_credit_note'),
        'credit_config': credit_config(root, policy, credit),
        'digest_line': f"Anthropic {status} · credit used ${credit.get('credit_used_usd', '?')} · remaining estimate ${credit.get('estimated_credit_remaining_usd', '?')} · UTC daily ${credit.get('today_used_usd', '?')}/${credit.get('daily_cap_usd', policy['daily_cap_usd'])} · expires {policy['expires_at']}",
    }


def admin_verification(root: Path, policy: dict) -> dict:
    """Optional Usage & Cost Admin API cross-check: key presence by NAME only, plus the last
    result file written by scripts/anthropic_cost_verify.py. Never reads a credential value."""
    cfg = policy.get('admin_cost_verification') or {}
    name = 'ANTHROPIC_ADMIN_API_KEY'  # literal env name (presence only; never the value)
    configured = cfg.get('enabled') is True and 'ANTHROPIC_ADMIN_API_KEY' in os.environ
    out = {'enabled': cfg.get('enabled') is True, 'key_name': name, 'configured': configured,
           'status': 'SKIPPED_NO_KEY' if not configured else 'NOT_RUN', 'last': None}
    try:
        last = json.loads((Path(root) / str(cfg.get('result_rel') or
                          'data/runtime/provider_cost/anthropic_admin_cost.json')).read_text(encoding='utf-8'))
        if isinstance(last, dict):
            out['last'] = {k: last.get(k) for k in ('verified_at', 'window_start', 'reported_usd',
                                                    'ledger_usd', 'delta_usd', 'status')}
            if configured:
                out['status'] = str(last.get('status') or 'UNKNOWN')
    except (OSError, ValueError, TypeError):
        pass
    return out


def credit_config(root: Path, policy: dict, credit: dict) -> dict:
    """Operator-visible credit configuration for LLM Spend and Ops Controls."""
    renewal = policy.get('renewal') or {'mode': 'one_time'}
    return {
        'daily_cap_usd': credit.get('daily_cap_usd'),
        'daily_cap_base_usd': policy.get('daily_cap_usd'),
        'daily_cap_override_active': bool(credit.get('daily_cap_override_active')),
        'daily_cap_overrides': [{k: row.get(k) for k in ('usd', 'from', 'until')}
                                for row in policy.get('daily_cap_overrides') or [] if isinstance(row, dict)],
        'renewal': {k: renewal.get(k) for k in ('mode', 'monthly_allowance_usd', 'renews_on_day')},
        'period_start': credit.get('period_start'),
        'total_cap_usd': credit.get('total_cap_usd', policy.get('total_cap_usd')),
        'models': dict(policy.get('models') or {}),
        'process_tiers': dict(policy.get('process_tiers') or {}),
        'anthropic_only_processes': sorted(policy.get('anthropic_only_processes') or {}),
        'admin_verification': admin_verification(root, policy),
    }


def digest_noteworthy(status: dict) -> bool:
    """Only material provider state or active usage can create an empty digest."""
    state = status.get('status')
    if state in {'NOT_CONFIGURED', 'EXPIRED', 'DISABLED', 'NOT_STARTED'}:
        return False
    if state in {'UNAVAILABLE', 'EXHAUSTED', 'PAUSED_TODAY'} or status.get('p1_continuous_failure'):
        return True
    if state == 'DEGRADED' and status.get('last_error'):
        return True
    today = status.get('usage', {}).get('today', {})
    return bool(today.get('calls') or today.get('failure_attempts') or today.get('usd'))


def due_notes(status: dict, policy: dict, *, paused_since=None) -> list[dict]:
    """Stable promotion-scoped notes. Only repeated auth failures may repeat."""
    try:
        return _due_notes(status, policy, paused_since=paused_since)
    except Exception:
        return []


def _due_notes(status: dict, policy: dict, *, paused_since=None) -> list[dict]:
    if status.get('status') in {'NOT_CONFIGURED', 'EXPIRED', 'DISABLED', 'NOT_STARTED'}:
        return []
    credit, result = status['credit'], []
    identity = policy['promotion_id']
    if credit.get('credit_used_usd') is not None:
        percentage = amount(credit['credit_used_usd']) / amount(policy['credit_usd']) * 100
        for threshold in policy['threshold_notes']:
            if percentage >= threshold:
                result.append({'key': f'credit-{threshold}', 'priority': 'P2', 'message': f'Anthropic promotion {identity}: {threshold}% of the granted credit used. Review LLM Spend for current usage, remaining estimate and pacing.'})
    if credit['status'] == 'EXHAUSTED':
        result.append({'key': 'exhausted', 'priority': 'P2', 'message': f'Anthropic promotion {identity}: credit exhausted. Governed routing falls through to OAuth then the admitted paid fallback. Review LLM Spend.'})
    if status.get('status') == 'UNAVAILABLE':
        result.append({'key': 'unavailable', 'priority': 'P2', 'message': f'Anthropic promotion {identity}: credit accounting unavailable; promotional calls are paused. Review LLM Spend and the operator recovery runbook.'})
    if status.get('status') == 'PAUSED_TODAY' and paused_since is not None:
        if utc(status['as_of']) - utc(paused_since) > timedelta(hours=24):
            result.append({'key': 'paused-over-24h', 'priority': 'P2', 'message': f'Anthropic promotion {identity}: daily pacing has remained paused for over 24 hours. Review unresolved authorizations and the operator recovery runbook.'})
    if 0 < credit.get('days_to_expiry', 1000) <= policy['expiry_notice_days']:
        result.append({'key': 'expiry-3-days', 'priority': 'P2', 'message': f'Anthropic promotion {identity} expires {policy["expires_at"]}; three-day renewal window. Review LLM Spend.'})
    if status.get('p1_billing_failure'):
        result.append({'key': 'billing-error', 'priority': 'P1', 'message': f'Anthropic promotion {identity}: billing rejected the promotional account. Confirm the key organization and balance before operator recovery. Review LLM Spend.'})
    if status.get('p1_auth_failure'):
        result.append({'key': 'continuous-auth', 'priority': 'P1', 'repeat_auth': True,
                       'message': f'Anthropic promotion {identity}: first choice continuously failing authentication. Review the rendered key and LLM Spend.'})
    return result


def note_is_due(note: dict, sent_at, *, now: float, auth_repeat_seconds=6 * 3600) -> bool:
    if sent_at is None:
        return True
    if note.get('repeat_auth') is not True:
        return False
    try:
        return now - float(sent_at) >= auth_repeat_seconds
    except (ValueError, TypeError):
        return True
