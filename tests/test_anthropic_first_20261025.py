"""Anthropic promotional routing: isolated authorization, accounting and fallback proof."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib
import json

import pytest


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def modules():
    return (importlib.import_module("scripts.lib.anthropic_credit"),
            importlib.import_module("scripts.lib.anthropic_transport"))


def policy(**updates):
    return {
        "enabled": True, "promotion_id": "fixture-promo", "credit_usd": "200",
        "total_cap_usd": "190", "daily_cap_usd": "10",
        "starts_at": "2026-10-25T00:00:00Z", "expires_at": "2026-11-16T00:00:00Z",
        "per_call_caps_usd": {"bulk": "0.10", "standard": "0.25", "high": "0.50"},
        "retry": {"max_attempts": 2, "max_delay_seconds": 0}, **updates,
    }


def test_credit_holds_are_atomic_and_cannot_exceed_daily_cap(tmp_path):
    credit, _ = modules()
    book = credit.CreditBook(tmp_path, policy())
    def reserve(n):
        try:
            return book.reserve(str(n), "fixture-process", Decimal("0.10"), tier="bulk", now=NOW)
        except credit.CreditDenied:
            return None
    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = [x for x in pool.map(reserve, range(140)) if x is not None]
    assert len(accepted) == 100
    snap = book.snapshot(now=NOW)
    assert Decimal(snap["reserved_usd"]) == Decimal("10")
    assert snap["status"] == "PAUSED_TODAY"


def test_total_cap_expiry_and_pending_previous_day_are_binding(tmp_path):
    credit, _ = modules()
    book = credit.CreditBook(tmp_path, policy(total_cap_usd="0.20"))
    for n in range(2):
        book.reserve(str(n), "fixture-process", Decimal("0.10"), tier="bulk", now=NOW)
        book.settle(str(n), Decimal("0.10"), now=NOW)
    with pytest.raises(credit.CreditDenied, match="EXHAUSTED"):
        book.reserve("over", "fixture-process", Decimal("0.01"), tier="bulk", now=NOW)
    assert book.snapshot(now=NOW)["remaining_budget_usd"] == "0.00"
    later = datetime(2026, 11, 16, tzinfo=timezone.utc)
    with pytest.raises(credit.CreditDenied, match="EXPIRED"):
        credit.CreditBook(tmp_path / "expiry", policy()).reserve("expired", "x", Decimal("0.01"), tier="bulk", now=later)
    day = credit.CreditBook(tmp_path / "days", policy(daily_cap_usd="0.10"))
    day.reserve("held", "x", Decimal("0.10"), tier="bulk", now=NOW)
    with pytest.raises(credit.CreditDenied, match="PAUSED_TODAY"):
        day.reserve("next", "x", Decimal("0.01"), tier="bulk", now=NOW + timedelta(days=1))
    day.settle("held", Decimal("0.04"), now=NOW + timedelta(days=1))
    day.reserve("next", "x", Decimal("0.06"), tier="bulk", now=NOW + timedelta(days=1))


def test_corrupt_journal_and_changed_policy_refuse_instead_of_resetting(tmp_path):
    credit, _ = modules()
    book = credit.CreditBook(tmp_path, policy())
    book.reserve("one", "x", Decimal("0.02"), tier="bulk", now=NOW)
    with book.path.open("a") as f:
        f.write('{"broken":')
    with pytest.raises(credit.CreditDenied, match="UNAVAILABLE"):
        book.reserve("two", "x", Decimal("0.02"), tier="bulk", now=NOW)


def test_settlement_is_idempotent_and_ambiguous_usage_keeps_its_hold(tmp_path):
    credit, _ = modules()
    book = credit.CreditBook(tmp_path, policy())
    book.reserve("one", "x", Decimal("0.10"), tier="bulk", now=NOW)
    book.settle("one", None, now=NOW)
    assert book.snapshot(now=NOW)["reserved_usd"] == "0.10"
    book.settle("one", Decimal("0.03"), now=NOW)
    size = book.path.stat().st_size
    book.settle("one", Decimal("0.03"), now=NOW)
    assert book.path.stat().st_size == size
    with pytest.raises(credit.CreditDenied, match="CONFLICT"):
        book.settle("one", Decimal("0.04"), now=NOW)


def test_billing_state_is_durable_but_rate_limits_do_not_exhaust_credit(tmp_path):
    credit, _ = modules()
    book = credit.CreditBook(tmp_path, policy())
    book.record_failure("rate_limited", now=NOW)
    assert book.snapshot(now=NOW)["status"] == "OK"
    book.record_failure("billing_error", now=NOW)
    assert credit.CreditBook(tmp_path, policy()).snapshot(now=NOW)["status"] == "EXHAUSTED"


def test_usage_prices_all_token_classes_and_haiku_context_boundary():
    _, transport = modules()
    prices = {"input": "2", "output": "10", "cache_read": "0.1", "cache_write_5m": "2.5", "cache_write_1h": "4", "batch_multiplier": "0.5"}
    usage = {"input_tokens": 1000, "output_tokens": 200,
             "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 500,
             "cache_creation": {"ephemeral_5m_input_tokens": 200, "ephemeral_1h_input_tokens": 300}}
    assert transport.price_usage(usage, prices) == Decimal("0.0060")
    assert transport.price_usage(usage, prices, batch=True) == Decimal("0.00300")
    with pytest.raises(ValueError):
        transport.price_usage({"input_tokens": -1, "output_tokens": 1}, prices)


def test_missing_key_performs_no_budget_write_or_http_call(tmp_path):
    credit, transport = modules()
    book = credit.CreditBook(tmp_path, policy())
    def never(*_a, **_k):
        pytest.fail("missing-key path reached network")
    adapter = transport.AnthropicTransport(book=book, env={}, request=never, now=lambda: NOW)
    with pytest.raises(transport.AnthropicError, match="NOT_CONFIGURED"):
        adapter.generate([{"role": "user", "content": "synthetic"}], "claude-haiku-5-5", max_tokens=10, client_request_id="missing")
    assert not book.path.exists()


def test_pricing_source_is_config_and_requested_model_ids_are_current():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    p = json.loads((root / "config/anthropic_credit_policy.json").read_text())
    assert p["total_cap_usd"] == "190" and p["daily_cap_usd"] == "10"
    assert set(p["models"].values()) == {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}
    assert p["expires_at"] == "2026-11-16T00:00:00Z"


def adapter_fixture(tmp_path, responses, *, record=None):
    credit, transport = modules()
    p = transport.load_policy()
    book = credit.CreditBook(tmp_path, p)
    calls, holds, settles, events = [], [], [], []
    def request(method, path, payload, **kwargs):
        calls.append((method, path, payload))
        if path.endswith('count_tokens'):
            return 200, {'input_tokens': 10}, {}
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response
    def meter(*args):
        events.append(args)
        return True if record is None else record
    client = transport.AnthropicTransport(book=book, env={'ANTHROPIC_API_KEY': 'synthetic-only'},
        request=request, now=lambda: NOW, sleep=lambda _s: None,
        record_usage=meter, record_attempt=lambda *a: True, reserve_process=lambda *a: holds.append(a), settle_process=settles.append)
    return client, book, calls, holds, settles, events


def response():
    return 200, {'id': 'fixture-request', 'model': 'claude-haiku-5-5',
                 'content': [{'type': 'text', 'text': 'synthetic answer'}], 'stop_reason': 'end_turn',
                 'usage': {'input_tokens': 10, 'output_tokens': 5,
                           'cache_read_input_tokens': 3000, 'cache_creation_input_tokens': 2000}}, {}


def invoke(client):
    return client.generate([{'role': 'system', 'content': 'repeated synthetic policy'},
                            {'role': 'user', 'content': 'synthetic'}], 'claude-haiku-5-5',
                           max_tokens=10, client_request_id='fixture-call', process_id='fixture-process')


def test_messages_usage_is_metered_before_exact_settlement_and_cache_is_requested(tmp_path):
    client, book, calls, holds, settles, events = adapter_fixture(tmp_path, [response()])
    out = invoke(client)
    assert calls[1][2]['system'][-1]['cache_control'] == {'type': 'ephemeral'}
    assert len(holds) == len(settles) == len(events) == 1
    assert Decimal(book.snapshot(now=NOW)['credit_used_usd']) == events[0][2]
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) == 0
    assert out['_tradeai']['provider'] == 'anthropic'


@pytest.mark.parametrize('status,kind,expected', [(400,'invalid_request_error','EXHAUSTED'),
    (402,'billing_error','EXHAUSTED'), (401,'authentication_error','OK'),
    (429,'rate_limit_error','OK'), (529,'overloaded_error','OK')])
def test_http_failures_release_or_hold_and_only_billing_exhausts(tmp_path, status, kind, expected):
    _, transport = modules()
    error = (status, {'error': {'type': kind, 'message': 'credit balance too low' if status == 400 else 'redacted'}}, {})
    client, book, calls, _, _, _ = adapter_fixture(tmp_path, [error, error])
    with pytest.raises(transport.AnthropicError):
        invoke(client)
    snap = book.snapshot(now=NOW)
    assert snap['status'] == expected
    assert len(calls) == (3 if status in (429,529) else 2)
    assert (Decimal(snap['reserved_usd']) > 0) == (status >= 500)


def test_ambiguous_overload_then_success_keeps_whole_authorization(tmp_path):
    client, book, _, _, settles, events = adapter_fixture(tmp_path,
        [(529, {'error': {'type': 'overloaded_error'}}, {}), response()])
    invoke(client)
    assert events and settles == [None]
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) > events[0][2]


def test_accounting_failure_never_releases_billable_authorization(tmp_path):
    _, transport = modules()
    client, book, *_ = adapter_fixture(tmp_path, [response()], record=False)
    with pytest.raises(transport.AnthropicError, match='ACCOUNTING_UNAVAILABLE'):
        invoke(client)
    assert book.snapshot(now=NOW)['status'] == 'UNAVAILABLE'
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) > 0


def test_haiku_long_context_counts_cache_reads_and_writes():
    _, transport = modules()
    p = transport.load_policy()['pricing']['claude-haiku-5-5']
    assert transport.price_usage({'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 100000}, p) == Decimal('0.005003')


def test_plan_uses_pinned_clock_and_never_calls_provider_for_missing_key():
    from scripts.lib import anthropic_routing as r
    p = r.load_policy()
    cfg = {'registered': True, 'anthropic_first': True, 'allowed_lanes': ['anthropic','grok','chatgpt']}
    plan = r.configured_plan('fixture', cfg, {'requested_policy':'FAST'}, enabled={'grok','chatgpt','deepseek'},
        model_for_provider=lambda provider, tier: provider, policy=p, env={}, now=NOW)
    assert [x['provider'] for x in plan] == ['anthropic','grok','chatgpt','deepseek']
    assert plan[0]['skip'] == 'not_configured'
    expired = r.configured_plan('fixture', cfg, {'requested_policy':'FAST'}, enabled={'grok'},
        model_for_provider=lambda provider, tier: provider, policy=p, env={'ANTHROPIC_API_KEY':'synthetic'},
        now=datetime(2026,11,16,tzinfo=timezone.utc))
    assert expired[0]['skip'] == 'credit_expired'


def test_malformed_billable_usage_retains_hold_instead_of_releasing(tmp_path):
    _, transport=modules()
    status,body,headers=response();body['usage']['input_tokens']=-1
    client,book,*_=adapter_fixture(tmp_path,[(status,body,headers)])
    with pytest.raises(ValueError):invoke(client)
    assert Decimal(book.snapshot(now=NOW)['reserved_usd'])>0


def test_long_retry_after_falls_through_without_early_retry(tmp_path):
    _, transport=modules()
    client,book,calls,*_=adapter_fixture(tmp_path,[(429,{'error':{'type':'rate_limit_error'}},{'retry-after':'120'})])
    with pytest.raises(transport.AnthropicError,match='RATE_LIMITED'):invoke(client)
    assert len(calls)==2
    assert book.snapshot(now=NOW)['status']=='OK'


def test_explicit_async_batch_holds_until_readback_and_uses_discount(tmp_path):
    credit,transport=modules();p=transport.load_policy();book=credit.CreditBook(tmp_path,p)
    events=[];holds=[];settles=[];calls=[]
    key=book._key('fixture-batch')
    def request(method,path,payload,**kw):
        calls.append((method,path))
        if path.endswith('count_tokens'):return 200,{'input_tokens':10},{}
        if method=='POST':return 200,{'id':'msgbatch_fixture','processing_status':'in_progress'},{}
        if path.endswith('results'):
            return 200,{'results':[{'custom_id':key,'result':{'type':'succeeded','message':response()[1]}}]},{}
        return 200,{'processing_status':'ended'},{}
    def meter(*a):events.append(a);return True
    adapter=transport.AnthropicTransport(book=book,env={'ANTHROPIC_API_KEY':'synthetic'},request=request,
        now=lambda:NOW,reserve_process=lambda *a:holds.append(a),record_usage=meter,record_attempt=lambda *a:True,settle_process=settles.append)
    args=dict(client_request_id='fixture-batch',process_id='fixture-process',max_tokens=10,
              max_input_tokens=1000,process_cap=Decimal(1))
    with pytest.raises(transport.AnthropicError,match='ASYNC_CALLER_REQUIRED'):
        adapter.submit_batch([{'role':'user','content':'synthetic'}],p['models']['bulk'],**args)
    assert calls==[]
    out=adapter.submit_batch([{'role':'user','content':'synthetic'}],p['models']['bulk'],caller_allows_async=True,**args)
    assert out['status']=='PENDING'
    assert Decimal(book.snapshot(now=NOW)['reserved_usd'])>0
    result=adapter.collect_batch(out['batch_id'],client_request_id='fixture-batch',process_id='fixture-process')
    assert result['status']=='SUCCEEDED' and result['requires_native_output_validation']
    expected=transport.price_usage(response()[1]['usage'],p['pricing'][p['models']['bulk']],batch=True)
    assert events[0][2]==expected and events[0][1]['batch'] is True
    assert Decimal(book.snapshot(now=NOW)['credit_used_usd'])==expected
    assert len(holds)==1 and settles==[expected]


def test_batch_readback_refuses_a_different_process_before_http(tmp_path):
    _,transport=modules();client,_,calls,*_=adapter_fixture(tmp_path,[])
    with pytest.raises(transport.AnthropicError,match='BATCH_NOT_ADMITTED'):
        client.collect_batch('msgbatch_fixture',client_request_id='unknown',process_id='different')
    assert calls==[]


def test_real_layout_dry_run_reads_only_temp_project_configs(tmp_path,monkeypatch):
    from pathlib import Path
    import shutil
    from scripts.anthropic_routing_dry_run import report
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'config').mkdir()
    for name in ('llm_process_registry','llm_routing_policy','llm_model_registry','anthropic_credit_policy'):
        shutil.copyfile(root/f'config/{name}.json',tmp_path/f'config/{name}.json')
    observed=json.loads((root/'docs/ops/packets/anthropic-first-20261025/ledger-inventory.json').read_text())
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setenv('PROJECT_ROOT',str(tmp_path))
    rows,total=report(tmp_path,observed)
    assert len(rows)==90
    assert len([r for r in rows if r['new'].startswith('anthropic')])==81
    assert total==Decimal('0.7226378')
    assert before=={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('model', ['claude-haiku-5-5','claude-sonnet-5-5','claude-opus-5-5'])
@pytest.mark.parametrize('batch',[False,True])
def test_canonical_spend_rows_use_the_same_effective_cache_prices(model,batch):
    from scripts.lib.anthropic_transport import load_policy,price_usage
    from scripts.lib.provider_cost.pricing import calculate_usd
    usage={'input_tokens':1234,'output_tokens':2468,'cache_read_input_tokens':100001,
           'cache_creation_input_tokens':1500,
           'cache_creation':{'ephemeral_5m_input_tokens':1000,'ephemeral_1h_input_tokens':500}}
    exact=price_usage(usage,load_policy()['pricing'][model],batch=batch)
    actual=calculate_usd(provider='anthropic',model=model,at=NOW.isoformat(),
        cache_hit_input=100001,cache_miss_input=1234,output=2468,
        cache_creation_input_tokens=1500,cache_creation_1h_tokens=500,batch=batch)
    assert actual['calculated_cost_usd']==pytest.approx(float(exact),abs=1e-8)


def test_disabling_provider_still_returns_to_configured_oauth_before_paid():
    from scripts.lib import anthropic_routing as r
    p=r.load_policy();p['enabled']=False
    cfg={'registered':True,'anthropic_first':True,'allowed_lanes':['anthropic','grok','chatgpt']}
    assert r.eligible('fixture',cfg,policy=p)
    plan=r.configured_plan('fixture',cfg,{'requested_policy':'FAST'},enabled={'grok','chatgpt','deepseek'},
        model_for_provider=lambda p,t:p,policy=p,env={'ANTHROPIC_API_KEY':'synthetic'},now=NOW)
    assert plan[0]['skip']=='provider_disabled' and plan[1]['provider']=='grok'


@pytest.mark.parametrize('failure',[ValueError('synthetic malformed response'),KeyboardInterrupt()])
def test_abort_or_invalid_http_decode_keeps_possibly_billable_hold(tmp_path,failure):
    _,transport=modules();client,book,*_=adapter_fixture(tmp_path,[failure])
    expected=KeyboardInterrupt if isinstance(failure,KeyboardInterrupt) else transport.AnthropicError
    with pytest.raises(expected):invoke(client)
    assert Decimal(book.snapshot(now=NOW)['reserved_usd'])>0


def test_overloaded_then_success_records_the_ambiguous_attempt_separately(tmp_path):
    client,book,*_=adapter_fixture(tmp_path,[(529,{'error':{'type':'overloaded_error'}},{}),response()])
    observed=[]
    def record(model,code):observed.append((model,code));return True
    client.record_attempt=record
    invoke(client)
    assert observed==[('claude-haiku-5-5','OVERLOADED')]
    assert Decimal(book.snapshot(now=NOW)['reserved_usd'])>0
