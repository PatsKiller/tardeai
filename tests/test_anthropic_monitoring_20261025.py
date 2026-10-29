"""Pinned-time monitor: no provider, DB, credentials, live path or sends."""
from tests.test_anthropic_first_20261025 import activated_fixture_promotion  # noqa: F401

from datetime import timedelta
from decimal import Decimal
import json

from tests.test_anthropic_first_20261025 import NOW
from scripts.lib.anthropic_credit import CreditBook
from scripts.lib.anthropic_monitoring import snapshot, due_notes
from scripts.lib.anthropic_transport import load_policy


def test_missing_monitor_is_read_only_and_never_claims_live_success(tmp_path):
    p=dict(load_policy(),enabled=True)
    status=snapshot(tmp_path, policy=p, now=NOW, configured=False)
    assert status['status']=='NOT_CONFIGURED'
    assert status['last_success_at'] is None
    assert status['routing_order']==['grok','chatgpt','deepseek']
    assert not list(tmp_path.iterdir())
    assert snapshot(tmp_path,policy=p,now=NOW,configured=True)['status']=='DEGRADED'


def test_usage_error_and_fallback_projection_with_pinned_windows(tmp_path):
    p=dict(load_policy(),enabled=True)
    book=CreditBook(tmp_path,p)
    book.record_failure('auth_failure',now=NOW-timedelta(hours=1))
    book.record_fallback('AUTH_FAILURE',now=NOW-timedelta(minutes=30))
    path=tmp_path/'data/runtime/provider_cost/events.jsonl'
    row={'provider':'anthropic','usage_start':NOW.isoformat(),'model':p['models']['bulk'],
         'calculated_cost_usd':0.012,'is_test':False}
    path.write_text(json.dumps(row)+'\n')
    status=snapshot(tmp_path,policy=p,now=NOW,configured=True)
    assert status['usage']['today']=={'calls':1,'usd':0.012,'failure_attempts':1,'error_rate':0.5}
    assert status['status']=='OK'
    assert status['last_fallback_reason']=='AUTH_FAILURE'
    assert status['fallback_count']==1
    assert status['models'][p['models']['bulk']]['usd']==0.012
    assert not status['p1_continuous_failure']


def test_continuous_auth_and_premature_billing_use_p1(tmp_path):
    p=dict(load_policy(),enabled=True)
    book=CreditBook(tmp_path,p)
    for _ in range(3): book.record_failure('auth_failure',now=NOW)
    status=snapshot(tmp_path,policy=p,now=NOW,configured=True)
    assert due_notes(status,p)[0]['priority']=='P1'
    billing=tmp_path/'billing'
    CreditBook(billing,p).record_failure('billing_error',now=NOW)
    notes=due_notes(snapshot(billing,policy=p,now=NOW,configured=True),p)
    assert {n['priority'] for n in notes}=={'P1','P2'}


def test_milestone_keys_are_stable_and_expiry_is_independent(tmp_path):
    p=dict(load_policy(),enabled=True)
    p['daily_cap_usd']='190';p['per_call_caps_usd']['bulk']='190'
    book=CreditBook(tmp_path,p)
    book.reserve('fixture','fixture-process',Decimal(165),tier='bulk',now=NOW)
    book.settle('fixture',Decimal(165),now=NOW)
    later=NOW+timedelta(days=19)
    status=snapshot(tmp_path,policy=p,now=later,configured=True)
    assert {n['key'] for n in due_notes(status,p)}=={'credit-50','credit-80','expiry-3-days'}
    assert due_notes(status,p)==due_notes(status,p)


def test_corrupt_accounting_never_becomes_zero_healthy_credit(tmp_path):
    p=dict(load_policy(),enabled=True);book=CreditBook(tmp_path,p)
    book.record_failure('rate_limited',now=NOW)
    book.path.write_text('broken')
    status=snapshot(tmp_path,policy=p,now=NOW,configured=True)
    assert status['status']=='UNAVAILABLE'
    assert 'credit_used_usd' not in status['credit']


def test_unknown_cost_never_becomes_a_measured_zero(tmp_path):
    p=dict(load_policy(),enabled=True);path=tmp_path/'data/runtime/provider_cost/events.jsonl';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'provider':'anthropic','usage_start':NOW.isoformat(),'model':'fixture','outcome':'possibly_billable_attempt','calculated_cost_usd':None})+'\n')
    status=snapshot(tmp_path,policy=p,now=NOW,configured=True)
    assert status['usage']['today']['usd'] is None
    assert status['models']['fixture']['usd'] is None
    assert status['ledger_coverage']=='INCOMPLETE'
    assert status['last_success_at'] is None
    assert status['usage']['today']['error_rate'] is None


def test_disabled_provider_does_not_page_as_configured_first_failure(tmp_path):
    p=dict(load_policy(),enabled=True);book=CreditBook(tmp_path,p)
    book.record_failure('billing_error',now=NOW)
    p['provider_enabled']=False
    status=snapshot(tmp_path,policy=p,now=NOW,configured=True)
    assert not status['p1_continuous_failure']


def test_milestone_messages_are_stable_for_notification_intent_dedupe(tmp_path):
    p=dict(load_policy(),enabled=True);p['daily_cap_usd']='190';p['per_call_caps_usd']['bulk']='190'
    book=CreditBook(tmp_path,p)
    book.reserve('a','fixture',Decimal(110),tier='bulk',now=NOW);book.settle('a',Decimal(110),now=NOW)
    first=due_notes(snapshot(tmp_path,policy=p,now=NOW,configured=True),p)
    book.reserve('b','fixture',Decimal(1),tier='bulk',now=NOW);book.settle('b',Decimal(1),now=NOW)
    later=due_notes(snapshot(tmp_path,policy=p,now=NOW+timedelta(minutes=5),configured=True),p)
    assert first==later
    assert p['milestone_dedupe_minutes']>22*24*60


def test_latest_unrecovered_transient_failure_is_degraded_not_exhausted(tmp_path):
    p=dict(load_policy(),enabled=True);book=CreditBook(tmp_path,p);book.record_failure('rate_limited',now=NOW)
    path=tmp_path/'data/runtime/provider_cost/events.jsonl'
    path.write_text(json.dumps({'provider':'anthropic','usage_start':(NOW-timedelta(minutes=5)).isoformat(),'model':'fixture','calculated_cost_usd':0.001})+'\n')
    result=snapshot(tmp_path,policy=p,now=NOW,configured=True)
    assert result['status']=='DEGRADED' and result['credit']['status']=='OK'
    assert not result['p1_continuous_failure']
