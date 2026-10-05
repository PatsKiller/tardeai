"""Hermetic complete-desk coverage, routing and payoff contracts. No provider access."""
from datetime import datetime, timezone

import pytest

from scripts.lib.options_research_universe import merge_research_rows, conviction_bias
from scripts.lib.options_economics import payoff_metrics
from scripts.lib.options_universe_census import build_coverage


def test_direction_conflict_keeps_shared_thesis_and_all_memberships():
    row = merge_research_rows([
        {"symbol": "TEST", "source": "cio_research", "direction": "bearish", "research_artifact_id": "e1"},
        {"symbol": "TEST", "source": "entry_state", "direction": "bullish", "entry_state": "BUY_READY"},
    ])[0]
    assert row["direction"] == "bearish"
    assert row["source_lanes"] == ["cio_research", "entry_state"]
    assert row["direction_conflict"] is True
    assert conviction_bias(row) == "conflict"
    assert conviction_bias({"verdict": "STRONG_BUY"}) == "bullish"
    assert conviction_bias({"verdict": "SELL"}) == "bearish"


def test_inventory_includes_unresearched_and_fractional_account_rows():
    coverage = build_coverage(
        holdings=[{"symbol": "V", "shares": 130, "account": "a"},
                  {"symbol": "V", "shares": .8, "account": "b"},
                  {"symbol": "FUND", "shares": 5, "options_desk_excluded": True}],
        convictions=[{"symbol": "ZZZZ", "source": "watchlist", "research_status": "research_required"},
                     {"symbol": "ZZZZ", "source": "reentry", "research_status": "research_required"}],
        proposals=[], drops=[], chains={},
    )
    assert coverage["inventory_count"] == 3
    assert coverage["account_position_count"] == 3
    rows = {r["symbol"]: r for r in coverage["rows"]}
    assert rows["V"]["accounts"][0]["covered_call_capacity"] == 1
    assert rows["V"]["accounts"][1]["covered_call_capacity"] == 0
    assert rows["ZZZZ"]["source_lanes"] == ["reentry", "watchlist"]
    assert rows["FUND"]["status"] == "POLICY_EXCLUDED"
    assert sum(coverage["status_counts"].values()) == 3


@pytest.mark.parametrize("strategy,extra,loss,profit,be", [
    ("long_call", {}, 200, None, 102),
    ("long_put", {}, 200, 9800, 98),
    ("cash_secured_put", {}, 9800, 200, 98),
    ("covered_call", {}, 9800, 200, 98),
    ("protective_put", {}, 200, None, 102),
    ("credit_spread", {"short_strike": 100, "long_strike": 95, "option_type": "put"}, 300, 200, 98),
    ("credit_spread", {"short_strike": 100, "long_strike": 105, "option_type": "call"}, 300, 200, 102),
    ("debit_spread", {"long_strike": 100, "short_strike": 105, "option_type": "call"}, 200, 300, 102),
    ("debit_spread", {"long_strike": 100, "short_strike": 95, "option_type": "put"}, 200, 300, 98),
    ("collar", {"put_strike": 95, "call_strike": 105, "net_debit": 2}, 700, 300, 102),
])
def test_package_payoffs(strategy, extra, loss, profit, be):
    p = {"strategy": strategy, "strike": 100, "premium": 2, "underlying_price": 100,
         "contracts": 1, "multiplier": 100, "iv_used": .3, "dte": 30, **extra}
    metrics = payoff_metrics(p)
    assert metrics["max_loss"] == loss
    assert metrics["max_profit"] == profit
    assert metrics["breakeven"] == be
    assert metrics["probability_basis"].startswith("lognormal")


def test_call_profit_probability_accounts_for_premium_and_fees():
    p = {"strategy": "long_call", "strike": 100, "premium": 5, "underlying_price": 100,
         "dte": 30, "iv_used": .3, "fees_total": 1.3}
    metrics = payoff_metrics(p)
    assert metrics["max_loss"] == 501.3
    assert metrics["breakeven"] == pytest.approx(105.013)
    assert metrics["probability_of_profit_pct"] < 50
    assert payoff_metrics({**p, "iv_used": None})["probability_of_profit_pct"] is None
    assert payoff_metrics({**p, "non_standard": True})["status"] == "UNSUPPORTED_DELIVERABLE"


