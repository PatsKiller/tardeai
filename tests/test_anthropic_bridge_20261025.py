"""Real bridge, injected providers/ledger: promotional precedence and native refusals."""
import json
from unittest.mock import MagicMock

import pytest

from tests.test_bridge_oauth_llm_step_20261014 import (  # noqa: F401
    DIAG, VALID, bridge, hermetic, wire,
)
from tests.test_n8n_oauth_first_routing_20261015 import ledger


class Provider:
    def __init__(self, *, fail=None):
        self.fail, self.calls = fail, []

    def generate(self, messages, model, **kwargs):
        model = model or "fixture-oauth-model"
        self.calls.append((model, kwargs))
        if self.fail:
            raise self.fail
        return {"model": model, "choices": [{"message": {"content": json.dumps(VALID)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                "_tradeai": {"estimated_cost_usd": 0.0001}}


@pytest.mark.parametrize("failing", [0, 1, 2, 3])
def test_real_bridge_walks_promotion_oauth_then_single_paid(monkeypatch, failing):
    from lib import anthropic_routing as promo
    from lib.anthropic_transport import AnthropicError
    with ledger(monkeypatch):
        base = __import__('lib.llm_consumption', fromlist=['get_process_config'])
        cfg = base.get_process_config(DIAG)
        cfg.update(anthropic_first=True, allowed_lanes=['anthropic', 'grok', 'chatgpt', 'fast'])
        monkeypatch.setattr(base, 'get_process_config', lambda _pid: cfg)
        monkeypatch.setattr(base, 'reprice_reservation', MagicMock())
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-key-not-a-credential')
        # One confirmed response per candidate; no provider HTTP, key file or DB.
        providers = {}
        order = ['anthropic', 'grok', 'chatgpt', 'deepseek']
        for i, name in enumerate(order):
            providers[name] = Provider(fail=AnthropicError('RATE_LIMITED') if i < failing else None)
            bridge.set_transport_override(name, providers[name])
        try:
            result = bridge.execute_governed_call([{'role': 'user', 'content': 'synthetic'}], process_id=DIAG)
            assert result.get('_tradeai', {}).get('governance_pass') is True, result
            assert [name for name in order if providers[name].calls] == order[:failing + 1]
            assert result['model'] == providers[order[failing]].calls[0][0]
            assert not promo.current_funding()
        finally:
            for name in order:
                bridge.set_transport_override(name, None)


def test_real_bridge_adapter_ledger_and_credit_settlement_are_correlated(monkeypatch,tmp_path):
    from lib import anthropic_routing as promo
    from lib.anthropic_transport import AnthropicTransport,price_usage,load_policy
    from tests.test_anthropic_first_20261025 import NOW
    import functools
    with ledger(monkeypatch) as led:
        lc=__import__('lib.llm_consumption',fromlist=['get_process_config'])
        cfg=lc.get_process_config(DIAG);cfg.update(anthropic_first=True,allowed_lanes=['anthropic','grok','chatgpt','fast'])
        monkeypatch.setattr(lc,'get_process_config',lambda _:cfg)
        monkeypatch.setattr(lc,'reprice_reservation',MagicMock())
        monkeypatch.setenv('PROJECT_ROOT',str(tmp_path))
        monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-transport-key')
        usage={'input_tokens':30,'output_tokens':12,'cache_read_input_tokens':2000,'cache_creation_input_tokens':1000}
        def http(method,path,payload,**kwargs):
            if path.endswith('count_tokens'):return 200,{'input_tokens':100},{}
            return 200,{'id':'fixture-correlated','model':load_policy()['models']['bulk'],
                'content':[{'type':'text','text':json.dumps(VALID)}],'usage':usage},{}
        monkeypatch.setattr(promo,'AnthropicTransport',functools.partial(AnthropicTransport,request=http,now=lambda:NOW))
        result=bridge.execute_governed_call([{'role':'user','content':'synthetic'}],process_id=DIAG)
        assert result.get('_tradeai',{}).get('governance_pass') is True,result
        expected=float(price_usage(usage,load_policy()['pricing'][load_policy()['models']['bulk']]))
        assert led['settle'].call_args.args[1]==expected
        events=[json.loads(line) for line in (tmp_path/'data/runtime/provider_cost/events.jsonl').read_text().splitlines()]
        assert len(events)==1 and events[0]['provider']=='anthropic'
        assert events[0]['source_process']==DIAG and events[0]['request_id']=='fixture-correlated'
        assert events[0]['cache_creation_input_tokens']==1000
        assert events[0]['calculated_cost_usd']==pytest.approx(expected)
        assert 'synthetic-transport-key' not in json.dumps(events)
