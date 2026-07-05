#!/usr/bin/env python3
"""strategy_weekly_review.py -- Weekly Sunday 8 AM strategy performance review.

For each strategy in strategy_registry, evaluates recent performance and
manages lifecycle transitions:

  UNVALIDATED -> TESTING      (>= 15 signals in strategy_signals)
  TESTING     -> VALIDATED    (>= 30 closed outcomes + win_rate >= min + PF >= 1.5)
  VALIDATED   -> WATCHLIST    (win_rate drops below min_win_rate for 2 consecutive weeks)
  VALIDATED   -> KILLING_REVIEW (win_rate < 30% or PF < 0.8)

Real executions come from the schwab journal (trade_closed): exact strategy_id
matches plus family tags owned via JOURNAL_FAMILY_OWNER (reported, but only
exact-id trades gate transitions). Zero-conversion rows carry a factual gate
note, and a snapshot is written to data/portfolios/state/ for the health agent.

Sends a Telegram summary and logs all transitions to strategy_state_transitions.

Usage:
    python scripts/strategy_weekly_review.py                    # normal
    python scripts/strategy_weekly_review.py --dry-run          # preview
    python scripts/strategy_weekly_review.py --no-telegram      # skip Telegram
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

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

# Telegram import (same project)
sys.path.insert(0, str(BASE_DIR / 'scripts'))
try:
    from telegram_alert import send_telegram
except ImportError:
    def send_telegram(msg: str) -> bool:
        logger.warning('telegram_alert not available -- skipping')
        return False

# ── logging ─────────────────────────────────────────────────────────────
logger = logging.getLogger('strategy_weekly_review')
logger.setLevel(logging.DEBUG)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

_fh = logging.FileHandler(LOG_DIR / 'strategy_weekly_review.log')
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

# ── thresholds ──────────────────────────────────────────────────────────
MIN_SIGNALS_FOR_TESTING = 15
MIN_TRADES_FOR_VALIDATED = 30
MIN_PF_FOR_VALIDATED = 1.5
KILLING_REVIEW_WR = 0.30
KILLING_REVIEW_PF = 0.8

# Where the latest review snapshot is written (read by health_agent
# collect_strategy_registry_integrity to sanity-check the real-trade join).
STATE_FILE = BASE_DIR / 'data' / 'portfolios' / 'state' / 'strategy_weekly_review_latest.json'

# Real executions live in the schwab journal (trade_closed, refreshed from
# schwab_round_trips by schwab_journal_builder). Its strategy_id values are
# FAMILY-level review tags ('scalp', 'swing', 'momentum', 'position_trim',
# 'other'), not registry strategy ids — so each family tag is attributed to
# exactly ONE owning registry strategy (no double counting). 'scalp' →
# momentum_scalp matches build_trade_execution_quality._family; 'swing' →
# swing_trade (the generic swing strategy). Tags with no unambiguous owner
# ('momentum', 'position_trim', 'other') stay unattributed and are surfaced
# in the report footer instead of being force-fitted to a strategy.
JOURNAL_FAMILY_OWNER = {
    'scalp': 'momentum_scalp',
    'swing': 'swing_trade',
}


def _journal_tags_for(strategy_id: str) -> list[str]:
    """All trade_closed strategy_id values attributable to this registry strategy:
    the exact id plus any family tags it owns."""
    sid = (strategy_id or '').lower()
    return [sid] + [tag for tag, owner in JOURNAL_FAMILY_OWNER.items() if owner == sid]


def _trading_days_last_7() -> int | None:
    """NYSE trading days in the trailing 7 calendar days (holiday/weekend aware)."""
    try:
        from market_session import is_trading_day
        base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        return sum(1 for i in range(7) if is_trading_day(now=base - timedelta(days=i)))
    except Exception:
        return None


def _gate_note(status: str, signal_count: int, gating_total: int,
               real_metrics: dict, min_wr: float) -> str:
    """Small factual reason WHY a strategy did not transition (instead of a bare zero row)."""
    if status == 'UNVALIDATED':
        return f'gate: {signal_count}/{MIN_SIGNALS_FOR_TESTING} signals for TESTING'
    if status == 'TESTING':
        if gating_total < MIN_TRADES_FOR_VALIDATED:
            return (f'gate: {gating_total}/{MIN_TRADES_FOR_VALIDATED} attributed closed '
                    f'trades for VALIDATED')
        blockers = []
        if real_metrics['win_rate'] < min_wr:
            blockers.append(f"WR {real_metrics['win_rate']:.0%} < {min_wr:.0%}")
        if real_metrics['profit_factor'] < MIN_PF_FOR_VALIDATED:
            blockers.append(f"PF {real_metrics['profit_factor']:.1f} < {MIN_PF_FOR_VALIDATED}")
        return 'gate: ' + '; '.join(blockers) if blockers else 'holding at TESTING'
    return 'no change'


def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


def _compute_metrics(outcomes: list[dict]) -> dict:
    """Compute win_rate, profit_factor, avg_winner, avg_loser from outcome rows."""
    if not outcomes:
        return {'win_rate': 0.0, 'profit_factor': 0.0, 'total': 0,
                'wins': 0, 'losses': 0, 'avg_winner': 0.0, 'avg_loser': 0.0,
                'total_pnl': 0.0}

    wins = [o for o in outcomes if (o.get('realized_pnl') or 0) > 0]
    losses = [o for o in outcomes if (o.get('realized_pnl') or 0) < 0]
    total = len(outcomes)
    win_rate = len(wins) / total if total else 0.0

    gross_profit = sum(o['realized_pnl'] for o in wins) if wins else 0.0
    gross_loss = abs(sum(o['realized_pnl'] for o in losses)) if losses else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    avg_w = (gross_profit / len(wins)) if wins else 0.0
    avg_l = (gross_loss / len(losses)) if losses else 0.0
    total_pnl = sum((o.get('realized_pnl') or 0) for o in outcomes)

    return {
        'win_rate': round(win_rate, 4),
        'profit_factor': round(pf, 2),
        'total': total,
        'wins': len(wins),
        'losses': len(losses),
        'avg_winner': round(avg_w, 2),
        'avg_loser': round(avg_l, 2),
        'total_pnl': round(total_pnl, 2),
    }


def _compute_paper_metrics(rows: list[dict]) -> dict:
    """Compute metrics from paper_trades rows (uses pnl, outcome_verdict)."""
    if not rows:
        return {'win_rate': 0.0, 'profit_factor': 0.0, 'total': 0,
                'wins': 0, 'losses': 0, 'total_pnl': 0.0}

    wins = [r for r in rows if (r.get('pnl') or 0) > 0]
    losses = [r for r in rows if (r.get('pnl') or 0) < 0]
    total = len(rows)
    win_rate = len(wins) / total if total else 0.0

    gross_profit = sum(r['pnl'] for r in wins) if wins else 0.0
    gross_loss = abs(sum(r['pnl'] for r in losses)) if losses else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    return {
        'win_rate': round(win_rate, 4),
        'profit_factor': round(pf, 2),
        'total': total,
        'wins': len(wins),
        'losses': len(losses),
        'total_pnl': round(sum((r.get('pnl') or 0) for r in rows), 2),
    }


def _log_transition(cur, strategy_id: str, from_status: str, to_status: str,
                     reason: str, metrics: dict, dry_run: bool = False):
    """Insert into strategy_state_transitions."""
    if dry_run:
        logger.info('[DRY-RUN] Transition %s: %s -> %s (%s)', strategy_id, from_status, to_status, reason)
        return
    cur.execute("""
        INSERT INTO strategy_state_transitions
            (strategy_id, from_status, to_status, reason, metrics, decided_by, triggered_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (strategy_id, from_status, to_status, reason,
          json.dumps(metrics), 'strategy_weekly_review', 'cron'))
    logger.info('Transition logged: %s %s -> %s (%s)', strategy_id, from_status, to_status, reason)


