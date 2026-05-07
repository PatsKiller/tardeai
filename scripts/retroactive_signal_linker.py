#!/usr/bin/env python3
"""retroactive_signal_linker.py -- Link closed trades to preceding GO/WAIT signals.

Matches trade_closed rows (where signal_linked_at IS NULL) to the nearest
preceding scan in trade_ai_scans by symbol + date window.  On match it:
  1. Inserts an agent_recommendation_outcomes row (scoring_method='retroactive').
  2. Stamps trade_closed.signal_linked_at = now().

Idempotent: skips any trade already linked (signal_linked_at IS NOT NULL).

Usage:
    python scripts/retroactive_signal_linker.py           # normal
    python scripts/retroactive_signal_linker.py --dry-run # preview only
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
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
logger = logging.getLogger('retroactive_signal_linker')
logger.setLevel(logging.DEBUG)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

_fh = logging.FileHandler(LOG_DIR / 'retroactive_signal_linker.log')
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

# ── constants ───────────────────────────────────────────────────────────
# Maximum days before trade open_date to search for a matching scan
LOOKBACK_DAYS = 3

# Map trade_type values to strategy_id heuristics
STRATEGY_MAP = {
    'scalp': 'SCALP',
    'swing': 'SWING',
    'daytrade': 'DAYTRADE',
    'day': 'DAYTRADE',
    'momentum': 'MOMENTUM',
}


def _infer_strategy(trade_type: str | None, scan_decision: str | None) -> str:
    """Best-effort strategy_id from trade_type + scan data."""
    if trade_type:
        key = trade_type.strip().lower()
        if key in STRATEGY_MAP:
            return STRATEGY_MAP[key]
    return 'UNKNOWN'


def _verdict(pnl: float | None) -> str:
    if pnl is None:
        return 'UNKNOWN'
    if pnl > 0:
        return 'WIN'
    if pnl < 0:
        return 'LOSS'
    return 'BREAKEVEN'


def run(dry_run: bool = False) -> dict:
    """Main linking logic.  Returns summary dict."""
    stats = {'trades_checked': 0, 'linked': 0, 'no_match': 0, 'errors': 0}

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
    except Exception as exc:
        logger.error('DB connection failed: %s', exc)
        stats['errors'] += 1
        return stats

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Fetch unlinked closed trades
        cur.execute("""
            SELECT id, symbol, open_date, close_date, buy_price, sell_price,
                   pnl, trade_type, account, hold_days, shares
            FROM trade_closed
            WHERE signal_linked_at IS NULL
            ORDER BY open_date
        """)
        trades = cur.fetchall()
        stats['trades_checked'] = len(trades)
        logger.info('Found %d unlinked closed trades', len(trades))

        if not trades:
            logger.info('Nothing to link -- exiting cleanly.')
            return stats

        for trade in trades:
            tid = trade['id']
            sym = trade['symbol']
            open_dt = trade['open_date']

            if open_dt is None:
                logger.warning('Trade %s has NULL open_date -- skipping', tid)
                stats['no_match'] += 1
                continue

            # Normalise to date
            if isinstance(open_dt, datetime):
                open_date = open_dt.date()
            else:
                open_date = open_dt

            window_start = open_date - timedelta(days=LOOKBACK_DAYS)

            # 2. Find best matching scan (closest preceding scan for same symbol)
            cur.execute("""
                SELECT id, symbol, score, decision, catalyst, catalyst_verified,
                       rvol, float_m, gap_pct, screener_label, scanned_at
                FROM trade_ai_scans
                WHERE symbol = %s
                  AND scanned_at::date BETWEEN %s AND %s
                ORDER BY scanned_at DESC
                LIMIT 1
            """, (sym, window_start, open_date))

            scan = cur.fetchone()
            if not scan:
                logger.debug('No scan match for trade %s (%s open %s)', tid, sym, open_date)
                stats['no_match'] += 1
                continue

            # 3. Build outcome row
            strategy_id = _infer_strategy(trade.get('trade_type'), scan.get('decision'))
            pnl = trade.get('pnl')
            buy_price = trade.get('buy_price')
            sell_price = trade.get('sell_price')
            pnl_pct = None
            if pnl is not None and buy_price and buy_price != 0:
                shares = trade.get('shares') or 1
                pnl_pct = round((pnl / (buy_price * shares)) * 100, 4)

            verdict = _verdict(pnl)
            recommendation = scan.get('decision') or 'UNKNOWN'
            rec_date = scan.get('scanned_at')

            if dry_run:
                logger.info(
                    '[DRY-RUN] Would link trade %s (%s) -> scan %s (%s %s) | pnl=%s verdict=%s',
                    tid, sym, scan['id'], recommendation, rec_date, pnl, verdict,
                )
                stats['linked'] += 1
                continue

            try:
                # Insert outcome
                cur.execute("""
                    INSERT INTO agent_recommendation_outcomes (
                        agent_name, symbol, recommendation, strategy_type,
                        recommendation_date, entry_date, exit_date,
                        entry_price, exit_price, realized_pnl, pnl_pct,
                        hold_days, verdict, scoring_method, notes
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                """, (
                    'signal_linker',
                    sym,
                    recommendation,
                    strategy_id,
                    rec_date,
                    trade.get('open_date'),
                    trade.get('close_date'),
                    buy_price,
                    sell_price,
                    pnl,
                    pnl_pct,
                    trade.get('hold_days'),
                    verdict,
                    'retroactive',
                    f'auto-linked scan {scan["id"]} to trade {tid}',
                ))

                # Stamp the trade
                cur.execute("""
                    UPDATE trade_closed
                    SET signal_linked_at = NOW()
                    WHERE id = %s
                """, (tid,))

                conn.commit()
                stats['linked'] += 1
                logger.info('Linked trade %s (%s) -> scan %s | verdict=%s pnl=%s',
                            tid, sym, scan['id'], verdict, pnl)

            except Exception as exc:
                conn.rollback()
                logger.error('Error linking trade %s: %s', tid, exc)
                stats['errors'] += 1

    except Exception as exc:
        logger.error('Query error: %s', exc)
        stats['errors'] += 1
    finally:
        conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Retroactive signal linker')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no DB writes')
    args = parser.parse_args()

    logger.info('=== Retroactive Signal Linker %s ===', '(DRY-RUN)' if args.dry_run else '')
    stats = run(dry_run=args.dry_run)

    summary = (
        f"\n{'='*50}\n"
        f"Signal Linker Summary {'(DRY-RUN)' if args.dry_run else ''}\n"
        f"  Trades checked : {stats['trades_checked']}\n"
        f"  Linked         : {stats['linked']}\n"
        f"  No match       : {stats['no_match']}\n"
        f"  Errors         : {stats['errors']}\n"
        f"{'='*50}"
    )
    logger.info(summary)
    print(summary)


if __name__ == '__main__':
    main()