def test_discovery_exhaustion_repeats_and_provider_failures():
    from scripts.lib.options_discovery import discover
    pages = {1: {'symbols': ['A', 'B'], 'total': 3}, 3: {'symbols': ['Z'], 'total': 3}}
    result = discover(pages.__getitem__)
    assert result['status'] == 'COMPLETE'
    assert [r['symbol'] for r in result['rows']] == ['A', 'B', 'Z']
    assert discover(lambda n: pages[1])['status'] == 'PARTIAL'
    assert discover(lambda n: {'symbols': ['A']})['status'] == 'PARTIAL'
    assert discover(pages.__getitem__, max_pages=1)['status'] == 'PARTIAL'


def test_scan_requests_deduplicate_resume_and_preserve_failures(tmp_path):
    from scripts.lib.options_scan import ScanStore, run_slice
    store = ScanStore(tmp_path)
    assert store.runs() == []
    assert not store.path.exists()  # GET does not create even an empty database
    run = store.request('full', 'first')
    assert store.request('full', 'first')['id'] == run['id']
    assert store.request('full', 'other-click')['id'] == run['id']
    inputs = {'inventory': [{'symbol': 'A'}, {'symbol': 'Z'}], 'source_receipts': {'watchlist': {'status': 'COMPLETE'}}}
    chain = {'status': 'ok', 'fetched_at': '2026-10-05T14:00:00Z',
             'request_coverage': {'all_strikes': True, 'both_sides': True, 'min_dte': 7, 'max_dte': 365, 'status': 'COMPLETE'},
             'expirations': [{'dte': 30, 'strikes': [{'strike': 100}]}]}
    calls = []
    def fetch(symbol):
        calls.append(symbol)
        if symbol == 'Z':
            raise TimeoutError('sensitive provider URL must not be persisted')
        return chain
    run = run_slice(store, run, collect=lambda p: inputs, fetch_chain=fetch, max_requests=1)
    assert run['status'] == 'RUNNING'
    run = run_slice(store, store.runs(active=True)[0], collect=lambda p: pytest.fail('must resume'),
                    fetch_chain=fetch, max_requests=1)
    assert run['status'] == 'PARTIAL'
    assert calls == ['A', 'Z']
    assert run['payload']['results']['Z']['reason'] == 'TimeoutError'
    assert 'sensitive' not in store.path.read_bytes().decode(errors='ignore')
    assert store.runs(active=True)[0]['payload']['projection_state'] == 'PENDING'
    # A crash before publication remains retryable without reacquiring chains.
    run['payload']['projection_state'] = 'COMPLETE'
    store.update(run['id'], run['status'], run['payload'], event='PROJECTED')
    assert not store.runs(active=True)


def test_scheduler_respects_early_close_and_missing_calendar():
    from scripts.lib.options_scan import due_profiles
    start = datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc)
    end = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)
    assert not due_profiles(start, open_at=start, close_at=end)
    assert not due_profiles(end, open_at=start, close_at=end)
    assert not due_profiles(start, open_at=None, close_at=None)
    now = start.replace(minute=35)
    assert due_profiles(now, open_at=start, close_at=end)[1][1].endswith(':0')


def _sample_chain():
    rows = []
    for side in ('call', 'put'):
        for strike in (90, 95, 100, 105, 110):
            intrinsic = max(0, strike - 100) if side == 'put' else max(0, 100 - strike)
            # Artificial bid/ask fixture, never production market evidence.
            premium = max(.5, 4 - abs(strike - 100) / 5) + intrinsic
            rows.append({'side': side, 'strike': strike, 'bid': premium, 'ask': premium + .2,
                         'multiplier': 100, 'iv': 30, 'quote_time': '2026-10-05T14:00:00Z'})
    return {'status': 'ok', 'underlying_price': 100, 'fetched_at': '2026-10-05T14:00:00Z',
            'expirations': [{'exp': '2026-11-04', 'dte': 30, 'strikes': rows}]}


