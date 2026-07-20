#!/usr/bin/env python3
"""pattern_extractor.py -- Monthly pattern extraction from trade outcomes.

Analyzes agent_recommendation_outcomes (joined with trade_ai_scans where available)
to discover repeatable patterns, then upserts them into pattern_library.

Pattern dimensions:
  - catalyst_type    (catalyst text keyword bucketing)
  - rvol_range       (low / medium / high / extreme)
  - float_range      (nano / micro / small / mid / large)
  - gap_range        (flat / small_gap / big_gap / mega_gap)
  - combined_high_conviction  (high rvol + small float + big gap)

Pattern classification:
  PROVEN   : win_rate >= 65% AND expectancy > $50
  KILLED   : win_rate <= 40%
  NEUTRAL  : everything else

Usage:
    python scripts/pattern_extractor.py                      # normal
    python scripts/pattern_extractor.py --min-trades 10      # require 10+ trades
    python scripts/pattern_extractor.py --dry-run            # preview only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ── env / config ────────────────────────────────────────────────────────
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
DB_CONFIG = dict(
    host=os.getenv('DB_HOST', '127.0.0.1'),
    port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'trade_ai'),
    user=os.getenv('DB_USER', 'trade_ai'),
    password=os.getenv('DB_PASSWORD'),
)

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# ── logging ─────────────────────────────────────────────────────────────
logger = logging.getLogger('pattern_extractor')
logger.setLevel(logging.DEBUG)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

_fh = logging.FileHandler(LOG_DIR / 'pattern_extractor.log')
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

# ── classification thresholds ───────────────────────────────────────────
PROVEN_WR = 0.65
PROVEN_EXPECTANCY = 50.0
KILLED_WR = 0.40

DEFAULT_MIN_TRADES = 5


# ── bucketing helpers ───────────────────────────────────────────────────

def _rvol_bucket(rvol: float | None) -> str | None:
    if rvol is None:
        return None
    if rvol < 1.5:
        return 'low'
    if rvol < 3.0:
        return 'medium'
    if rvol < 6.0:
        return 'high'
    return 'extreme'


def _float_bucket(float_m: float | None) -> str | None:
    if float_m is None:
        return None
    if float_m < 10:
        return 'nano'
    if float_m < 50:
        return 'micro'
    if float_m < 200:
        return 'small'
    if float_m < 1000:
        return 'mid'
    return 'large'


def _gap_bucket(gap_pct: float | None) -> str | None:
    if gap_pct is None:
        return None
    gap = abs(gap_pct)
    if gap < 2:
        return 'flat'
    if gap < 8:
        return 'small_gap'
    if gap < 20:
        return 'big_gap'
    return 'mega_gap'


def _catalyst_bucket(catalyst: str | None) -> str | None:
    if not catalyst:
        return None
    c = catalyst.lower()
    if any(k in c for k in ['earn', 'revenue', 'eps', 'guidance']):
        return 'earnings'
    if any(k in c for k in ['fda', 'drug', 'trial', 'pharma', 'biotech', 'pdufa']):
        return 'biotech_catalyst'
    if any(k in c for k in ['contract', 'deal', 'partner', 'acqui', 'merger', 'm&a']):
        return 'deal_ma'
    if any(k in c for k in ['sec', 'filing', '13f', 'insider']):
        return 'sec_filing'
    if any(k in c for k in ['short', 'squeeze', 'gamma']):
        return 'short_squeeze'
    if any(k in c for k in ['offering', 'dilut', 'atm', 'shelf']):
        return 'offering'
    return 'other'


def _compute_pattern_stats(trades: list[dict]) -> dict:
    """Compute stats for a group of trades."""
    total = len(trades)
    # realized_pnl arrives from PostgreSQL as Decimal. Mixing it with the float
    # win_rate raised "unsupported operand type(s) for *: 'float' and
    # 'decimal.Decimal'" and aborted every extraction — which is why this script
    # produced 0 patterns and pattern_library sat empty despite 3,004 input rows
    # and four consumers reading it (2026-07-20).
    def _pnl(t) -> float:
        try:
            return float(t.get('realized_pnl') or 0)
        except (TypeError, ValueError):
            return 0.0

    wins = [t for t in trades if _pnl(t) > 0]
    losses = [t for t in trades if _pnl(t) < 0]
    win_count = len(wins)
    win_rate = win_count / total if total else 0.0

    gross_profit = sum(_pnl(t) for t in wins) if wins else 0.0
    gross_loss = abs(sum(_pnl(t) for t in losses)) if losses else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    avg_winner = (gross_profit / len(wins)) if wins else 0.0
    avg_loser = (gross_loss / len(losses)) if losses else 0.0
    expectancy = (win_rate * avg_winner) - ((1 - win_rate) * avg_loser)

    return {
        'trade_count': total,
        'win_count': win_count,
        'win_rate': round(win_rate, 4),
        'avg_winner': round(avg_winner, 2),
        'avg_loser': round(avg_loser, 2),
        'expectancy': round(expectancy, 2),
        'profit_factor': round(pf, 2),
    }


def _classify(stats: dict) -> str:
    if stats['win_rate'] >= PROVEN_WR and stats['expectancy'] > PROVEN_EXPECTANCY:
        return 'PROVEN'
    if stats['win_rate'] <= KILLED_WR:
        return 'KILLED'
    return 'NEUTRAL'


def run(min_trades: int = DEFAULT_MIN_TRADES, dry_run: bool = False) -> dict:
    """Main extraction logic."""
    summary = {'patterns_found': 0, 'proven': 0, 'killed': 0, 'neutral': 0,
               'upserted': 0, 'errors': 0}

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
    except Exception as exc:
        logger.error('DB connection failed: %s', exc)
        summary['errors'] += 1
        return summary

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch all scored outcomes, LEFT JOIN scans for rvol/float/gap/catalyst
        cur.execute("""
            SELECT
                o.id, o.agent_name, o.symbol, o.recommendation,
                o.strategy_type, o.recommendation_date,
                o.entry_date, o.exit_date, o.entry_price, o.exit_price,
                o.realized_pnl, o.pnl_pct, o.hold_days, o.verdict,
                s.rvol, s.float_m, s.gap_pct, s.catalyst, s.catalyst_verified
            FROM agent_recommendation_outcomes o
            LEFT JOIN LATERAL (
                SELECT rvol, float_m, gap_pct, catalyst, catalyst_verified
                FROM trade_ai_scans
                WHERE symbol = o.symbol
                  AND scanned_at::date <= o.entry_date
                ORDER BY scanned_at DESC
                LIMIT 1
            ) s ON true
            WHERE o.verdict IS NOT NULL
              AND o.verdict != 'UNKNOWN'
              AND o.realized_pnl IS NOT NULL
            ORDER BY o.entry_date
        """)
        rows = cur.fetchall()
        logger.info('Loaded %d scored outcomes for pattern analysis', len(rows))

        if not rows:
            logger.info('No outcomes to analyze -- exiting cleanly.')
            return summary

        # ── bucket trades into pattern groups ───────────────────────────
        buckets: dict[str, list[dict]] = defaultdict(list)

        for r in rows:
            rvol_b = _rvol_bucket(r.get('rvol'))
            float_b = _float_bucket(r.get('float_m'))
            gap_b = _gap_bucket(r.get('gap_pct'))
            cat_b = _catalyst_bucket(r.get('catalyst'))

            if rvol_b:
                buckets[f'rvol_{rvol_b}'].append(r)
            if float_b:
                buckets[f'float_{float_b}'].append(r)
            if gap_b:
                buckets[f'gap_{gap_b}'].append(r)
            if cat_b:
                buckets[f'catalyst_{cat_b}'].append(r)

            # Combined high-conviction: high+ rvol AND (nano or micro float) AND (big or mega gap)
            if (rvol_b in ('high', 'extreme')
                    and float_b in ('nano', 'micro')
                    and gap_b in ('big_gap', 'mega_gap')):
                buckets['combined_high_conviction'].append(r)

        # ── compute stats and upsert ────────────────────────────────────
        patterns_to_save = []

        for pattern_name, trades in buckets.items():
            if len(trades) < min_trades:
                logger.debug('Skipping %s -- only %d trades (min=%d)', pattern_name, len(trades), min_trades)
                continue

            stats = _compute_pattern_stats(trades)
            classification = _classify(stats)
            summary['patterns_found'] += 1
            summary[classification.lower()] += 1

            # Determine strategy_id from most common strategy_type
            strat_counts: dict[str, int] = defaultdict(int)
            for t in trades:
                st = t.get('strategy_type') or 'UNKNOWN'
                strat_counts[st] += 1
            dominant_strategy = max(strat_counts, key=strat_counts.get)

            # Determine pattern_type from the bucket dimension
            if pattern_name.startswith('rvol_'):
                ptype = 'rvol_range'
            elif pattern_name.startswith('float_'):
                ptype = 'float_range'
            elif pattern_name.startswith('gap_'):
                ptype = 'gap_range'
            elif pattern_name.startswith('catalyst_'):
                ptype = 'catalyst_type'
            else:
                ptype = 'combined'

            definition = {
                'dimension': ptype,
                'bucket': pattern_name,
                'sample_symbols': list({t['symbol'] for t in trades})[:10],
                'strategy_distribution': dict(strat_counts),
            }

            conditions = {
                'min_trades': min_trades,
                'extracted_at': datetime.now().isoformat(),
                'outcome_count': len(trades),
            }

            scoring_bonus = {}
            scoring_adjustment = {}
            if classification == 'PROVEN':
                scoring_bonus = {'bonus': 5, 'reason': f'Proven pattern: {pattern_name}'}
                scoring_adjustment = {'adjustment': 5, 'direction': 'up'}
            elif classification == 'KILLED':
                scoring_bonus = {'penalty': -5, 'reason': f'Killed pattern: {pattern_name}'}
                scoring_adjustment = {'adjustment': -5, 'direction': 'down'}

            patterns_to_save.append({
                'pattern_name': pattern_name,
                'strategy_id': dominant_strategy,
                'definition': definition,
                'status': classification,
                'trade_count': stats['trade_count'],
                'win_rate': stats['win_rate'],
                'avg_winner': stats['avg_winner'],
                'avg_loser': stats['avg_loser'],
                'expectancy': stats['expectancy'],
                'profit_factor': stats['profit_factor'],
                'scoring_bonus': scoring_bonus,
                'conditions': conditions,
                'scoring_adjustment': scoring_adjustment,
                'win_count': stats['win_count'],
                'pattern_type': ptype,
                'notes': f'Auto-extracted {datetime.now().strftime("%Y-%m-%d")}. '
                         f'{stats["trade_count"]} trades, WR={stats["win_rate"]:.0%}, '
                         f'E[x]=${stats["expectancy"]:.2f}',
            })

            logger.info('Pattern %-30s | %s | trades=%d WR=%.0f%% PF=%.1f E[x]=$%.2f',
                        pattern_name, classification, stats['trade_count'],
                        stats['win_rate'] * 100, stats['profit_factor'], stats['expectancy'])

        # ── upsert into pattern_library ─────────────────────────────────
        for p in patterns_to_save:
            if dry_run:
                logger.info('[DRY-RUN] Would upsert pattern: %s (%s)', p['pattern_name'], p['status'])
                summary['upserted'] += 1
                continue

            try:
                cur.execute("""
                    INSERT INTO pattern_library (
                        pattern_name, strategy_id, definition, status,
                        trade_count, win_rate, avg_winner, avg_loser,
                        expectancy, profit_factor, scoring_bonus, notes,
                        conditions, scoring_adjustment, win_count, pattern_type,
                        applied, last_updated, updated_at
                    ) VALUES (
                        %(pattern_name)s, %(strategy_id)s, %(definition)s, %(status)s,
                        %(trade_count)s, %(win_rate)s, %(avg_winner)s, %(avg_loser)s,
                        %(expectancy)s, %(profit_factor)s, %(scoring_bonus)s, %(notes)s,
                        %(conditions)s, %(scoring_adjustment)s, %(win_count)s, %(pattern_type)s,
                        false, NOW(), NOW()
                    )
                    ON CONFLICT (pattern_name) DO UPDATE SET
                        strategy_id       = EXCLUDED.strategy_id,
                        definition        = EXCLUDED.definition,
                        status            = EXCLUDED.status,
                        trade_count       = EXCLUDED.trade_count,
                        win_rate          = EXCLUDED.win_rate,
                        avg_winner        = EXCLUDED.avg_winner,
                        avg_loser         = EXCLUDED.avg_loser,
                        expectancy        = EXCLUDED.expectancy,
                        profit_factor     = EXCLUDED.profit_factor,
                        scoring_bonus     = EXCLUDED.scoring_bonus,
                        notes             = EXCLUDED.notes,
                        conditions        = EXCLUDED.conditions,
                        scoring_adjustment = EXCLUDED.scoring_adjustment,
                        win_count         = EXCLUDED.win_count,
                        pattern_type      = EXCLUDED.pattern_type,
                        last_updated      = NOW(),
                        updated_at        = NOW()
                """, {
                    'pattern_name': p['pattern_name'],
                    'strategy_id': p['strategy_id'],
                    'definition': json.dumps(p['definition']),
                    'status': p['status'],
                    'trade_count': p['trade_count'],
                    'win_rate': p['win_rate'],
                    'avg_winner': p['avg_winner'],
                    'avg_loser': p['avg_loser'],
                    'expectancy': p['expectancy'],
                    'profit_factor': p['profit_factor'],
                    'scoring_bonus': json.dumps(p['scoring_bonus']),
                    'notes': p['notes'],
                    'conditions': json.dumps(p['conditions']),
                    'scoring_adjustment': json.dumps(p['scoring_adjustment']),
                    'win_count': p['win_count'],
                    'pattern_type': p['pattern_type'],
                })
                conn.commit()
                summary['upserted'] += 1
                logger.info('Upserted pattern: %s (%s)', p['pattern_name'], p['status'])

            except Exception as exc:
                conn.rollback()
                logger.error('Error upserting pattern %s: %s', p['pattern_name'], exc)
                summary['errors'] += 1

    except Exception as exc:
        logger.error('Pattern extraction error: %s', exc)
        summary['errors'] += 1
    finally:
        conn.close()

    return summary


def main():
    parser = argparse.ArgumentParser(description='Pattern extractor (monthly)')
    parser.add_argument('--min-trades', type=int, default=DEFAULT_MIN_TRADES,
                        help=f'Minimum trades per pattern (default {DEFAULT_MIN_TRADES})')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no DB writes')
    args = parser.parse_args()

    logger.info('=== Pattern Extractor %s (min-trades=%d) ===',
                '(DRY-RUN)' if args.dry_run else '', args.min_trades)
    result = run(min_trades=args.min_trades, dry_run=args.dry_run)

    summary = (
        f"\n{'='*50}\n"
        f"Pattern Extractor Summary {'(DRY-RUN)' if args.dry_run else ''}\n"
        f"  Patterns found  : {result['patterns_found']}\n"
        f"    PROVEN        : {result['proven']}\n"
        f"    KILLED        : {result['killed']}\n"
        f"    NEUTRAL       : {result['neutral']}\n"
        f"  Upserted to DB  : {result['upserted']}\n"
        f"  Errors          : {result['errors']}\n"
        f"{'='*50}"
    )
    logger.info(summary)
    print(summary)


if __name__ == '__main__':
    main()
