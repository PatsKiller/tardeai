"""In-process entry authority/fallback, isolated from DB/network/dotenv."""
from tests.test_anthropic_first_20261025 import activated_fixture_promotion  # noqa: F401

from unittest.mock import MagicMock
import sys
import types

import pytest

from tests.test_anthropic_first_20261025 import NOW


def test_cloud_helper_does_not_require_an_oauth_lane_before_promotion(monkeypatch):
    from scripts.lib import governed_cloud_generation as cloud
    from scripts.lib import llm_consumption as lc
    monkeypatch.setattr(cloud,'via_bridge',lambda:False)
    from scripts.lib import anthropic_routing as promo
    monkeypatch.setattr(promo,'active',lambda *a,**k:True)
    cfg={'registered':True,'anthropic_first':True,'allowed_lanes':['fast','anthropic','grok','chatgpt']}
    monkeypatch.setattr(lc,'_registry_process',lambda _:cfg)
    monkeypatch.setattr(lc,'get_process_config',lambda _:cfg)
    called=MagicMock(return_value=('synthetic answer',{'provider':'anthropic'}))
    monkeypatch.setattr(lc,'gate_and_generate',called)
    monkeypatch.setitem(sys.modules,'llm_lane',types.SimpleNamespace(available=lambda _:pytest.fail('OAuth prefilter ran')))
    assert cloud.generate_cloud('synthetic',process_id='fixture',task_summary='fixture',manual_trigger=True)==('synthetic answer','anthropic')
    assert called.call_args.kwargs['manual_trigger'] is True


def test_inprocess_router_falls_through_provider_errors_but_stops_on_manual_refusal(monkeypatch):
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    from scripts.lib.anthropic_transport import AnthropicError
    cfg={'registered':True,'anthropic_first':True,'allowed_lanes':['anthropic','grok','chatgpt','fast']}
    monkeypatch.setattr(promo,'selected_policy',lambda *a,**k:{'requested_policy':'FAST','credit_tier':'bulk'})
    monkeypatch.setattr(promo,'configured_plan',lambda *a,**k:[{'provider':p,'policy_name':'FAST','model_id':None,'credit_tier':'bulk'} for p in ['anthropic','grok','chatgpt','deepseek']])
    monkeypatch.setattr(promo.FundingContext,'record_fallback',lambda *a:None)
    attempts=[]
    def call(_prompt,**kwargs):
        attempts.append(kwargs['lane'])
        if len(attempts)==1:raise AnthropicError('RATE_LIMITED')
        if len(attempts)==2:return '',{}
        return 'synthetic',{}
    monkeypatch.setattr(lc,'gate_and_generate',call)
    text,prov=promo.generate_in_process('synthetic',process_id='fixture',cfg=cfg,options={'return_provenance':True})
    assert attempts==['anthropic','grok','chatgpt'] and prov['provider']=='chatgpt'
    def manual(*a,**k):raise lc.ManualRequired('fixture','anthropic','fixture','synthetic')
    monkeypatch.setattr(lc,'gate_and_generate',manual)
    with pytest.raises(lc.ManualRequired):promo.generate_in_process('synthetic',process_id='fixture',cfg=cfg,options={})


def test_paid_reprice_is_required_before_last_resort_and_missing_global_cap_refuses(monkeypatch):
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    from scripts.lib import consumption_run_manual as crm
    cfg={'max_input_tokens':1000,'max_output_tokens':100,'daily_cost_cap_usd':1}
    context=promo.FundingContext('fixture',cfg,1,global_cap=None,cost_ceiling=None)
    monkeypatch.setattr(crm,'projected_max_cost_usd',lambda **kw:0.02)
    monkeypatch.setattr(lc,'calibrated_projected_usd',lambda *a:{'projected_usd':0.02})
    def reprice(*a,**kw):
        assert kw['paid_component_usd']==0.02
        if kw['global_cap'] is None:raise RuntimeError('COST_CONFIGURATION_INVALID: global daily USD cap required')
    monkeypatch.setattr(lc,'reprice_reservation',reprice)
    with pytest.raises(RuntimeError,match='COST_CONFIGURATION_INVALID'):
        context.authorize_candidate({'provider':'deepseek','model_id':'fixture-model'})


