"""Review regressions: synthetic evidence, no host env/manifest, DB, sockets or sends."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from scripts.lib import anthropic_monitoring as monitoring
from scripts.lib.anthropic_credit import CreditBook
from scripts.lib.anthropic_transport import load_policy

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 25, 18, tzinfo=timezone.utc)


@pytest.fixture
def policy():
    value = load_policy()
    value['enabled'] = True
    value['provider_enabled'] = True
    return value


def event(at=NOW, model='fixture-haiku', cost=0.01):
    return {'provider': 'anthropic', 'usage_start': at.isoformat(),
            'model': model, 'calculated_cost_usd': cost, 'is_test': False}


def ledger(root, rows):
    path = root / 'data/runtime/provider_cost/events.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return path


def function(path, name, namespace):
    """Load only a pure function: skip script-level env/bootstrap/client imports."""
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def modules(monkeypatch, tmp_path):
    lib = ModuleType('lib')
    lib.__path__ = []
    route = ModuleType('lib.anthropic_routing')
    route.state_root = lambda: tmp_path
    monkeypatch.setitem(sys.modules, 'lib', lib)
    monkeypatch.setitem(sys.modules, 'lib.anthropic_monitoring', monitoring)
    monkeypatch.setitem(sys.modules, 'lib.anthropic_routing', route)


@pytest.mark.parametrize('bad', [{}, [], {'provider_order': None}, {'provider_order': []}])
def test_malformed_policy_returns_complete_unavailable(tmp_path, bad):
    result = monitoring.snapshot(tmp_path, policy=bad, now=NOW, configured=True)
    assert result['status'] == 'UNAVAILABLE'
    assert result['usage']['today']['usd'] is None
    assert result['credit']['remaining_is_estimated']
    assert result['digest_line']
    assert not result['p1_continuous_failure']
    assert not list(tmp_path.iterdir())


def test_policy_loader_failure_is_contained(monkeypatch, tmp_path):
    def broken():
        raise ValueError('synthetic malformed policy')
    monkeypatch.setattr(monitoring, 'load_policy', broken)
    assert monitoring.snapshot(tmp_path, now=NOW, configured=False)['status'] == 'UNAVAILABLE'


@pytest.mark.parametrize('bad', [[], None, 'not-an-object', 5])
def test_non_object_event_rows_do_not_break_projection(tmp_path, policy, bad):
    ledger(tmp_path, [bad, event(), event(NOW - timedelta(days=1), cost=0.02)])
    result = monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)
    assert result['ledger_coverage'] == 'INCOMPLETE'
    assert result['usage']['today']['calls'] == 1
    assert result['usage']['seven_days']['calls'] == 2


@pytest.mark.parametrize('cost', ['broken', float('nan'), float('inf'), -1, True])
def test_invalid_cost_is_unmeasured_instead_of_zero(tmp_path, policy, cost):
    ledger(tmp_path, [event(cost=cost)])
    result = monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)
    assert result['ledger_coverage'] == 'INCOMPLETE'
    assert result['usage']['today']['usd'] is None
    assert result['models_by_period']['today']['fixture-haiku']['usd'] is None


def test_non_object_credit_journal_is_contained(tmp_path, policy):
    book = CreditBook(tmp_path, policy)
    book.path.parent.mkdir(parents=True)
    book.path.write_text('[]\n')
    book.path.with_suffix('.lock').touch()
    assert monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)['status'] == 'UNAVAILABLE'


def test_configured_uses_names_only_manifest_even_without_process_env(monkeypatch, tmp_path, policy):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    manifest = tmp_path / 'env.manifest.json'
    manifest.write_text(json.dumps({'shell_keys': ['ANTHROPIC_API_KEY'], 'rendered_at': NOW.isoformat()}))
    result = monitoring.snapshot(tmp_path, policy=policy, now=NOW, manifest_path=manifest)
    assert result['configured']
    assert result['configuration_basis'] == 'rendered_manifest_names'
    assert result['status'] == 'DEGRADED'
    # A valid manifest is authoritative, including explicit key removal.
    manifest.write_text(json.dumps({'shell_keys': []}))
    assert not monitoring.snapshot(tmp_path, policy=policy, now=NOW, manifest_path=manifest)['configured']


def test_temp_root_discovery_never_opens_host_manifest(monkeypatch, tmp_path, policy):
    monkeypatch.setenv('PROJECT_ROOT', str(tmp_path))
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        assert str(path).startswith(str(tmp_path)), 'unexpected read outside synthetic root'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    assert monitoring.snapshot(tmp_path, policy=policy, now=NOW)['status'] == 'NOT_CONFIGURED'


def test_model_usage_today_and_seven_days_and_fallback_reasons(tmp_path, policy):
    book = CreditBook(tmp_path, policy)
    book.record_fallback('RATE_LIMITED', now=NOW)
    book.record_fallback('RATE_LIMITED', now=NOW)
    book.record_fallback('PAUSED_TODAY', now=NOW)
    ledger(tmp_path, [event(), event(NOW - timedelta(days=1), cost=0.02)])
    result = monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)
    assert result['models_by_period']['today']['fixture-haiku'] == {'calls': 1, 'usd': 0.01}
    assert result['models_by_period']['seven_days']['fixture-haiku'] == {'calls': 2, 'usd': 0.03}
    assert result['models'] == result['models_by_period']['seven_days']
    assert result['fallback_reasons'] == {'RATE_LIMITED': 2, 'PAUSED_TODAY': 1}
    assert result['probe']['basis'] == 'last_real_call'
    assert not result['probe']['active_probe_performed']


def test_ledger_cache_reuses_unchanged_file_and_invalidates_append_replace(monkeypatch, tmp_path, policy):
    path = ledger(tmp_path, [event()])
    original, reads = Path.open, []
    def counted(file, *args, **kwargs):
        if file == path:
            reads.append(file)
        return original(file, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', counted)
    first = monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)
    second = monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)
    assert first['usage'] == second['usage']
    assert len(reads) == 1
    with original(path, 'a') as handle:
        handle.write(json.dumps(event(cost=0.02)) + '\n')
    assert monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)['usage']['today']['calls'] == 2
    assert len(reads) == 2
    replacement = path.with_suffix('.replacement')
    replacement.write_text(json.dumps(event(cost=0.04)) + '\n')
    replacement.replace(path)
    assert monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)['usage']['today']['usd'] == 0.04
    assert len(reads) == 3


def test_unavailable_and_stuck_pause_notes_are_one_shot(policy):
    result = monitoring.unavailable_snapshot(now=NOW, configured=True)
    notes = monitoring.due_notes(result, policy)
    unavailable = next(n for n in notes if n['key'] == 'unavailable')
    assert unavailable['priority'] == 'P2'
    assert monitoring.note_is_due(unavailable, None, now=NOW.timestamp())
    assert not monitoring.note_is_due(unavailable, NOW.timestamp(), now=NOW.timestamp() + 7 * 86400)
    result['status'] = result['credit']['status'] = 'PAUSED_TODAY'
    assert not monitoring.due_notes(result, policy, paused_since=NOW - timedelta(hours=24))
    paused = monitoring.due_notes(result, policy, paused_since=NOW - timedelta(hours=24, seconds=1))
    assert [n['key'] for n in paused] == ['paused-over-24h']
    assert paused[0]['priority'] == 'P2'


def publisher(monkeypatch, tmp_path, policy):
    modules(monkeypatch, tmp_path)
    state, sent, clock = {}, [], [NOW.timestamp()]
    def save(value):
        state.clear()
        state.update(deepcopy(value))
    ns = {'datetime': datetime, 'timezone': timezone, 'time': SimpleNamespace(time=lambda: clock[0]),
          'DEDUPE_SECONDS': 21600, '_load_state': lambda: deepcopy(state), '_save_state': save,
          '_deliver': lambda message, priority, heartbeat, keys, **kwargs: sent.append((priority, keys[0], kwargs)) or True}
    return function('scripts/check_llm_provider_health.py', '_publish_anthropic_notes', ns), state, sent, clock


def test_billing_p1_once_per_promotion_auth_only_repeats_after_six_hours(monkeypatch, tmp_path, policy):
    publish, state, sent, clock = publisher(monkeypatch, tmp_path, policy)
    book = CreditBook(tmp_path, policy)
    book.record_failure('billing_error', now=NOW)
    result = monitoring.snapshot(tmp_path, policy=policy, now=NOW, configured=True)
    publish(result, policy, {})
    clock[0] += 7 * 3600
    publish(result, policy, {})
    assert len([n for n in sent if n[0] == 'P1']) == 1
    assert sent[1][1].endswith(':billing-error')
    assert sent[1][2]['dedupe_minutes'] >= 22 * 24 * 60
    # A separate synthetic promotion's auth failure keeps the native repeat cadence.
    auth_root = tmp_path / 'auth'
    auth = CreditBook(auth_root, policy)
    for _ in range(3):
        auth.record_failure('auth_failure', now=NOW)
    result = monitoring.snapshot(auth_root, policy=policy, now=NOW, configured=True)
    publish(result, policy, {})
    clock[0] += 3600
    publish(result, policy, {})
    assert len([n for n in sent if n[1].endswith(':continuous-auth')]) == 1
    clock[0] += 5 * 3600
    publish(result, policy, {})
    assert len([n for n in sent if n[1].endswith(':continuous-auth')]) == 2


def test_provider_check_remembers_and_clears_continuous_pause(monkeypatch, tmp_path, policy):
    publish, state, sent, clock = publisher(monkeypatch, tmp_path, policy)
    result = monitoring.unavailable_snapshot(now=NOW, configured=True)
    result['status'] = result['credit']['status'] = 'PAUSED_TODAY'
    publish(result, policy, {})
    assert state['anthropic:' + policy['promotion_id'] + ':paused-since'] == NOW.isoformat()
    clock[0] += 24 * 3600 + 1
    result['as_of'] = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    publish(result, policy, {})
    assert [n[1].split(':')[-1] for n in sent] == ['paused-over-24h']
    clock[0] += 24 * 3600
    publish(result, policy, {})
    assert len(sent) == 1
    result['status'] = result['credit']['status'] = 'OK'
    publish(result, policy, {})
    assert not any(k.endswith(':paused-since') for k in state)


@pytest.mark.parametrize('state', ['NOT_CONFIGURED', 'EXPIRED', 'DISABLED', 'NOT_STARTED', 'OK', 'DEGRADED'])
def test_empty_digest_remains_quiet_without_noteworthy_provider(state):
    result = monitoring.unavailable_snapshot(now=NOW)
    result.update(status=state, last_error=None)
    assert not monitoring.digest_noteworthy(result)


def test_digest_active_usage_and_accounting_problem_are_material():
    result = monitoring.unavailable_snapshot(now=NOW)
    assert monitoring.digest_noteworthy(result)
    result.update(status='OK', last_error=None)
    result['usage']['today']['calls'] = 1
    assert monitoring.digest_noteworthy(result)
    result['status'] = 'EXPIRED'
    assert not monitoring.digest_noteworthy(result)


def digest_function(monkeypatch, tmp_path):
    modules(monkeypatch, tmp_path)
    db = ModuleType('db_adapter')
    db._execute = lambda sql, fetch: {} if fetch == 'one' else []
    metrics = ModuleType('alert_condition_state')
    metrics.today_metrics = lambda: {'new': 0, 'recovered': 0}
    metrics.unresolved_conditions = lambda: []
    monkeypatch.setitem(sys.modules, 'db_adapter', db)
    monkeypatch.setitem(sys.modules, 'alert_condition_state', metrics)
    return function('scripts/alert_daily_digest.py', '_build_message', {})


def test_digest_caller_survives_projection_failure_and_preserves_other_reports(monkeypatch, tmp_path):
    build = digest_function(monkeypatch, tmp_path)
    def broken(*args, **kwargs):
        raise AttributeError('synthetic projection failure')
    monkeypatch.setattr(monitoring, 'snapshot', broken)
    result = build()
    assert result.startswith('🗞 Alert Digest')
    assert 'Anthropic UNAVAILABLE' in result


def test_digest_caller_returns_none_for_empty_not_configured(monkeypatch, tmp_path):
    build = digest_function(monkeypatch, tmp_path)
    result = monitoring.unavailable_snapshot(now=NOW)
    result['status'] = 'NOT_CONFIGURED'
    monkeypatch.setattr(monitoring, 'snapshot', lambda *a, **k: result)
    assert build() is None


def test_runtime_health_caller_survives_projection_failure(monkeypatch, tmp_path):
    modules(monkeypatch, tmp_path)
    def broken(*args, **kwargs):
        raise KeyError('synthetic projection failure')
    monkeypatch.setattr(monitoring, 'snapshot', broken)
    ns = {'datetime': datetime, 'timezone': timezone,
          '_get_json': lambda url: {'wiring': {'read_api': {'state': 'CONNECTED'}, 'dispatch': {'state': 'WIRED'}}}}
    collect = function('scripts/agent_runtime/health_monitor.py', 'collect', ns)
    result = collect('http://synthetic.invalid')
    assert result['state'] == 'DEGRADED'
    assert len(result['checks']) >= 4
    provider = next(c for c in result['checks'] if c['check'] == 'anthropic_provider')
    assert provider['provider_state'] == 'UNAVAILABLE'
    assert provider['status'] == 'WARN'
