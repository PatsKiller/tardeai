#!/usr/bin/env python3
"""strategy_router.py — Maps candidates to matching strategy playbooks.

Given a candidate dict (symbol, price, rvol, etc.), determines which
strategy playbooks apply. Each matched strategy produces its own
independent Strategy Card. One strategy's score cannot justify another.

Usage:
    python3 scripts/strategy_router.py --test
    python3 scripts/strategy_router.py --symbol FTCI --price 4.95 --rvol 8.2 --float-m 12 --catalyst "FDA clearance"
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger(__name__)

STRATEGIES_DIR = PROJECT_ROOT / 'config' / 'strategies'

STRATEGY_IDS = [
    'momentum_scalp', 'gap_and_go', 'swing_breakout',
    'sector_rotation', 'earnings_catalyst', 'income_add',
]


class StrategyRouter:
    def __init__(self):
        self._yamls = {}

    def _load_yaml(self, strategy_id: str) -> dict:
        if strategy_id not in self._yamls:
            path = STRATEGIES_DIR / f'{strategy_id}.yaml'
            try:
                with open(path) as f:
                    self._yamls[strategy_id] = yaml.safe_load(f) or {}
            except Exception:
                self._yamls[strategy_id] = {}
        return self._yamls[strategy_id]

    def route(self, candidate: dict) -> dict:
        """Route a candidate to matching strategies.

        Args:
            candidate: dict with some/all of: symbol, price, rvol, gap_pct,
                change_pct, catalyst, catalyst_verified, asset_type, sector,
                earnings_date, earnings_reported_recently, dividend_yield,
                base_days, breakout_volume_ratio, sector_rank, account,
                source, float_m, volume, dollar_volume

        Returns:
            {
                "symbol": str,
                "matched_strategies": [...],
                "rejected_strategies": [...]
            }
        """
        symbol = (candidate.get('symbol') or '').upper()
        matched = []
        rejected = []

        for sid in STRATEGY_IDS:
            result = self._check_strategy(sid, candidate)
            if result['matched']:
                matched.append(result)
            else:
                rejected.append(result)

        return {
            'symbol': symbol,
            'matched_strategies': matched,
            'rejected_strategies': rejected,
        }

    def _check_strategy(self, strategy_id: str, c: dict) -> dict:
        """Check if candidate matches a specific strategy."""
        checkers = {
            'momentum_scalp': self._check_momentum_scalp,
            'gap_and_go': self._check_gap_and_go,
            'swing_breakout': self._check_swing_breakout,
            'sector_rotation': self._check_sector_rotation,
            'earnings_catalyst': self._check_earnings_catalyst,
            'income_add': self._check_income_add,
        }
        checker = checkers.get(strategy_id)
        if not checker:
            return {'strategy_id': strategy_id, 'matched': False,
                    'reasons': ['unknown_strategy'], 'missing': [], 'confidence': 0}
        return checker(c)

    def _check_momentum_scalp(self, c: dict) -> dict:
        yaml_cfg = self._load_yaml('momentum_scalp')
        filters = yaml_cfg.get('screen_filters', {})
        reasons = []
        missing = []
        reject_reasons = []

        price = c.get('price')
        rvol = c.get('rvol')
        float_m = c.get('float_m')
        catalyst = c.get('catalyst')

        # Price range
        if price is not None:
            max_p = filters.get('max_price', 25)
            if float(price) <= float(max_p):
                reasons.append('price_range')
            else:
                reject_reasons.append(f'price_over_{max_p}')
        else:
            missing.append('price')

        # RVOL
        if rvol is not None:
            min_r = filters.get('min_rvol', 5.0)
            if float(rvol) >= float(min_r):
                reasons.append('rvol')
            else:
                reject_reasons.append(f'rvol_below_{min_r}')
        else:
            missing.append('rvol')

        # Float
        if float_m is not None:
            max_f = filters.get('max_float_m', 100)
            if float(float_m) <= float(max_f):
                reasons.append('float')
            else:
                reject_reasons.append(f'float_over_{max_f}M')
        else:
            missing.append('float_m')

        # Catalyst
        if catalyst:
            reasons.append('catalyst_present')
        else:
            # Social source can still qualify as candidate
            source = c.get('source', '')
            if source in ('stocktwits', 'reddit', 'social', 'social_surge'):
                reasons.append('social_candidate')
            else:
                missing.append('catalyst')

        # Match decision
        matched = len(reasons) >= 2 and not reject_reasons
        confidence = min(1.0, len(reasons) / 4.0) if matched else 0
        if reject_reasons:
            return {'strategy_id': 'momentum_scalp', 'matched': False,
                    'reasons': reject_reasons, 'missing': missing, 'confidence': 0}
        return {'strategy_id': 'momentum_scalp', 'matched': matched,
                'reasons': reasons, 'missing': missing,
                'confidence': round(confidence, 2)}

    def _check_gap_and_go(self, c: dict) -> dict:
        yaml_cfg = self._load_yaml('gap_and_go')
        filters = yaml_cfg.get('screen_filters', {})
        reasons = []
        missing = []
        reject_reasons = []

        gap_pct = c.get('gap_pct')
        price = c.get('price')
        catalyst = c.get('catalyst')
        rvol = c.get('rvol')

        if gap_pct is not None:
            min_gap = filters.get('min_gap_pct', 5.0)
            if float(gap_pct) >= float(min_gap):
                reasons.append('gap_qualifies')
            else:
                reject_reasons.append(f'gap_below_{min_gap}pct')
        else:
            missing.append('gap_pct')
            reject_reasons.append('no_gap_data')

        if price is not None:
            if float(price) <= float(filters.get('max_price', 50)):
                reasons.append('price_range')
            else:
                reject_reasons.append('price_over_50')

        if catalyst:
            reasons.append('catalyst_present')
        else:
            reject_reasons.append('no_catalyst')

        if rvol is not None and float(rvol) >= float(filters.get('min_rvol', 3.0)):
            reasons.append('rvol')

        matched = 'gap_qualifies' in reasons and 'catalyst_present' in reasons
        confidence = min(1.0, len(reasons) / 4.0) if matched else 0
        if not matched:
            return {'strategy_id': 'gap_and_go', 'matched': False,
                    'reasons': reject_reasons, 'missing': missing, 'confidence': 0}
        return {'strategy_id': 'gap_and_go', 'matched': True,
                'reasons': reasons, 'missing': missing,
                'confidence': round(confidence, 2)}

    def _check_swing_breakout(self, c: dict) -> dict:
        reasons = []
        missing = []
        reject_reasons = []

        base_days = c.get('base_days')
        breakout_vol = c.get('breakout_volume_ratio')
        sector_rank = c.get('sector_rank')
        price = c.get('price')

        if base_days is not None:
            if int(base_days) >= 15:
                reasons.append('base_duration')
            else:
                reject_reasons.append('base_too_short')
        else:
            missing.append('base_days')

        if breakout_vol is not None:
            if float(breakout_vol) >= 1.5:
                reasons.append('breakout_volume')
            else:
                reject_reasons.append('breakout_volume_low')
        else:
            missing.append('breakout_volume_ratio')

        if sector_rank is not None:
            if int(sector_rank) <= 3:
                reasons.append('sector_leading')
        else:
            missing.append('sector_rank')

        if price is not None:
            if 5 <= float(price) <= 150:
                reasons.append('price_range')

        matched = 'base_duration' in reasons and 'breakout_volume' in reasons
        confidence = min(1.0, len(reasons) / 4.0) if matched else 0
        if not matched:
            return {'strategy_id': 'swing_breakout', 'matched': False,
                    'reasons': reject_reasons or ['insufficient_data'],
                    'missing': missing, 'confidence': 0}
        return {'strategy_id': 'swing_breakout', 'matched': True,
                'reasons': reasons, 'missing': missing,
                'confidence': round(confidence, 2)}

    def _check_sector_rotation(self, c: dict) -> dict:
        reasons = []
        reject_reasons = []

        yaml_cfg = self._load_yaml('sector_rotation')
        etf_universe = yaml_cfg.get('etf_universe', [])
        symbol = (c.get('symbol') or '').upper()
        asset_type = c.get('asset_type', '')

        if symbol in etf_universe:
            reasons.append('in_etf_universe')
        elif asset_type and 'etf' in str(asset_type).lower():
            reasons.append('is_etf')
        else:
            reject_reasons.append('not_sector_etf')

        matched = bool(reasons) and not reject_reasons
        return {'strategy_id': 'sector_rotation', 'matched': matched,
                'reasons': reasons if matched else reject_reasons,
                'missing': [], 'confidence': 0.7 if matched else 0}

    def _check_earnings_catalyst(self, c: dict) -> dict:
        reasons = []
        missing = []
        reject_reasons = []

        earnings_date = c.get('earnings_date')
        earnings_reported = c.get('earnings_reported_recently')

        if earnings_date:
            reasons.append('earnings_date_present')
        elif earnings_reported:
            reasons.append('earnings_reported_recently')
        else:
            missing.append('earnings_date')
            reject_reasons.append('no_earnings_context')

        catalyst = c.get('catalyst', '')
        if catalyst and any(kw in catalyst.lower() for kw in
                           ['earnings', 'revenue', 'eps', 'guidance', 'quarterly', 'q1', 'q2', 'q3', 'q4']):
            reasons.append('earnings_catalyst')

        matched = bool(reasons) and not reject_reasons
        confidence = min(1.0, len(reasons) / 2.0) if matched else 0
        if not matched:
            return {'strategy_id': 'earnings_catalyst', 'matched': False,
                    'reasons': reject_reasons, 'missing': missing, 'confidence': 0}
        return {'strategy_id': 'earnings_catalyst', 'matched': True,
                'reasons': reasons, 'missing': missing,
                'confidence': round(confidence, 2)}

    def _check_income_add(self, c: dict) -> dict:
        reasons = []
        missing = []
        reject_reasons = []

        dividend_yield = c.get('dividend_yield')
        if dividend_yield is not None:
            if float(dividend_yield) >= 3.0:
                reasons.append('yield_qualifies')
            else:
                reject_reasons.append('yield_below_3pct')
        else:
            missing.append('dividend_yield')
            reject_reasons.append('no_yield_data')

        # Check strategy type hints
        strategy_type = c.get('strategy_type', '')
        if strategy_type and any(kw in strategy_type.lower() for kw in
                                 ['dividend', 'income', 'yield', 'reit', 'bdc']):
            reasons.append('income_strategy_type')

        matched = 'yield_qualifies' in reasons or 'income_strategy_type' in reasons
        if not matched:
            return {'strategy_id': 'income_add', 'matched': False,
                    'reasons': reject_reasons, 'missing': missing, 'confidence': 0}
        return {'strategy_id': 'income_add', 'matched': True,
                'reasons': reasons, 'missing': missing,
                'confidence': min(1.0, len(reasons) / 2.0)}


def main():
    parser = argparse.ArgumentParser(description='Strategy Router')
    parser.add_argument('--test', action='store_true', help='Run self-test')
    parser.add_argument('--symbol', help='Symbol to route')
    parser.add_argument('--price', type=float)
    parser.add_argument('--rvol', type=float)
    parser.add_argument('--float-m', type=float)
    parser.add_argument('--gap-pct', type=float)
    parser.add_argument('--catalyst', type=str)
    parser.add_argument('--dividend-yield', type=float)
    parser.add_argument('--base-days', type=int)
    parser.add_argument('--breakout-volume-ratio', type=float)
    parser.add_argument('--sector-rank', type=int)
    args = parser.parse_args()

    router = StrategyRouter()

    if args.test:
        print("=== Strategy Router Self-Test ===\n")

        # Test 1: High-RVOL catalyst stock -> momentum_scalp
        r = router.route({'symbol': 'FTCI', 'price': 4.95, 'rvol': 8.2,
                          'float_m': 12, 'catalyst': 'FDA clearance'})
        scalp_match = [m for m in r['matched_strategies'] if m['strategy_id'] == 'momentum_scalp']
        print(f"1. FTCI (scalp candidate): matched={bool(scalp_match)}")
        assert scalp_match, "FTCI should match momentum_scalp"
        print(f"   reasons: {scalp_match[0]['reasons']}")

        # Test 2: Gap candidate
        r = router.route({'symbol': 'BDSX', 'price': 3.50, 'gap_pct': 12.0,
                          'rvol': 4.5, 'catalyst': 'Partnership announcement'})
        gap_match = [m for m in r['matched_strategies'] if m['strategy_id'] == 'gap_and_go']
        print(f"2. BDSX (gap candidate): matched={bool(gap_match)}")
        assert gap_match, "BDSX should match gap_and_go"

        # Test 3: Swing breakout
        r = router.route({'symbol': 'EVER', 'price': 25.0, 'base_days': 22,
                          'breakout_volume_ratio': 2.1, 'sector_rank': 2})
        swing_match = [m for m in r['matched_strategies'] if m['strategy_id'] == 'swing_breakout']
        print(f"3. EVER (swing candidate): matched={bool(swing_match)}")
        assert swing_match, "EVER should match swing_breakout"

        # Test 4: Sector ETF
        r = router.route({'symbol': 'XLK', 'asset_type': 'ETF'})
        rot_match = [m for m in r['matched_strategies'] if m['strategy_id'] == 'sector_rotation']
        print(f"4. XLK (sector rotation): matched={bool(rot_match)}")
        assert rot_match, "XLK should match sector_rotation"

        # Test 5: Income candidate
        r = router.route({'symbol': 'SCHD', 'dividend_yield': 3.8,
                          'strategy_type': 'dividend_growth_compounder'})
        inc_match = [m for m in r['matched_strategies'] if m['strategy_id'] == 'income_add']
        print(f"5. SCHD (income candidate): matched={bool(inc_match)}")
        assert inc_match, "SCHD should match income_add"

        # Test 6: Earnings catalyst
        r = router.route({'symbol': 'AAPL', 'earnings_date': '2026-05-10',
                          'catalyst': 'Q2 earnings beat guidance raised'})
        earn_match = [m for m in r['matched_strategies'] if m['strategy_id'] == 'earnings_catalyst']
        print(f"6. AAPL (earnings catalyst): matched={bool(earn_match)}")
        assert earn_match, "AAPL should match earnings_catalyst"

        # Test 7: Multi-match (scalp + gap)
        r = router.route({'symbol': 'ABCD', 'price': 5.0, 'rvol': 6.0,
                          'float_m': 8, 'gap_pct': 7.5,
                          'catalyst': 'FDA approval'})
        matched_ids = [m['strategy_id'] for m in r['matched_strategies']]
        print(f"7. Multi-match: {matched_ids}")
        assert 'momentum_scalp' in matched_ids, "Should match scalp"
        assert 'gap_and_go' in matched_ids, "Should match gap"

        # Test 8: No match
        r = router.route({'symbol': 'XYZ', 'price': 500})
        print(f"8. No match: matched={len(r['matched_strategies'])}, rejected={len(r['rejected_strategies'])}")

        print("\n=== All strategy router tests passed ===")
        return

    if args.symbol:
        candidate = {'symbol': args.symbol}
        if args.price: candidate['price'] = args.price
        if args.rvol: candidate['rvol'] = args.rvol
        if args.float_m: candidate['float_m'] = args.float_m
        if args.gap_pct: candidate['gap_pct'] = args.gap_pct
        if args.catalyst: candidate['catalyst'] = args.catalyst
        if args.dividend_yield: candidate['dividend_yield'] = args.dividend_yield
        if args.base_days: candidate['base_days'] = args.base_days
        if args.breakout_volume_ratio: candidate['breakout_volume_ratio'] = args.breakout_volume_ratio
        if args.sector_rank: candidate['sector_rank'] = args.sector_rank

        result = router.route(candidate)
        print(json.dumps(result, indent=2))
        return

    print("Usage: python3 scripts/strategy_router.py --test")
    print("       python3 scripts/strategy_router.py --symbol FTCI --price 4.95 --rvol 8.2")


if __name__ == '__main__':
    main()