def test_advisory_families_are_directional_same_expiry_and_never_activated():
    from scripts.lib.options_advisory_candidates import generate_candidates
    chain = _sample_chain()
    # Make an executable bear-call credit without relying on strike targeting.
    for row in chain['expirations'][0]['strikes']:
        if row['side'] == 'call':
            row['bid'] = (120 - row['strike']) / 5
            row['ask'] = row['bid'] + .2
    holdings = [{'symbol': 'TEST', 'shares': 130, 'account': 'a'},
                {'symbol': 'TEST', 'shares': .8, 'account': 'b'}]
    out = generate_candidates([{'symbol': 'TEST', 'direction': 'bearish'}], holdings, {'TEST': chain})
    strategies = {r['strategy'] for r in out}
    assert {'long_put', 'credit_spread', 'debit_spread', 'collar'}.issubset(strategies)
    assert not {'long_call', 'cash_secured_put'}.intersection(strategies)
    for row in out:
        assert row['approvable'] is False and row['enterprise']['live_eligible'] is False
        assert len({leg['expiration'] for leg in row['legs']}) == 1
    assert [r['account'] for r in out if r['strategy'] == 'collar'] == ['a']
    conflicted = generate_candidates([{'symbol': 'TEST', 'direction_conflict': True}], [], {'TEST': chain})
    assert conflicted == []


def test_engine_does_not_send_bearish_or_neutral_names_to_bullish_generators(monkeypatch):
    import options_engine as engine
    monkeypatch.setattr(engine, '_resolve_symbol_price', lambda *a, **k: pytest.fail('direction should gate first'))
    rows = [{'symbol': 'TEST', 'direction': direction, 'confidence': .9} for direction in ('bearish', 'neutral')]
    assert engine.generate_defined_risk_proposals(rows, {}, set()) == []
    assert engine.generate_credit_spread_proposals(rows, {}) == []
    rows = [{'id': str(n), 'strategy': 'long_call', 'edge_score': n, 'approvable': False} for n in range(30)]
    rows.append({'id': 'ready', 'strategy': 'long_call', 'edge_score': 1, 'approvable': True})
    ordered = engine._allocate_strategy_slots(rows)
    assert len(ordered) == 31 and ordered[0]['id'] == 'ready'


def test_api_gets_read_cache_and_paginate_without_generation(tmp_path, monkeypatch):
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    import sys
    source = ast.parse((Path(__file__).parents[1] / 'scripts/api_v2.py').read_text())
    names = {'_options_proposals', '_options_coverage', '_options_holdings_funnel'}
    module = ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    rows = [{'id': str(i), 'symbol': 'TEST', 'strategy': 'covered_call', 'desk_queue': 'income',
             'enterprise': {'live_eligible': False, 'blocks': ['fixture']}} for i in range(60)]
    snapshot = {'proposals': rows, 'count': 60, 'coverage': {'rows': [], 'inventory_count': 0}}
    fake = SimpleNamespace(PROJECT_ROOT=tmp_path, STATE_DIR=tmp_path,
        read_proposals=lambda: snapshot, filter_proposals=lambda p, **k: p,
        proposal_filter_facets=lambda p: {'total': len(p)},
        generate_proposals=lambda *a, **k: pytest.fail('GET attempted generation'))
    monkeypatch.setitem(sys.modules, 'options_pilot_arm', SimpleNamespace(status=lambda: {}))
    ns = {'_get_options_engine': lambda: fake, '_json_clean': lambda x: x}
    exec(compile(module, '<options-api-test>', 'exec'), ns)
    response = ns['_options_proposals']({'offset': ['50'], 'limit': ['50'], 'force': ['1']})
    assert response['filtered_count'] == 60 and len(response['proposals']) == 10
    assert response['scan_request_required'] == 'POST /api/v2/options/scans'
    assert ns['_options_proposals']({'show_blocked': ['0']})['filtered_count'] == 0
    rows[-1].update(approvable=True, enterprise={'live_eligible': True, 'blocks': []})
    ready = ns['_options_proposals']({'show_blocked': ['0'], 'offset': ['0']})
    assert ready['filtered_count'] == 1 and ready['proposals'][0]['id'] == '59'
    assert ns['_options_holdings_funnel']()['status'] == 'UNAVAILABLE'
    assert ns['_options_coverage']()['scan_enabled'] is False
    assert not (tmp_path / 'options_scan.sqlite3').exists()


