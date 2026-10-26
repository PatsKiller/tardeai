"""PR2181 routing review regressions: isolated authority, independent models and legacy-route parity."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock

import pytest

from tests.test_anthropic_first_20261025 import NOW
from tests.test_bridge_oauth_llm_step_20261014 import hermetic  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def activated_policy():
    from scripts.lib.anthropic_transport import load_policy
    return dict(load_policy(), enabled=True)


def test_shipped_disabled_until_key_organization_and_canaries_are_verified():
    p = json.loads((ROOT / 'config/anthropic_credit_policy.json').read_text())
    assert p['enabled'] is False
    assert (p['total_cap_usd'], p['daily_cap_usd']) == ('190', '10')
    assert p['models']['standard'] == p['models']['high'] == 'claude-opus-5-5'
    assert p['models']['bulk'] == 'claude-haiku-5-5'
    assert not any('fable' in model for model in p['models'].values())
    assert p['pricing']['claude-sonnet-5-5']['cache_read'] == '0.10'  # current official pricing, re-fetched 2026-10-25


@pytest.mark.parametrize('state', ['disabled', 'missing_key', 'expired', 'billing', 'paused', 'corrupt'])
def test_nonusable_credit_does_not_replace_existing_route(tmp_path, state):
    from scripts.lib import anthropic_routing as promo
    from scripts.lib.anthropic_credit import CreditBook
    p = deepcopy(activated_policy())
    cfg = {'registered': True, 'anthropic_first': True, 'daily_soft_cap': 10, 'daily_cost_cap_usd': 1,
           'allowed_lanes': ['fast', 'deepseek-flash']}
    original = deepcopy(cfg)
    env, now = {'ANTHROPIC_API_KEY': True}, NOW
    book = CreditBook(tmp_path, p)
    if state == 'disabled': p['enabled'] = False
    elif state == 'missing_key': env = {}
    elif state == 'expired': now += timedelta(days=30)
    elif state == 'billing': book.record_failure('billing_error', now=NOW)
    elif state == 'paused':
        p['daily_cap_usd'] = '0.10'
        book = CreditBook(tmp_path, p)
        book.reserve('fixture', 'fixture', __import__('decimal').Decimal('0.10'), tier='bulk', now=NOW)
    else:
        book.record_failure('auth_failure', now=NOW)
        book.path.write_text('corrupt fixture')
    assert not promo.active('fixture', cfg, policy=p, env=env, now=now, root=tmp_path)
    assert cfg == original


def test_active_promotion_read_is_pure_and_has_declared_caps(tmp_path):
    from scripts.lib import anthropic_routing as p
    cfg = {'registered': True, 'anthropic_first': True, 'daily_soft_cap': 10, 'daily_cost_cap_usd': 1}
    assert p.active('fixture', cfg, policy=activated_policy(), env={'ANTHROPIC_API_KEY': True}, now=NOW, root=tmp_path)
    assert not list(tmp_path.iterdir())
    assert not p.active('fixture', {**cfg, 'daily_cost_cap_usd': None}, policy=activated_policy(), env={'ANTHROPIC_API_KEY': True}, now=NOW, root=tmp_path)


@pytest.mark.parametrize('message', ['CREDIT_UNAVAILABLE', 'CREDIT_CONFIGURATION_INVALID', 'CREDIT_PAUSED_TODAY: durable UTC cap',
    'CREDIT_EXHAUSTED: durable total cap', 'CREDIT_EXPIRED: database clock', 'COST_CAP_EXCEEDED: process cap',
    'COST_CONFIGURATION_INVALID: missing cap', 'COST_PERSISTENCE_UNAVAILABLE'])
def test_anthropic_credit_or_process_refusal_reaches_free_grok(monkeypatch, message):
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    monkeypatch.setattr(promo, 'selected_policy', lambda *a, **k: {'requested_policy': 'FAST', 'credit_tier': 'bulk'})
    monkeypatch.setattr(promo, 'configured_plan', lambda *a, **k: [
        {'provider': provider, 'policy_name': 'FAST', 'model_id': None, 'credit_tier': 'bulk'}
        for provider in ['anthropic', 'grok', 'chatgpt', 'deepseek']])
    monkeypatch.setattr(promo.FundingContext, 'record_fallback', lambda *a: None)
    attempts = []
    def generate(_prompt, **kw):
        attempts.append(kw['lane'])
        if kw['lane'] == 'anthropic': raise RuntimeError(message)
        return 'synthetic', {}
    monkeypatch.setattr(lc, 'gate_and_generate', generate)
    assert promo.generate_in_process('fixture', process_id='fixture', cfg={}, options={}) == 'synthetic'
    assert attempts == ['anthropic', 'grok']


def test_provider_pinned_processes_keep_independent_models_and_original_lanes():
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    rows = {r['id']: r for r in json.loads((ROOT/'config/llm_process_registry.json').read_text())['processes']}
    for pid in ['blind_review_runner', 'options_ensemble', 'cloud_review', 'watchlist_cio_synthesis_cron', 'rotation_grok_review', 'reporting_grok_editorial']:
        cfg = dict(rows[pid], registered=True)
        assert not promo.eligible(pid, cfg)
        assert 'anthropic' not in lc._allowed_lanes_from_registry(cfg)
    cfg = dict(rows['advisory_desk_opinion'], registered=True)
    assert lc._allowed_lanes_from_registry(cfg) == ['fast', 'deepseek-flash']


def test_explicit_cloud_lane_is_not_replaced_by_a_promotional_walk(monkeypatch):
    from scripts.lib import governed_cloud_generation as cloud
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    monkeypatch.setattr(cloud, 'via_bridge', lambda: False)
    monkeypatch.setattr(lc, '_registry_process', lambda _: {'anthropic_first': True})
    monkeypatch.setattr(promo, 'active', lambda *a, **k: pytest.fail('explicit lane must stay pinned'))
    calls = []
    monkeypatch.setitem(sys.modules, 'llm_lane', types.SimpleNamespace(available=lambda _: True,
        generate=lambda _prompt, **kw: calls.append(kw) or 'synthetic'))
    assert cloud.generate_cloud('fixture', process_id='fixture', task_summary='fixture', lanes=('grok',)) == ('synthetic', 'grok')
    assert calls[0]['metadata'] == {'provider_pinned': True}


@pytest.mark.parametrize('scope', ['process', 'global', 'question'])
def test_active_promotion_keeps_ask_cio_preprovider_budgets(monkeypatch, scope):
    from tests.test_cio_ask_process_registration_20261024 import ledger, call, transports
    from lib import anthropic_routing as promo
    monkeypatch.setattr(promo, 'active', lambda *a, **k: True)
    grok, chat, ds = transports(monkeypatch)
    params = {'process_spent': 4.99} if scope == 'process' else {'global_spent': 1.99} if scope == 'global' else {}
    with ledger(monkeypatch, **params) as seen:
        response = call(budget={'cost_ceiling_usd': 0.01} if scope == 'question' else None)
    assert response['error']['code'] == ('COST_CEILING_EXCEEDED' if scope == 'question' else 'COST_CAP_EXCEEDED')
    assert seen['reserve'].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []


def test_general_calls_use_opus_and_named_bulk_calls_use_haiku():
    from scripts.lib import anthropic_routing as promo
    policy = activated_policy()
    assert promo.tier_for('FAST', policy=policy, process_id='portfolio_ask') == 'standard'
    assert policy['models']['standard'] == 'claude-opus-5-5'
    assert promo.tier_for('FAST', policy=policy, process_id='hermes_tag_engine') == 'bulk'
    assert policy['models']['bulk'] == 'claude-haiku-5-5'
    assert promo.tier_for('PRO_THINK', policy=policy) == 'high'
    assert policy['models']['high'] == 'claude-opus-5-5'


def test_paid_fallback_cannot_subtract_old_promotional_hold_from_paid_cap(monkeypatch):
    from scripts.lib import llm_consumption as lc
    cur = MagicMock()
    cur.fetchone.return_value = ('fixture', 0.20, 'reserved', {'funding_source': 'anthropic_promotional_credit'})
    conn = MagicMock(); conn.cursor.return_value = cur
    monkeypatch.setattr(lc, 'cost_persistence_available', lambda: True)
    monkeypatch.setattr(lc, '_conn', lambda: conn)
    monkeypatch.setattr(lc, 'ledger_paid_usd_today', lambda *a, **k: 0.99)
    with pytest.raises(RuntimeError, match='COST_CAP_EXCEEDED: process cap'):
        lc.reprice_reservation(1, 'fixture', 0.30, process_config={'daily_cost_cap_usd': 1},
            global_cap=2, funding_source='mixed', paid_component_usd=0.10, credit_policy=activated_policy())
    assert conn.rollback.called and not conn.commit.called


def test_non_growing_credit_settlement_does_not_recheck_expiry(monkeypatch):
    from scripts.lib import llm_consumption as lc
    cur = MagicMock()
    cur.fetchone.side_effect = [('fixture', 0.10, 'reserved', {'funding_source': 'anthropic_promotional_credit', 'promotion_id': 'operator-promo-20261025'}), (0, 0)]
    conn = MagicMock(); conn.cursor.return_value = cur
    monkeypatch.setattr(lc, 'cost_persistence_available', lambda: True)
    monkeypatch.setattr(lc, '_conn', lambda: conn)
    monkeypatch.setattr(lc, 'ledger_paid_usd_today', lambda *a, **k: 0)
    lc.reprice_reservation(1, 'fixture', 0.05, process_config={'daily_cost_cap_usd': 1},
        global_cap=None, funding_source='anthropic_promotional_credit', paid_component_usd=0,
        credit_policy=activated_policy())
    assert conn.commit.called
    assert not any('SELECT CURRENT_TIMESTAMP >=' in c.args[0] for c in cur.execute.call_args_list)


@pytest.mark.parametrize('status,severity', [('OK', 'OK'), ('DISABLED', 'OK'), ('PAUSED_TODAY', 'WARN'), ('UNAVAILABLE', 'UNKNOWN')])
def test_platform_provider_probe_uses_injected_observation(tmp_path, status, severity):
    from scripts.lib import platform_health as ph
    report = {'status': status, 'as_of': NOW.isoformat(), 'credit': {}, 'usage': {}, 'p1_continuous_failure': False}
    deps = ph.Deps(state_root=tmp_path, now=lambda: NOW, extra={'anthropic_reader': lambda *a, **k: report})
    row, = ph.probe_anthropic(deps)
    assert row['status'] == severity and row['id'] == 'providers.anthropic'
    assert row['as_of'] == NOW.isoformat()


def test_inbox_provider_rule_preserves_failure_priority_and_unknown_evidence():
    from scripts.lib import needs_action as na
    assert na.rule_anthropic({'status': 'DISABLED'}, NOW) == []
    assert na.rule_anthropic({'status': 'EXPIRED'}, NOW) == []
    assert na.rule_anthropic({'status': 'DEGRADED', 'p1_continuous_failure': True}, NOW)[0]['severity'] == 'P1'
    assert na.rule_anthropic({'status': 'PAUSED_TODAY'}, NOW)[0]['severity'] == 'P2'
    with pytest.raises(na.SourceUnavailable): na.rule_anthropic({'status': 'UNAVAILABLE'}, NOW)


def test_released_529_authorization_is_not_settled_as_billable_credit():
    from decimal import Decimal
    from scripts.lib.anthropic_routing import FundingContext
    context = FundingContext('fixture', {}, 1, global_cap=1, cost_ceiling=None)
    context.credit_total = Decimal('0.20'); context.projected = Decimal('0.20')
    context.finish_anthropic(Decimal(0))
    assert context.failure_cost(paid_billable=False) == (Decimal(0), Decimal(0))
    context.paid_projection = Decimal('0.05')
    assert context.failure_cost(paid_billable=False) == (Decimal(0), Decimal(0))
    assert context.failure_cost(paid_billable=True) == (Decimal('0.05'), Decimal('0.05'))


def test_active_operator_question_requires_global_cap_before_providers(monkeypatch):
    from tests.test_cio_ask_process_registration_20261024 import ledger, call, transports
    from lib import anthropic_routing as promo
    monkeypatch.setattr(promo, 'active', lambda *a, **k: True)
    grok, chat, ds = transports(monkeypatch)
    with ledger(monkeypatch) as seen:
        monkeypatch.delenv('LLM_GLOBAL_DAILY_USD_CAP', raising=False)
        result = call()
    assert result['error']['code'] == 'COST_CONFIGURATION_INVALID'
    assert seen['reserve'].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []


@pytest.mark.parametrize('tagged,new_total,new_paid,expiry_checked', [
    (True, 0.10, 0, False), (False, 0.10, 0, True), (True, 0.11, 0, True)])
def test_expiry_growth_uses_same_promotion_decimal_components(monkeypatch, tagged, new_total, new_paid, expiry_checked):
    from scripts.lib import llm_consumption as lc
    p = activated_policy()
    meta = {'funding_source': 'mixed', 'paid_component_usd': 0.02}
    if tagged: meta['promotion_id'] = p['promotion_id']
    cur = MagicMock();cur.fetchone.side_effect = [('fixture', 0.12, 'reserved', meta), (0, 0), (False,)]
    conn=MagicMock();conn.cursor.return_value=cur
    monkeypatch.setattr(lc,'cost_persistence_available',lambda:True)
    monkeypatch.setattr(lc,'_conn',lambda:conn)
    monkeypatch.setattr(lc,'ledger_paid_usd_today',lambda *a,**k:0.02)
    lc.reprice_reservation(1,'fixture',new_total,process_config={'daily_cost_cap_usd':1},
        global_cap=2,funding_source='anthropic_promotional_credit',paid_component_usd=new_paid,credit_policy=p)
    assert any('SELECT CURRENT_TIMESTAMP >=' in c.args[0] for c in cur.execute.call_args_list) is expiry_checked
    assert conn.commit.called


def test_deep_question_admission_keeps_original_high_reasoning_projection(monkeypatch):
    from tests.test_cio_ask_process_registration_20261024 import ledger, call, transports, DEPTH, bridge
    from lib import anthropic_routing as promo
    from lib import consumption_run_manual as crm
    from lib import llm_consumption as lc
    monkeypatch.setattr(promo, 'active', lambda *a, **k: True)
    grok, chat, ds = transports(monkeypatch)
    high_model = bridge.POLICY_RESOLUTION['PRO_THINK']['model_id']
    seen_models = []
    with ledger(monkeypatch) as seen:
        def project(**kw):
            seen_models.append(kw['model_id'])
            return 0.02 if kw['model_id'] == high_model else 0.001
        monkeypatch.setattr(crm, 'projected_max_cost_usd', project)
        monkeypatch.setattr(lc, 'calibrated_projected_usd', lambda pid, worst: {'projected_usd': worst})
        result = call(**bridge.caller_reasoning_options('advisory_desk', DEPTH), budget={'cost_ceiling_usd': 0.01})
    assert result['error']['code'] == 'COST_CEILING_EXCEEDED'
    assert seen_models == [high_model]
    assert seen['reserve'].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []
