"""Synthetic business-proof and native n8n packet regressions; no live sources."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from scripts.lib import cio_ask_lifecycle_health as health

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / 'docs/ops/packets/ask-hourly-20261026/n8n'
NOW = datetime(2026, 10, 26, 17, 10, tzinfo=timezone.utc)
CHECKED = NOW.replace(minute=0)


def evidence():
    lifecycle = {'state': 'watching', 'monitoring_active': True,
                 'last_checked_at': CHECKED.isoformat(), 'last_answer_at': (CHECKED - timedelta(hours=1)).isoformat(),
                 'next_check_at': (CHECKED + timedelta(hours=1)).isoformat(),
                 'next_eligible_at': (CHECKED + timedelta(hours=5)).isoformat(),
                 'last_check_outcome': {'state': 'no_change'},
                 'memory_sync': {'state': 'verified'}, 'delivery': {'state': 'not_required'}}
    thread = {'thread_id': 'fixture_thread', 'entities': [{'tracking': {'state': 'tracked'}}], 'lifecycle': lifecycle}
    docs, attempts = [], []
    for lane in (health.LANE, health.EVENT_LANE):
        event = lane == health.EVENT_LANE
        run_id = f'd:{lane}:live:20261026T1300'
        summary = {'schema': health.RECEIPT_SCHEMA, 'run_id': run_id, 'mode': 'live', 'dry_run': False,
                   'ok': True, 'observed_at': (NOW if event else CHECKED).isoformat(),
                   'checked_count': 0 if event else 1, 'research_count': 0, 'no_change_count': 0 if event else 1,
                   'blocked_count': 0, 'failed_count': 0, 'deferred_count': 0, 'tracked_threads': 1,
                   'source_errors': [], 'threads': [] if event else [
                       {'thread_id': 'fixture_thread', 'lifecycle': deepcopy(lifecycle),
                        'consumer_readback': {'state': 'verified', 'answer_id': 'fixture_answer'}}]}
        attempt = {'schema': 'LaneRunReceipt@v2', 'lane_id': lane, 'run_id': run_id,
                   'mode': 'live', 'run_mode': 'live', 'status': 'ok', 'exit': 0,
                   'produced_count': 0 if event else 1, 'summary': deepcopy(summary)}
        docs.append(summary)
        attempts.append(attempt)
    return {'receipt': docs[0], 'material_receipt': docs[1], 'attempt_receipt': attempts[0],
            'material_attempt_receipt': attempts[1], 'threads': {'fixture_thread': thread}, 'now': NOW}


def sync(value):
    for key, attempt in [('receipt', 'attempt_receipt'), ('material_receipt', 'material_attempt_receipt')]:
        value[attempt]['summary'] = deepcopy(value[key])


def codes(report):
    return {condition['code'] for condition in report['conditions']}


def test_full_business_chain_accepts_no_change_without_another_paid_answer():
    result = health.evaluate(**evidence())
    assert result['ok'] and result['status'] == 'OK'
    assert all(result['chain'].values())
    assert result['tracked_threads'] == 1
    assert result['threads'][0]['answer_cooldown']
    assert result['cooldown_deferred'] == 0


@pytest.mark.parametrize('part,change,expected', [
    ('memory_sync', {'state': 'pending'}, 'memory_sync_pending'),
    ('memory_sync', {'state': 'unknown'}, 'memory_sync_unverified'),
    ('delivery', {'state': 'accepted'}, 'delivery_pending'),
    ('delivery', {'state': 'failed'}, 'delivery_unverified'),
])
def test_memory_and_delivery_pending_are_independent_conditions(part, change, expected):
    value = evidence()
    for lifecycle in [value['threads']['fixture_thread']['lifecycle'], value['receipt']['threads'][0]['lifecycle']]:
        lifecycle[part] = change
    sync(value)
    result = health.evaluate(**value)
    assert codes(result) == {expected}
    assert result['status'] == 'WARN'
    assert result['chain']['thread_check']
    assert not result['chain'][part]


def test_consumer_readback_is_not_implied_by_memory_success():
    value = evidence()
    value['receipt']['threads'][0]['consumer_readback']['state'] = 'pending'
    sync(value)
    result = health.evaluate(**value)
    assert codes(result) == {'consumer_readback_unverified'}
    assert result['chain']['memory_sync'] and not result['chain']['consumer_readback']


def test_six_hour_answer_cooldown_never_hides_a_late_hourly_check():
    value = evidence()
    outcome = {'state': 'deferred', 'reason': 'answer_cooldown'}
    value['threads']['fixture_thread']['lifecycle']['last_check_outcome'] = outcome
    value['receipt']['threads'][0]['lifecycle']['last_check_outcome'] = outcome
    sync(value)
    assert health.evaluate(**value)['cooldown_deferred'] == 1
    value['now'] = CHECKED + timedelta(hours=1, minutes=15, seconds=1)
    result = health.evaluate(**value)
    assert 'hourly_check_late' in codes(result)
    assert result['threads'][0]['answer_cooldown']


def test_exact_fifteen_minute_grace_is_not_early_and_future_due_cannot_hide_staleness():
    value = evidence()
    value['now'] = CHECKED + timedelta(hours=1, minutes=15)
    assert 'hourly_check_late' not in codes(health.evaluate(**value))
    value['threads']['fixture_thread']['lifecycle']['next_check_at'] = (NOW + timedelta(days=5)).isoformat()
    value['now'] += timedelta(seconds=1)
    assert 'hourly_check_late' in codes(health.evaluate(**value))


@pytest.mark.parametrize('field', ['last_checked_at', 'last_answer_at', 'last_check_outcome'])
def test_receipt_cannot_claim_another_canonical_check_or_answer(field):
    value = evidence()
    value['receipt']['threads'][0]['lifecycle'][field] = {'state': 'different'} if field == 'last_check_outcome' else NOW.isoformat()
    sync(value)
    result = health.evaluate(**value)
    assert 'thread_check_readback_unverified' in codes(result)
    assert result['status'] == 'UNAVAILABLE'


@pytest.mark.parametrize('bad', [None, [], {'schema': 'LaneRunReceipt@v1'}, {'schema': 'old'}, {'state': 'RUN_DONE', 'mode': 'dry_run'}])
def test_missing_or_old_receipt_is_unavailable_never_healthy(bad):
    value = evidence()
    value['receipt'] = bad
    result = health.evaluate(**value)
    assert result['status'] == 'UNAVAILABLE' and not result['ok']
    assert not result['chain']['host_receipt']


def test_dry_run_run_done_cannot_advance_business_freshness():
    value = evidence()
    value['receipt'].update(dry_run=True, mode='dry_run', state='RUN_DONE')
    sync(value)
    assert 'cio-ask-lifecycle.not_live_business_evidence' in codes(health.evaluate(**value))


@pytest.mark.parametrize('mutation', [
    {'run_id': 'fixture_other_attempt'}, {'lane_id': 'fixture_other_lane'}, {'exit': True},
    {'exit': 1}, {'status': 'failed'}, {'run_mode': 'dry_run'}, {'schema': 'LaneRunReceipt@v1'},
])
def test_immutable_attempt_must_match_the_exact_successful_live_host_attempt(mutation):
    value = evidence()
    value['attempt_receipt'].update(mutation)
    assert 'cio-ask-lifecycle.host_attempt_unverified' in codes(health.evaluate(**value))


def test_manual_run_is_not_native_schedule_proof():
    value = evidence()
    value['receipt']['run_id'] = value['attempt_receipt']['run_id'] = 'fixture_manual'
    sync(value)
    assert 'cio-ask-lifecycle.trigger_identity_unverified' in codes(health.evaluate(**value))


@pytest.mark.parametrize('key,bad', [('checked_count', True), ('tracked_threads', -1), ('failed_count', '0')])
def test_malformed_counts_are_not_a_healthy_zero(key, bad):
    value = evidence()
    value['receipt'][key] = bad
    sync(value)
    assert 'cio-ask-lifecycle.receipt_counts_unavailable' in codes(health.evaluate(**value))


def test_missing_material_schedule_and_nonempty_source_errors_are_visible():
    value = evidence()
    value['material_receipt'] = None
    assert 'cio-ask-material-events.receipt_missing' in codes(health.evaluate(**value))
    value = evidence()
    value['receipt']['source_errors'] = ['fixture_unavailable_source']
    sync(value)
    assert 'cio-ask-lifecycle.source_errors' in codes(health.evaluate(**value))


def test_material_feed_poll_gets_its_own_fifteen_minute_deadline():
    value = evidence()
    value['now'] = NOW + timedelta(minutes=15, seconds=1)
    result = health.evaluate(**value)
    assert codes(result) == {'cio-ask-material-events.receipt_late'}
    assert not result['chain']['host_receipt']


def test_tracked_legacy_thread_without_lifecycle_is_unavailable():
    value = evidence()
    value['threads']['fixture_thread'].pop('lifecycle')
    assert 'lifecycle_unavailable' in codes(health.evaluate(**value))


def test_untracked_threads_require_no_business_activity_but_still_require_real_receipts():
    value = evidence()
    value['threads']['fixture_thread']['lifecycle']['monitoring_active'] = False
    value['threads']['fixture_thread']['entities'][0]['tracking']['state'] = 'untracked'
    for key in ['receipt', 'material_receipt']:
        value[key].update(checked_count=0, no_change_count=0, tracked_threads=0, threads=[])
    sync(value)
    assert health.evaluate(**value)['ok']
    value['receipt'] = None
    assert not health.evaluate(**value)['ok']


def test_collectors_are_injected_and_read_only_with_hidden_postgres(monkeypatch, tmp_path):
    value = evidence()
    monkeypatch.setitem(sys.modules, 'psycopg2', None)
    monkeypatch.setitem(sys.modules, 'db_adapter', None)
    def reader(path):
        assert str(path).startswith(str(tmp_path))
        lane = health.EVENT_LANE if health.EVENT_LANE in str(path) else health.LANE
        key = 'material_' if lane == health.EVENT_LANE else ''
        return value[key + ('attempt_receipt' if 'lane_attempts' in str(path) else 'receipt')]
    result = health.collect_cio_ask_lifecycle_health(root=tmp_path, now=NOW,
        thread_reader=lambda: value['threads'], receipt_reader=reader)
    assert result['ok']
    assert not list(tmp_path.iterdir())


def test_ci_default_collector_never_inspects_host_stores(monkeypatch):
    monkeypatch.setenv('TRADE_AI_CI', '1')
    monkeypatch.delenv('TRADEAI_STATE_ROOT', raising=False)
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.setattr(health, '_read', lambda p: pytest.fail('unexpected host read'))
    result = health.collect_cio_ask_lifecycle_health(now=NOW)
    assert result['status'] == 'UNAVAILABLE'
    assert result['firing'] == ['fixture_root_required']


def test_missing_or_corrupt_canonical_ledger_does_not_become_a_healthy_empty_queue(tmp_path):
    result = health.collect_cio_ask_lifecycle_health(root=tmp_path, now=NOW)
    assert result['status'] == 'UNAVAILABLE'
    assert not list(tmp_path.iterdir())
    path = tmp_path / 'data/cio/cio_ask_events.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text('[]\n')
    assert health.collect_cio_ask_lifecycle_health(root=tmp_path, now=NOW)['status'] == 'UNAVAILABLE'


def test_cli_dry_run_is_write_free_and_strict_findings_have_exit_three(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/cio_ask_lifecycle_health.py'),
        '--root', str(tmp_path), '--now', NOW.isoformat(), '--dry-run', '--strict'],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)['status'] == 'UNAVAILABLE'
    assert not list(tmp_path.iterdir())


def test_registered_research_probe_invokes_injected_business_collector(monkeypatch):
    from scripts.lib import research_lane_health as research
    for name in ['OVERNIGHT', 'PIN', 'DRIVE', 'COVERAGE_STALL', 'REGISTRY', 'SEARCH', 'CIO_HERMES']:
        monkeypatch.setenv('RESEARCH_LANE_HEALTH_' + name, '0')
    monkeypatch.setattr(research, 'EXTERNAL_AUTO_LANES', ())
    monkeypatch.setattr(research, 'EXTERNAL_MANUAL_LANES', ())
    identity = ModuleType('scripts.lib.identity_health')
    identity.collect_identity_health = lambda **kw: {'lane': 'fixture_identity', 'ok': True, 'firing': []}
    monkeypatch.setitem(sys.modules, 'scripts.lib.identity_health', identity)
    calls = []
    def reader(**kwargs):
        calls.append(kwargs)
        return health.unavailable(now=kwargs['now'], code='fixture_pending_memory')
    # Exercise the default registration import as well as its injectable path.
    monkeypatch.setattr(health, 'collect_cio_ask_lifecycle_health', reader)
    report = research.collect_report(now=NOW)
    assert calls == [{'now': NOW}]
    assert health.LANE in report['firing']
    assert next(r for r in report['lanes'] if r['lane'] == health.LANE)['status'] == 'UNAVAILABLE'


def test_native_workflow_has_real_hourly_and_five_minute_schedule_nodes_and_authenticated_relay_only():
    workflow = json.loads((PACKET / 'workflow.native.candidate.json').read_text())
    assert workflow['active'] is False
    assert workflow['settings']['timezone'] == 'America/New_York'
    schedules = [n for n in workflow['nodes'] if n['type'] == 'n8n-nodes-base.scheduleTrigger']
    assert {n['parameters']['rule']['interval'][0]['expression'] for n in schedules} == {'0 0 * * * *', '0 */5 * * * *'}
    requests = [n for n in workflow['nodes'] if n['type'] == 'n8n-nodes-base.httpRequest']
    assert len(requests) == 4
    for request in requests:
        assert request['credentials']['httpHeaderAuth']['name'] == 'tradeai-run-relay'
        assert request['parameters']['authentication'] == 'genericCredentialType'
        assert 'TRADEAI_N8N_RUN_URL' in request['parameters']['url']
    assert not any('webhook' in n['type'].lower() or 'executeCommand' in n['type'] for n in workflow['nodes'])
    assert all('p:' not in n['parameters'].get('jsCode', '') for n in workflow['nodes'])
    for lane in [health.LANE, health.EVENT_LANE]:
        assert any('lane=' + lane in r['parameters']['url'] for r in requests)


def test_config_rows_are_packet_only_shadow_llm_and_preserve_same_lock_and_automated_identity():
    registry = json.loads((PACKET / 'lane-registry.rows.candidate.json').read_text())
    allowlist = json.loads((PACKET / 'run-allowlist.rows.candidate.json').read_text())
    assert {r['lane_id'] for r in registry} == {health.LANE, health.EVENT_LANE}
    assert {tuple(r['dispatch']['cron']) for r in registry} == {('0 * * * *',), ('*/5 * * * *',)}
    assert all(r['state'] == 'NEVER_SCHEDULED' and r['dispatch']['class'] == 'llm' for r in registry)
    assert all(r['active_days'] == list(range(7)) for r in registry)
    assert {r['lock'] for r in allowlist} == {'/tmp/cio_ask_lifecycle.lock'}
    assert all(r['live_arg'] is None and r['dry_run_arg'] == ['--dry-run'] for r in allowlist)
    assert all(r['llm_route'] == {'via': 'cio-governed-bridge', 'process_id': 'cio_ask_reanswer'} for r in allowlist)
    assert '--events-only' in next(r for r in allowlist if r['lane_id'] == health.EVENT_LANE)['command']
    admission = json.loads((PACKET / 'automated-process-admission.candidate.json').read_text())
    assert admission['operator_intent'] is False
    assert admission['process_id'] == 'cio_ask_reanswer'


def test_complete_contract_candidates_validate_without_forged_review():
    from scripts.lib.n8n_health_contracts import validate_contract
    from scripts.lib.n8n_output_verdict import validate_expected_output
    contracts = json.loads((PACKET / 'health-contracts.candidate.json').read_text())
    for contract in contracts:
        assert contract['status'] == 'DRAFT'
        assert contract['review']['reviewed_by'] is None
        assert validate_contract(contract) == []
        assert validate_expected_output(contract['expected_output']) == []
        reviewed = deepcopy(contract)
        reviewed['status'] = 'REVIEWED'
        assert validate_contract(reviewed) == []
        assert 'dry-run' in contract['evidence']['never'].lower() or 'dry_run' in contract['evidence']['never'].lower()


def test_expired_monitoring_active_flag_cannot_hide_a_still_tracked_thread():
    value = evidence()
    value['threads']['fixture_thread']['lifecycle']['monitoring_active'] = False
    value['now'] = CHECKED + timedelta(hours=1, minutes=16)
    assert 'hourly_check_late' in codes(health.evaluate(**value))


def test_string_deferred_outcome_uses_engine_cooldown_reason():
    value = evidence()
    for lifecycle in [value['threads']['fixture_thread']['lifecycle'], value['receipt']['threads'][0]['lifecycle']]:
        lifecycle.update(last_check_outcome='deferred', reason='ANSWER_COOLDOWN')
    sync(value)
    assert health.evaluate(**value)['cooldown_deferred'] == 1


def test_no_event_receipt_keeps_previous_material_thread_check_provable():
    value = evidence()
    checked = CHECKED + timedelta(minutes=5)
    canonical = value['threads']['fixture_thread']['lifecycle']
    canonical['last_checked_at'] = checked.isoformat()
    # Latest material poll has no new event/rows; the immutable 13:05 copy is proof.
    archived = deepcopy(value['material_attempt_receipt'])
    archived['run_id'] = archived['run_id'].replace('1300', '1305')
    archived['summary'].update(run_id=archived['run_id'], observed_at=checked.isoformat(),
        checked_count=1, no_change_count=1, threads=[{'thread_id': 'fixture_thread',
        'lifecycle': deepcopy(canonical), 'consumer_readback': {'state': 'verified'}}])
    value['now'] = CHECKED + timedelta(minutes=45)
    value['material_receipt']['observed_at'] = value['now'].isoformat()
    sync(value)
    result = health.evaluate(**value, thread_attempt_receipts=[archived])
    assert result['ok'], result['firing']
    archived['run_id'] = 'fixture_wrong_attempt'
    assert not health.evaluate(**value, thread_attempt_receipts=[archived])['ok']


def test_verified_consumer_must_match_the_canonical_answer_identity():
    value = evidence()
    value['threads']['fixture_thread']['turns'] = [{'answers': [{'answer_id': 'fixture_canonical_answer'}]}]
    assert 'consumer_answer_readback_mismatch' in codes(health.evaluate(**value))


@pytest.mark.parametrize('slot', ['garbage', '20260230T1300', '20261026T1301'])
def test_trigger_identity_requires_a_valid_admitted_hourly_slot(slot):
    value = evidence()
    value['receipt']['run_id'] = value['attempt_receipt']['run_id'] = 'd:' + health.LANE + ':live:' + slot
    sync(value)
    assert 'cio-ask-lifecycle.trigger_identity_unverified' in codes(health.evaluate(**value))