def test_watchlist_inventory_query_has_no_research_or_alphabetical_limit(monkeypatch):
    import sys
    from types import SimpleNamespace
    import options_engine as engine
    queries = []
    def execute(sql, params, **kwargs):
        queries.append((sql, params))
        return [{'symbol': f'NAME{i}', 'card_rec': None, 'synth_rec': None} for i in range(250)]
    monkeypatch.setitem(sys.modules, 'db_adapter', SimpleNamespace(USE_DB=True, _execute=execute))
    rows = engine._researched_watchlist_rows()
    assert len(rows) == 250
    assert queries[0][1] == (None,)
    assert 'AND (rc.symbol IS NOT NULL' not in queries[0][0]
    assert all(r['research_status'] == 'research_required' for r in rows)


def test_full_and_priority_reuse_same_chain_identity_and_request_alias(tmp_path):
    from scripts.lib.options_scan import ScanStore, run_slice, chain_receipt
    store = ScanStore(tmp_path)
    chain = _sample_chain()
    chain['request_coverage'] = {'status': 'COMPLETE', 'all_strikes': True, 'both_sides': True, 'min_dte': 7, 'max_dte': 365}
    receipt = chain_receipt(chain)
    store.save_snapshot('TEST', chain, receipt)
    run = store.request('priority', 'click1')
    alias = store.request('priority', 'click2')
    inputs = {'inventory': [{'symbol': 'TEST', 'source_lanes': ['watchlist']}], 'source_receipts': {}}
    finished = run_slice(store, run, collect=lambda _: inputs, max_requests=5,
                         fetch_chain=lambda _: pytest.fail('fresh full chain must be reused'),
                         now=datetime(2026, 10, 5, 14, 1, tzinfo=timezone.utc))
    assert finished['payload']['results']['TEST']['snapshot_id'] == receipt['snapshot_id']
    assert finished['payload']['request_count'] == 0
    assert store.request('priority', 'click2')['id'] == alias['id']


def test_merged_direction_evidence_is_idempotent_and_does_not_invent_artifacts():
    source = [{'symbol': 'X', 'source': 'cio_research', 'direction': 'bearish', 'research_artifact_id': 'a'},
              {'symbol': 'X', 'source': 'watchlist', 'direction': 'bullish', 'research_status': 'research_required'}]
    once = merge_research_rows(source)
    assert merge_research_rows(once) == once
    assert merge_research_rows([{'symbol': 'Y', 'source': 'watchlist', 'research_status': 'research_required'}])[0]['research_status'] == 'research_required'


def test_same_account_lots_cover_together_but_accounts_never_combine():
    result = build_coverage(holdings=[{'symbol': 'X', 'account': 'a', 'shares': 60},
                                     {'symbol': 'X', 'account': 'a', 'shares': 50},
                                     {'symbol': 'X', 'account': 'b', 'shares': 90}],
                            convictions=[], proposals=[], drops=[], chains={})
    assert [(a['shares'], a['covered_call_capacity']) for a in result['rows'][0]['accounts']] == [(110, 1), (90, 0)]


def test_all_eight_expression_families_cover_long_dated_chains():
    from scripts.lib.options_advisory_candidates import generate_candidates
    chain = _sample_chain()
    chain['expirations'][0].update(dte=365, exp='2027-10-05')
    holdings = [{'symbol': 'X', 'shares': 100, 'account': 'a'}]
    bull = generate_candidates([{'symbol': 'X', 'direction': 'bullish'}], holdings, {'X': chain})
    bear = generate_candidates([{'symbol': 'X', 'direction': 'bearish'}], holdings, {'X': chain})
    assert {r['strategy'] for r in bull + bear} == {'covered_call', 'cash_secured_put', 'protective_put',
        'long_call', 'long_put', 'credit_spread', 'debit_spread', 'collar'}
    assert all(r['dte'] == 365 and not r['approvable'] for r in bull + bear)
    chain['expirations'][0]['dte'] = 0
    assert generate_candidates([{'symbol': 'X', 'direction': 'bullish'}], holdings, {'X': chain}) == []


