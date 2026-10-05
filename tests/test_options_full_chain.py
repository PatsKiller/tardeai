"""Broker-adjacent engineering grant 116800f43e11f43b: injected read only."""
import pytest


@pytest.fixture(autouse=True)
def forbid_live(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network forbidden'))


def test_full_chain_omits_strike_cap_and_bounds_dates(monkeypatch):
    import schwab_transport as transport
    calls = []
    monkeypatch.setattr(transport, '_read', lambda *a, **k: calls.append((a, k)) or {'status': 'ok', 'response_complete': True})
    out = transport.get_option_chain('TEST', account_key='fixture', full_chain=True)
    args, kw = calls[0]
    assert args[1] == 'get_option_chain'
    assert 'strike_count' not in kw
    assert 'contract_type' not in kw
    assert (kw['to_date'] - kw['from_date']).days == 358
    assert out['request_coverage']['all_strikes']
    assert transport.get_option_chain('TEST', account_key='fixture', full_chain=True, min_dte=0)['status'] == 'error'
    assert len(calls) == 1


def test_default_remains_bounded_and_failure_is_not_complete(monkeypatch):
    import schwab_transport as transport
    calls = []
    monkeypatch.setattr(transport, '_read', lambda *a, **k: calls.append(k) or {'status': 'error'})
    transport.get_option_chain('TEST', account_key='fixture')
    assert calls[0]['strike_count'] == 8
    out = transport.get_option_chain('TEST', account_key='fixture', full_chain=True)
    assert out['request_coverage']['status'] == 'PARTIAL'


def test_normalizer_preserves_all_contracts_and_detects_partial_response():
    import schwab_transport as transport
    raw = {'symbol': 'TEST', 'numberOfContracts': 2,
           'callExpDateMap': {'2026-11-05:30': {'100': [
               {'symbol': 'STANDARD', 'multiplier': 100, 'daysToExpiration': 30},
               {'symbol': 'ADJUSTED', 'multiplier': 100, 'nonStandard': True, 'daysToExpiration': 30}]}},
           'putExpDateMap': {}}
    result = transport.normalize_option_chain(raw)
    assert result['received_contract_count'] == 2
    assert result['response_complete'] is True
    raw['numberOfContracts'] = 3
    assert transport.normalize_option_chain(raw)['response_complete'] is False
    raw.pop('numberOfContracts')
    assert transport.normalize_option_chain(raw)['response_complete'] is False
