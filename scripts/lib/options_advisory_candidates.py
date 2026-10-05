"""Complete the options expression families from captured chains, without authority.

These additional structures remain advisory with an explicit approval/configuration
block. They never activate a strategy or synthesize a thesis. Existing live families
continue through the existing enterprise and CIO gates in options_engine.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

from .options_economics import payoff_metrics
from .options_research_universe import conviction_bias


def _quote(row):
    try:
        bid, ask = float(row.get('bid') or 0), float(row.get('ask') or 0)
        multiplier = float(row.get('multiplier') or 100)
        strike = float(row.get('strike') or 0)
        return (all(math.isfinite(v) for v in (bid, ask, multiplier, strike)) and strike > 0
                and bid >= 0 and ask > 0 and ask >= bid and multiplier == 100 and not row.get('nonstandard'))
    except (ValueError, TypeError):
        return False


def _pick(rows, side, target):
    candidates = [r for r in rows if r.get('side') == side and _quote(r)]
    return min(candidates, key=lambda r: (abs(float(r['strike']) - target),
        float(r['ask']) - float(r.get('bid') or 0)), default=None)


def generate_candidates(research: list[dict], holdings: list[dict], chains: dict[str, dict],
                        *, covered_call_block=None, drops: list[dict] | None = None) -> list[dict]:
    """One representative per expiry/family/account, examining all returned strikes."""
    research_by_symbol = {r['symbol']: r for r in research}
    result = []
    for symbol, chain in chains.items():
        if chain.get('status') != 'ok':
            continue
        thesis = research_by_symbol.get(symbol, {})
        direction = conviction_bias(thesis)
        try:
            spot = float(chain.get('underlying_price') or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(spot) or spot <= 0:
            continue
        for expiry in chain.get('expirations', []):
            try:
                dte = int(expiry.get('dte') or 0)
            except (ValueError, TypeError):
                continue
            if not 7 <= dte <= 365:
                continue
            contracts = [r for r in expiry.get('strikes') or [] if _quote(r)]
            exp = expiry.get('exp')

            def emit(strategy, legs, premium, **extra):
                if not all(leg is not None for _, leg in legs):
                    return
                if strategy != 'collar' and premium <= 0:
                    return
                if covered_call_block and strategy in {'covered_call', 'collar'}:
                    call = next(leg for action, leg in legs if action == 'SELL' and leg['side'] == 'call')
                    reason = covered_call_block(symbol, float(call['strike']), spot)
                    if reason:
                        if drops is not None:
                            drops.append({'symbol': symbol, 'strategy': strategy, 'reason': 'OPERATOR_INTENT', 'detail': reason})
                        return
                spec = [(action, leg['side'], leg['strike']) for action, leg in legs]
                identity = [symbol, strategy, exp, extra.get('account'), spec]
                proposal_id = 'adv_' + hashlib.sha256(repr(identity).encode()).hexdigest()[:24]
                ivs = [float(leg.get('iv') or 0) for _, leg in legs]
                ivs = [iv / 100 if iv > 3 else iv for iv in ivs if iv > 0]
                proposal = {'id': proposal_id, 'strategy': strategy, 'symbol': symbol, 'underlying': symbol,
                    'expiration': exp, 'dte': dte, 'underlying_price': spot, 'premium': round(premium, 4),
                    'premium_total': round(premium * 100, 2), 'contracts': 1, 'multiplier': 100,
                    'strike': legs[0][1]['strike'], 'option_type': legs[0][1]['side'],
                    'side': 'SELL' if strategy in {'credit_spread', 'covered_call', 'cash_secured_put'} else 'BUY',
                    'iv_used': sum(ivs) / len(ivs) if ivs else None,
                    'price_basis': 'executable bid/ask before fees and slippage', 'data_source': 'schwab_chain',
                    'chain_snapshot_id': chain.get('snapshot_id'), 'quotes_as_of': chain.get('fetched_at'),
                    'quote_time': min((str(leg['quote_time']) for _, leg in legs if leg.get('quote_time')), default=None),
                    'legs': [{'action': action, 'option_type': leg['side'], 'strike': leg['strike'],
                              'expiration': exp, 'symbol': leg.get('symbol'), 'bid': leg.get('bid'),
                              'ask': leg.get('ask'), 'quote_time': leg.get('quote_time'), 'multiplier': 100}
                             for action, leg in legs],
                    'research_context': {k: thesis.get(k) for k in ('source_lanes', 'research_status',
                        'research_artifact_id', 'research_as_of', 'subject_guid', 'summary')},
                    'advisory_only': True, 'approvable': False, 'enterprise_blocked': True,
                    'enterprise': {'live_eligible': False, 'blocks': [
                        'CONFIG_REQUIRED: additional expression requires strategy policy and CIO review']},
                    'quality_pass': False, 'edge_score': None, 'edge_basis': 'not ranked: configuration required',
                    'action_buttons': [{'action': 'review_chain', 'label': 'View chain'}],
                    'recommended_action': 'Research expression', **extra}
                economics = payoff_metrics(proposal)
                if economics['status'] != 'MODELED':
                    return
                proposal.update(payoff=economics, pop_pct=economics['probability_of_profit_pct'],
                    pop_basis=economics['probability_basis'], max_loss=economics['max_loss'],
                    max_profit='unlimited' if economics['profit_unlimited'] else economics['max_profit'],
                    breakeven=economics['breakeven'], expected_value=None,
                    expected_value_method='withheld until quote/liquidity and strategy gates pass')
                result.append(proposal)

            if direction == 'bullish':
                call = _pick(contracts, 'call', spot)
                if call:
                    emit('long_call', [('BUY', call)], float(call['ask']))
                short_put = _pick(contracts, 'put', spot * .95)
                if short_put:
                    emit('cash_secured_put', [('SELL', short_put)], float(short_put['bid']),
                         ownership_consent=thesis.get('willing_to_own') is True,
                         ownership_requirement='Operator willingness to own and account cash must be verified')
                    long_put = _pick([r for r in contracts if float(r['strike']) < float(short_put['strike'])], 'put', spot * .90)
                    if long_put:
                        emit('credit_spread', [('SELL', short_put), ('BUY', long_put)],
                             float(short_put['bid']) - float(long_put['ask']),
                             short_strike=short_put['strike'], long_strike=long_put['strike'])
            if direction == 'bearish':
                long_put = _pick(contracts, 'put', spot)
                if long_put:
                    emit('long_put', [('BUY', long_put)], float(long_put['ask']))
                short_call = _pick(contracts, 'call', spot * 1.05)
                if short_call:
                    long_call = _pick([r for r in contracts if float(r.get('strike') or 0) > float(short_call['strike'])],
                                      'call', spot * 1.10)
                    if long_call:
                        emit('credit_spread', [('SELL', short_call), ('BUY', long_call)],
                             float(short_call.get('bid') or 0) - float(long_call['ask']),
                             short_strike=short_call['strike'], long_strike=long_call['strike'])
            if direction in {'bullish', 'bearish'}:
                side = 'call' if direction == 'bullish' else 'put'
                long = _pick(contracts, side, spot)
                if long:
                    strike = float(long['strike'])
                    eligible = [r for r in contracts if (float(r.get('strike') or 0) > strike if side == 'call'
                                                         else float(r.get('strike') or 0) < strike)]
                    short = _pick(eligible, side, spot * (1.05 if side == 'call' else .95))
                    if short:
                        emit('debit_spread', [('BUY', long), ('SELL', short)],
                             float(long['ask']) - float(short.get('bid') or 0),
                             long_strike=long['strike'], short_strike=short['strike'])
            put, call = _pick(contracts, 'put', spot * .95), _pick(contracts, 'call', spot * 1.05)
            if put and call:
                for holding in holdings:
                    if (holding.get('symbol') != symbol or holding.get('options_desk_excluded')
                            or float(holding.get('shares') or 0) < 100):
                        continue
                    emit('covered_call', [('SELL', call)], float(call['bid']), account=holding.get('account'),
                         shares_held=holding.get('shares'), ownership_requirement='Assignment consent requires operator review')
                    emit('protective_put', [('BUY', put)], float(put['ask']), account=holding.get('account'),
                         shares_held=holding.get('shares'))
                    debit = float(put['ask']) - float(call.get('bid') or 0)
                    emit('collar', [('BUY', put), ('SELL', call)], debit,
                         net_debit=debit, put_strike=put['strike'], call_strike=call['strike'],
                         account=holding.get('account'), shares_held=holding.get('shares'),
                         stock_coverage_basis='one 100-share package in this account; not sized')
    return result