def test_snapshot_projection_reads_immutable_identity_with_bounded_cache(tmp_path):
    from scripts.lib.options_scan import ScanStore, CapturedChains, chain_receipt
    store = ScanStore(tmp_path)
    old = _sample_chain()
    first = chain_receipt(old)
    store.save_snapshot('X', old, first)
    store.save_snapshot('X', {**old, 'underlying_price': 200}, chain_receipt({**old, 'underlying_price': 200}))
    mapping = CapturedChains(store, {'X': first})
    assert mapping['X']['underlying_price'] == 100
    assert mapping['X']['snapshot_id'] == first['snapshot_id']
    assert mapping._load.cache_info().maxsize == 4


def test_shared_research_request_reuses_pending_and_obeys_existing_budget():
    from scripts.lib.options_scan import request_missing_research
    rows = [{'symbol': s, 'source_lanes': ['watchlist'], 'research_status': 'research_required',
             'chain': {'status': 'COMPLETE', 'snapshot_id': f'chain-{s}'}} for s in ['A', 'B', 'C']]
    calls = []
    pending = {'A'}
    first = request_missing_research(rows, pending=pending, limit=1,
        request=lambda sym, **kw: calls.append(sym) or {'symbol': sym, 'timestamp': 'fixture'}, run_id='run')
    assert calls == ['B'] and first[0]['chain_snapshot_id'] == 'chain-B'
    request_missing_research(rows, pending=pending, limit=1,
        request=lambda sym, **kw: calls.append(sym), run_id='run')
    assert calls == ['B', 'C']


def test_watchlist_query_failure_cannot_claim_complete(monkeypatch):
    import options_engine as engine
    import db_adapter
    monkeypatch.setattr(db_adapter, 'USE_DB', True)
    monkeypatch.setattr(db_adapter, '_execute', lambda *a, **kw: None)
    assert engine._researched_watchlist_rows() == []
    assert engine.SOURCE_RECEIPTS['watchlist']['status'] == 'UNAVAILABLE'


def test_reentry_membership_exceeds_snapshot_and_query_failure_is_visible(monkeypatch, tmp_path):
    import options_engine as engine
    import db_adapter
    monkeypatch.setattr(engine, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(engine, '_load_json', lambda _: {'computed_at': '2026-10-05T20:00:00Z', 'rows': [{'symbol': 'A'}]})
    monkeypatch.setattr(db_adapter, 'USE_DB', True)
    def query(sql, *args, **kwargs):
        return [] if 'ui_prefs' in sql else [{'symbol': 'Z'}]
    monkeypatch.setattr(db_adapter, '_execute', query)
    rows = engine._reentry_research_rows()
    assert {r['symbol'] for r in rows} == {'A', 'Z'}
    assert engine.SOURCE_RECEIPTS['reentry']['status'] == 'COMPLETE'
    assert engine.SOURCE_RECEIPTS['reentry']['as_of'] == '2026-10-05T20:00:00Z'
    monkeypatch.setattr(db_adapter, '_execute', lambda *a, **k: None)
    assert engine._reentry_research_rows()[0]['symbol'] == 'A'
    assert engine.SOURCE_RECEIPTS['reentry']['status'] == 'UNAVAILABLE'


def test_advisory_calls_and_collars_respect_existing_operator_intent():
    from scripts.lib.options_advisory_candidates import generate_candidates
    drops = []
    out = generate_candidates([{'symbol': 'X', 'direction': 'bullish'}],
        [{'symbol': 'X', 'shares': 100, 'account': 'a'}], {'X': _sample_chain()},
        covered_call_block=lambda symbol, strike, spot: 'operator floor 150' if strike < 150 else None,
        drops=drops)
    assert not {'covered_call', 'collar'}.intersection(r['strategy'] for r in out)
    assert 'protective_put' in {r['strategy'] for r in out}
    assert {r['strategy'] for r in drops} == {'covered_call', 'collar'}
    assert all(r['reason'] == 'OPERATOR_INTENT' for r in drops)