def _update_status(cur, strategy_id: str, new_status: str, dry_run: bool = False):
    """Update strategy_registry.status."""
    if dry_run:
        logger.info('[DRY-RUN] Would set %s status = %s', strategy_id, new_status)
        return
    cur.execute("""
        UPDATE strategy_registry SET status = %s WHERE strategy_id = %s
    """, (new_status, strategy_id))


def run(dry_run: bool = False, send_tg: bool = True) -> dict:
    """Run the weekly review.  Returns summary dict."""
    stats = {'strategies': 0, 'transitions': 0, 'errors': 0}
    report_lines = ['*Strategy Weekly Review*', f'_{datetime.now().strftime("%Y-%m-%d %H:%M")}_']

    # Week context: a holiday-shortened week legitimately produces low counts —
    # say so instead of rendering bare zeros.
    tdays = _trading_days_last_7()
    if tdays is not None:
        week_note = f'{tdays} NYSE trading days in the last 7 days'
        if tdays < 5:
            week_note += ' (holiday-shortened week)'
        report_lines.append(f'_{week_note}_')
    report_lines.append('')

    per_strategy: list[dict] = []
    real_attributed_total = 0
    all_journal_tags: set[str] = set()

    try:
        conn = _get_conn()
        conn.autocommit = False
    except Exception as exc:
        logger.error('DB connection failed: %s', exc)
        stats['errors'] += 1
        return stats

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch all strategies. strategy_id falls back to strategy_type (the PK) so a
        # registry row whose strategy_id was left NULL by an older config-loader upsert
        # can never render as "None (UNVALIDATED)".
        cur.execute("""
            SELECT COALESCE(NULLIF(BTRIM(strategy_id), ''), strategy_type) AS strategy_id,
                   strategy_type, status, min_win_rate,
                   target_win_rate, total_signals, trades_taken
            FROM strategy_registry
            ORDER BY 1
        """)
        strategies = cur.fetchall()
        stats['strategies'] = len(strategies)
        logger.info('Reviewing %d strategies', len(strategies))

        if not strategies:
            logger.info('No strategies in registry -- nothing to review.')
            report_lines.append('_No strategies registered._')
            if send_tg:
                send_telegram('\n'.join(report_lines))
            return stats

        for strat in strategies:
            sid = strat['strategy_id']
            stype = strat['strategy_type']
            status = strat['status'] or 'UNVALIDATED'
            min_wr = strat.get('min_win_rate') or 0.50
            target_wr = strat.get('target_win_rate') or 0.60

            logger.info('--- Reviewing %s (type=%s, status=%s) ---', sid, stype, status)

            # Count signals
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM strategy_signals WHERE strategy_id = %s
            """, (sid,))
            signal_count = cur.fetchone()['cnt']

            # Real executions: the schwab journal (trade_closed, rebuilt from
            # schwab_round_trips). Matches the exact strategy_id plus any journal
            # family tags this strategy owns (JOURNAL_FAMILY_OWNER). The previous
            # source (agent_recommendation_outcomes.strategy_type) is NULL on every
            # row, which rendered "Real: 0" for all strategies while 130+ closed
            # real trades sat in the journal.
            tags = _journal_tags_for(sid)
            all_journal_tags.update(tags)
            cur.execute("""
                SELECT pnl AS realized_pnl, LOWER(strategy_id) AS journal_tag
                FROM trade_closed
                WHERE LOWER(COALESCE(strategy_id, '')) = ANY(%s)
            """, (tags,))
            real_rows = cur.fetchall()
            real_metrics = _compute_metrics(real_rows)
            real_attributed_total += real_metrics['total']
            # Family-attributed history is a heuristic classification — it is REPORTED
            # but only exact-id trades gate lifecycle transitions (no auto-promote off
            # human_review_only classifications).
            exact_rows = [r for r in real_rows if r['journal_tag'] == sid.lower()]
            exact_metrics = _compute_metrics(exact_rows)
            family_n = real_metrics['total'] - exact_metrics['total']

            # Paper trades (by strategy_id)
            cur.execute("""
                SELECT pnl, outcome_verdict, strategy_id
                FROM paper_trades
                WHERE strategy_id = %s AND status = 'closed'
            """, (sid,))
            paper_rows = cur.fetchall()
            paper_metrics = _compute_paper_metrics(paper_rows)

            # Build report line for this strategy
            fam_tags = [t for t in tags if t != sid.lower()]
            fam_note = (f", {family_n} via family tag '{'+'.join(fam_tags)}'"
                        if family_n and fam_tags else '')
            line = (
                f"*{sid}* ({status})\n"
                f"  Signals: {signal_count} | Real: {real_metrics['total']} "
                f"(WR {real_metrics['win_rate']:.0%}, PF {real_metrics['profit_factor']:.1f}{fam_note}) "
                f"| Paper: {paper_metrics['total']} "
                f"(WR {paper_metrics['win_rate']:.0%})\n"
                f"  PnL Real: ${real_metrics['total_pnl']:,.2f} | Paper: ${paper_metrics['total_pnl']:,.2f}"
            )

            # ── lifecycle transitions ───────────────────────────────────
            # Gating uses EXACT-id real trades + paper only; family-attributed
            # journal history never promotes/demotes a strategy.
            transition_made = False
            combined_total = exact_metrics['total'] + paper_metrics['total']

            if status == 'UNVALIDATED' and signal_count >= MIN_SIGNALS_FOR_TESTING:
                _log_transition(cur, sid, status, 'TESTING',
                                f'{signal_count} signals >= {MIN_SIGNALS_FOR_TESTING}',
                                {'signal_count': signal_count}, dry_run)
                _update_status(cur, sid, 'TESTING', dry_run)
                line += '\n  -> TESTING'
                stats['transitions'] += 1
                transition_made = True

            elif status == 'TESTING':
                if (combined_total >= MIN_TRADES_FOR_VALIDATED
                        and exact_metrics['win_rate'] >= min_wr
                        and exact_metrics['profit_factor'] >= MIN_PF_FOR_VALIDATED):
                    _log_transition(cur, sid, status, 'VALIDATED',
                                    f'{combined_total} trades, WR={exact_metrics["win_rate"]:.0%}, PF={exact_metrics["profit_factor"]:.1f}',
                                    {**exact_metrics, 'paper': paper_metrics}, dry_run)
                    _update_status(cur, sid, 'VALIDATED', dry_run)
                    line += '\n  -> VALIDATED'
                    stats['transitions'] += 1
                    transition_made = True

            elif status == 'VALIDATED':
                if exact_metrics['total'] >= 5:  # need minimum sample
                    if (exact_metrics['win_rate'] < KILLING_REVIEW_WR
                            or exact_metrics['profit_factor'] < KILLING_REVIEW_PF):
                        _log_transition(cur, sid, status, 'KILLING_REVIEW',
                                        f'WR={exact_metrics["win_rate"]:.0%} PF={exact_metrics["profit_factor"]:.1f} below thresholds',
                                        exact_metrics, dry_run)
                        _update_status(cur, sid, 'KILLING_REVIEW', dry_run)
                        line += '\n  -> KILLING_REVIEW'
                        stats['transitions'] += 1
                        transition_made = True
                    elif exact_metrics['win_rate'] < min_wr:
                        _log_transition(cur, sid, status, 'WATCHLIST',
                                        f'WR={exact_metrics["win_rate"]:.0%} below min {min_wr:.0%}',
                                        exact_metrics, dry_run)
                        _update_status(cur, sid, 'WATCHLIST', dry_run)
                        line += '\n  -> WATCHLIST'
                        stats['transitions'] += 1
                        transition_made = True

            if not transition_made:
                line += f'\n  ({_gate_note(status, signal_count, combined_total, exact_metrics, min_wr)})'

            per_strategy.append({
                'strategy_id': sid, 'status': status, 'signals': signal_count,
                'real': real_metrics['total'], 'real_exact': exact_metrics['total'],
                'real_family': family_n, 'paper': paper_metrics['total'],
            })
            report_lines.append(line)
            report_lines.append('')

            if not dry_run:
                conn.commit()

        # ── unattributed real trades ────────────────────────────────────
        # Journal rows whose family tag has no owning registry strategy
        # ('momentum', 'position_trim', 'other', untagged). Surfaced honestly
        # instead of silently dropped or force-fitted to a strategy.
        unattributed = []
        try:
            cur.execute("""
                SELECT COALESCE(NULLIF(LOWER(strategy_id), ''), '(untagged)') AS tag,
                       COUNT(*) AS n, COALESCE(SUM(pnl), 0) AS pnl
                FROM trade_closed
                WHERE LOWER(COALESCE(strategy_id, '')) <> ALL(%s)
                GROUP BY 1 ORDER BY 2 DESC
            """, (sorted(all_journal_tags),))
            unattributed = cur.fetchall()
        except Exception as exc:
            logger.warning('unattributed journal tag query failed: %s', exc)
        if unattributed:
            parts = ', '.join(f"{u['tag']} {u['n']} (${float(u['pnl']):,.0f})" for u in unattributed)
            report_lines.append(f'_Real trades with no owning strategy (journal family tags): {parts}_')

        # ── summary ─────────────────────────────────────────────────────
        tx_note = ''
        if stats['transitions'] == 0:
            tx_note = ' — no strategy crossed a lifecycle gate (see per-strategy gate notes)'
        report_lines.append(f'_Transitions: {stats["transitions"]}{tx_note} | Errors: {stats["errors"]}_')
        report_text = '\n'.join(report_lines)

        # Snapshot for health_agent (collect_strategy_registry_integrity) — lets it
        # verify the real-trade join against the journal without re-running the review.
        try:
            cur.execute('SELECT COUNT(*) AS n FROM trade_closed')
            journal_total = int(cur.fetchone()['n'])
            snapshot = {
                'generated_at': datetime.now().isoformat(),
                'dry_run': dry_run,
                'trading_days_last_7': tdays,
                'journal_closed_total': journal_total,
                'real_rows_attributed': real_attributed_total,
                'real_rows_unattributed': int(sum(int(u['n']) for u in unattributed)),
                'transitions': stats['transitions'],
                'strategies': per_strategy,
            }
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(snapshot, indent=2, default=str))
        except Exception as exc:
            logger.warning('state snapshot write failed: %s', exc)

        if dry_run or not send_tg:
            print(report_text)
        if send_tg and not dry_run:
            send_telegram(report_text)
            logger.info('Telegram report sent')

    except Exception as exc:
        logger.error('Review error: %s', exc)
        stats['errors'] += 1
        if not dry_run:
            conn.rollback()
    finally:
        conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Strategy weekly review')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no DB writes')
    parser.add_argument('--no-telegram', action='store_true', help='Skip Telegram report')
    args = parser.parse_args()

    logger.info('=== Strategy Weekly Review %s ===', '(DRY-RUN)' if args.dry_run else '')
    stats = run(dry_run=args.dry_run, send_tg=not args.no_telegram)

    summary = (
        f"\n{'='*50}\n"
        f"Weekly Review Summary {'(DRY-RUN)' if args.dry_run else ''}\n"
        f"  Strategies reviewed : {stats['strategies']}\n"
        f"  Transitions         : {stats['transitions']}\n"
        f"  Errors              : {stats['errors']}\n"
        f"{'='*50}"
    )
    logger.info(summary)
    print(summary)


if __name__ == '__main__':
    with PipelineRun("strategy_weekly_review") as _run:
        main()