@pytest.mark.parametrize('total,day,expired,reason',[(189.99,0,False,'CREDIT_EXHAUSTED'),(0,9.99,False,'CREDIT_PAUSED_TODAY'),(0,0,True,'CREDIT_EXPIRED')])
def test_durable_db_backstop_refuses_even_if_local_journal_was_lost(monkeypatch,total,day,expired,reason):
    from scripts.lib import llm_consumption as lc
    from scripts.lib.anthropic_transport import load_policy
    cur=MagicMock()
    cur.fetchone.side_effect=[('fixture',0,'reserved',{}),(total,day),(expired,)]
    conn=MagicMock();conn.cursor.return_value=cur
    monkeypatch.setattr(lc,'cost_persistence_available',lambda:True)
    monkeypatch.setattr(lc,'_conn',lambda:conn)
    monkeypatch.setattr(lc,'ledger_paid_usd_today',lambda *a,**k:0)
    with pytest.raises(RuntimeError,match=reason):
        lc.reprice_reservation(1,'fixture',0.02,process_config={'daily_cost_cap_usd':1},
            global_cap=None,funding_source='anthropic_promotional_credit',paid_component_usd=0,credit_policy={**load_policy(),'daily_cap_overrides':[]})
    assert conn.rollback.called and not conn.commit.called
    assert 'pg_advisory_xact_lock' in cur.execute.call_args_list[0].args[0]
    assert not any('UPDATE llm_cost_reservations SET projected' in c.args[0] for c in cur.execute.call_args_list)


def test_native_free_fallback_keeps_request_cap_without_using_paid_pool(monkeypatch):
    from scripts.lib import llm_consumption as lc
    import lib.oauth_lane_status as oauth
    cfg={'registered':True,'anthropic_first':True,'mode':'automated','allowed_lanes':['anthropic','grok','chatgpt'],
         'max_input_tokens':100,'max_output_tokens':100,'daily_soft_cap':10,'daily_cost_cap_usd':1}
    monkeypatch.setattr(lc,'get_process_config',lambda _:cfg)
    monkeypatch.setattr(lc,'_registry_process',lambda _:cfg)
    monkeypatch.setattr(oauth,'lane_available',lambda _:True)
    monkeypatch.setitem(sys.modules,'memory_ring2',types.SimpleNamespace(check=lambda *a,**k:{'decision':'ALLOW'},research_class=lambda *a:False))
    monkeypatch.setitem(sys.modules,'model_chooser',types.SimpleNamespace(apply=lambda *a,**k:('grok',{})))
    monkeypatch.setitem(sys.modules,'llm_lane',types.SimpleNamespace(generate=lambda *a,**k:('synthetic',{'_tradeai':{},'usage':{}})))
    check=MagicMock(side_effect=lambda *a,**k:{'allow':k['global_cap'] is None})
    reserve=MagicMock(return_value=42);settle=MagicMock()
    monkeypatch.setattr(lc,'check_cost_cap',check);monkeypatch.setattr(lc,'reserve_projected_cost',reserve)
    monkeypatch.setattr(lc,'settle_reservation',settle);monkeypatch.setattr(lc,'log_call',MagicMock())
    monkeypatch.setenv('LLM_GLOBAL_DAILY_USD_CAP','0.01')
    assert lc.gate_and_generate('synthetic',lane='grok',process_id='fixture',_anthropic_route=True)=='synthetic'
    assert check.call_args.kwargs['global_cap'] is None
    assert reserve.call_args.args[1]==0 and reserve.call_args.kwargs['global_cap'] is None
    assert settle.call_args.args[0]==42


def test_missing_credit_admission_keeps_existing_free_routes(monkeypatch):
    from scripts.lib import anthropic_routing as r
    p=r.load_policy();cfg={'registered':True,'anthropic_first':True,'allowed_lanes':['anthropic','grok','chatgpt']}
    plan=r.configured_plan('fixture',cfg,{'requested_policy':'FAST'},enabled={'grok','chatgpt','deepseek'},
        model_for_provider=lambda p,t:p,env={'ANTHROPIC_API_KEY':'synthetic'},now=NOW,policy=p)
    assert plan[0]['skip']=='process_caps_not_admitted'
    assert plan[1]['provider']=='grok' and plan[1]['skip'] is None
    assert not r.credit_admitted(cfg)
    assert r.credit_admitted(dict(cfg,daily_soft_cap=10,daily_cost_cap_usd=0.1))


def test_legacy_unregistered_sentinel_has_no_new_provider_authority():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    row=next(r for r in json.loads((root/'config/llm_process_registry.json').read_text())['processes'] if r['id']=='unregistered')
    assert 'anthropic_first' not in row and 'allowed_lanes' not in row
