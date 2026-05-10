#!/usr/bin/env python3
"""
incubator_proposal_promoter.py — Bridge incubator_universe to paper_trade_proposals.

Promotes qualifying incubator candidates into paper-trade proposals with
computed entry/stop/target levels and proper timeframe classification.

Usage:
    python scripts/incubator_proposal_promoter.py --dry-run
    python scripts/incubator_proposal_promoter.py --run
    python scripts/incubator_proposal_promoter.py --run --limit 5
    python scripts/incubator_proposal_promoter.py --run --force-symbol KVHI
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from pipeline_registry import PipelineRun

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TIMEFRAME_MAP = {
    'gap_and_go': ('intraday', 8),
    'momentum_scalp': ('intraday', 8),
    'swing_breakout': ('short_swing', 120),
    'swing_trade': ('short_swing', 120),
    'earnings_catalyst': ('event_window', 240),
    'speculative_growth': ('event_window', 240),
    'core_growth_compounder': ('position', 720),
    'core_index': ('position', 720),
    'income_add': ('position', 720),
    'covered_call_income': ('position', 720),
    'dividend_growth_compounder': ('position', 720),
    'defense_thesis': ('position', 720),
    'recovery_watch': ('position', 720),
    'sector_rotation': ('swing', 120),
}
DEFAULT_TIMEFRAME = ('short_swing', 120)

SCREENER_DISPLAY = {
    'day_scalp': 'Finviz Day Scalp (RVOL + Float)',
    'swing_trade': 'Finviz Swing Trade (Momentum)',
    'speculative_growth': 'Finviz Speculative Growth',
    'dividend_growth': 'Finviz Dividend Growth',
    'covered_call': 'Finviz Covered Call Income',
    'high_yield': 'Finviz High Yield BDC',
    'income_etf': 'Finviz Income ETF',
    'core_growth': 'Finviz Core Growth Compounder',
    'defense_thesis': 'Finviz Defense / Aerospace',
    'core_holding': 'Finviz Core Holding',
    'core_index': 'Finviz Core Index',
    'recovery': 'Finviz Recovery Watch',
    'international': 'Finviz International Dividend',
    'reit': 'Finviz REIT Income',
    'bond': 'Finviz Bond Income',
    'social_scalp': 'Social Scalp Scanner',
    'screener': 'Finviz Multi-Screener',
}

RISK_BUDGET = 150  # dollars per trade


def _queue_llm_review(conn, proposal_id: int, symbol: str, strategy_id: str):
    """Queue a proposal for LLM review via proposal_llm_reviewer.py.

    Inserts a row into proposal_agent_reviews with status='pending' so
    the enrichment pipeline or manual trigger picks it up.
    Uses savepoints so failures here never poison the main transaction.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT llm_queue")
            # Queue via the existing agent review infrastructure
            cur.execute("""
                INSERT INTO proposal_agent_reviews
                    (proposal_id, symbol, strategy_id, agent_name, status, created_at)
                VALUES (%s, %s, %s, 'scalp_critic', 'pending', NOW())
                ON CONFLICT DO NOTHING
            """, [proposal_id, symbol, strategy_id])
            cur.execute("RELEASE SAVEPOINT llm_queue")
    except Exception as e:
        log.warning(f"[llm_queue] agent_reviews non-fatal: {e}")
        try:
            conn.cursor().execute("ROLLBACK TO SAVEPOINT llm_queue")
        except Exception:
            pass


def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', 5432)),
        dbname=os.getenv('DB_NAME', 'trade_ai'),
        user=os.getenv('DB_USER', 'trade_ai'),
        password=os.getenv('DB_PASSWORD'),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_candidates(cur, force_symbol=None, limit=10):
    """Return incubator rows eligible for promotion."""
    if force_symbol:
        cur.execute("""
            SELECT * FROM incubator_universe
            WHERE symbol = %s
              AND status = 'ACTIVE'
              AND promoted_to_proposal_at IS NULL
            LIMIT %s
        """, [force_symbol.upper(), limit])
    else:
        cur.execute("""
            SELECT iu.*, s.decision as scan_decision
            FROM incubator_universe iu
            LEFT JOIN LATERAL (
                SELECT decision FROM trade_ai_scans
                WHERE symbol = iu.symbol
                ORDER BY scanned_at DESC LIMIT 1
            ) s ON true
            WHERE iu.status = 'ACTIVE'
              AND iu.latest_score >= 38
              AND (iu.catalyst_verified = true OR iu.latest_score >= 45)
              AND iu.promoted_to_proposal_at IS NULL
              AND iu.days_active >= 1
              AND COALESCE(iu.llm_screen_verdict, 'HOLD') != 'DROP'
              AND COALESCE(s.decision, 'WAIT') != 'AVOID'
            ORDER BY
                CASE COALESCE(s.decision, 'WAIT')
                    WHEN 'GO' THEN 0
                    WHEN 'WAIT' THEN 1
                    ELSE 2
                END,
                iu.latest_score DESC
            LIMIT %s
        """, [limit])
    return cur.fetchall()


def is_already_pending(cur, symbol, strategy_id):
    cur.execute("""
        SELECT 1 FROM paper_trade_proposals
        WHERE symbol = %s AND strategy_id = %s AND status = 'PENDING'
        LIMIT 1
    """, [symbol, strategy_id])
    return cur.fetchone() is not None


def get_scan_price(cur, symbol):
    """Return (price, screener_label) from most recent trade_ai_scans row."""
    cur.execute("""
        SELECT price, screener_label FROM trade_ai_scans
        WHERE symbol = %s
        ORDER BY scanned_at DESC
        LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row:
        return row['price'], row['screener_label']
    return None, None


def extract_evidence_price(evidence_payload):
    """Try to pull a price from the evidence_payload JSON."""
    if not evidence_payload:
        return None
    try:
        if isinstance(evidence_payload, str):
            evidence_payload = json.loads(evidence_payload)
        return evidence_payload.get('price')
    except (json.JSONDecodeError, AttributeError):
        return None


def compute_levels(price):
    """Return (entry, stop, target, shares) from a price."""
    entry = round(price, 2)
    risk_per_share = round(entry * 0.05, 4)
    stop = round(entry - risk_per_share, 2)
    target = round(entry + risk_per_share * 2, 2)
    shares = max(1, int(RISK_BUDGET / risk_per_share))
    return entry, stop, target, shares


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run=True, limit=10, force_symbol=None, max_per_symbol=2):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    candidates = fetch_candidates(cur, force_symbol=force_symbol, limit=limit)
    promoted = 0
    skipped = 0
    results = []
    symbol_counts = {}  # track promotions per symbol this run

    # Load existing PENDING proposal counts per symbol (total, not just this run)
    cur.execute("SELECT symbol, COUNT(*) FROM paper_trade_proposals WHERE status='PENDING' GROUP BY symbol")
    existing_pending = {r['symbol']: r['count'] for r in cur.fetchall()}

    for c in candidates:
        symbol = c['symbol']
        strategy_id = c['strategy_id']

        # Duplicate control: max TOTAL pending proposals per symbol
        total_pending = existing_pending.get(symbol, 0) + symbol_counts.get(symbol, 0)
        symbol_counts.setdefault(symbol, 0)
        if total_pending >= max_per_symbol:
            results.append(f"SKIPPED: {symbol} (total_pending={total_pending} >= max={max_per_symbol})")
            skipped += 1
            continue
        score = c['latest_score']
        days_active = c['days_active'] or 0
        catalyst_verified = c['catalyst_verified']

        # Gate check (force-symbol bypasses score gates but not pending check)
        if not force_symbol:
            if not catalyst_verified and (score is None or score < 45):
                results.append(f"SKIPPED: {symbol} (no_catalyst, score={score})")
                skipped += 1
                continue

        # LLM screen gate: require grade A or B (skip if not screened yet)
        llm_grade = c.get('llm_screen_grade')
        llm_verdict = c.get('llm_screen_verdict')
        if llm_grade and llm_grade not in ('A', 'B'):
            results.append(f"SKIPPED: {symbol} (llm_grade={llm_grade}, verdict={llm_verdict})")
            skipped += 1
            continue
        if llm_verdict == 'DROP':
            results.append(f"SKIPPED: {symbol} (llm_verdict=DROP)")
            skipped += 1
            continue

        # Already pending?
        if is_already_pending(cur, symbol, strategy_id):
            results.append(f"SKIPPED: {symbol} (already_pending)")
            skipped += 1
            continue

        # Price lookup
        scan_price, screener_label = get_scan_price(cur, symbol)
        if scan_price is None:
            scan_price = extract_evidence_price(c.get('evidence_payload'))
        if scan_price is None or scan_price <= 0:
            results.append(f"SKIPPED: {symbol} (no_price)")
            skipped += 1
            continue

        entry, stop, target, shares = compute_levels(scan_price)

        # Timeframe
        strategy_key = strategy_id if isinstance(strategy_id, str) else str(strategy_id)
        timeframe_class, expires_hours = TIMEFRAME_MAP.get(strategy_key, DEFAULT_TIMEFRAME)
        expires_at = datetime.now(tz=__import__('datetime').timezone.utc) + timedelta(hours=expires_hours)

        # Screener name: use actual screener_label from scans, with incubator context
        display_screener = screener_label or None
        screener_display_name = SCREENER_DISPLAY.get(screener_label, None) if screener_label else None
        screener_name = f"Incubator ({days_active}d active)"
        if display_screener:
            screener_name = f"Incubator ({days_active}d) via {display_screener}"

        # Signal grade from score
        if score is not None:
            if score >= 48:
                signal_grade = 'A+'
            elif score >= 40:
                signal_grade = 'A'
            elif score >= 30:
                signal_grade = 'B'
            else:
                signal_grade = 'C'
        else:
            signal_grade = None

        # Setup type display
        setup_display = strategy_key.replace('_', ' ').title()

        overnight = timeframe_class != 'intraday'

        # Source run label
        source_run_label = f"incubator_promote_{datetime.now(tz=__import__('datetime').timezone.utc).strftime('%Y%m%d_%H%M')}"

        if dry_run:
            results.append(
                f"WOULD PROMOTE: {symbol} ({strategy_key}, score={score}, grade={signal_grade}, {screener_name})"
            )
            promoted += 1
            continue

        # INSERT proposal
        cur.execute("""
            INSERT INTO paper_trade_proposals
                (symbol, strategy_id, primary_strategy_id,
                 proposed_entry, proposed_stop, proposed_target1,
                 proposed_shares, status, expires_at, lifecycle_status,
                 entry_zone_status, proposal_timeframe_class,
                 screener_name, source_table, discovery_source, source_run_label,
                 signal_score, signal_grade, catalyst, catalyst_verified,
                 setup_type, proposed_by, overnight_monitoring_enabled,
                 packet_state, packet_completion_pct,
                 llm_review_status, agent_review_status)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, 'PENDING', %s, 'ACTIVE',
                    'NEEDS_PRICE_CHECK', %s,
                    %s, 'incubator_universe', 'incubator', %s,
                    %s, %s, %s, %s,
                    %s, 'incubator_promoter', %s,
                    'NEW', 0,
                    'NOT_REQUESTED', 'NOT_REQUESTED')
            RETURNING id
        """, [
            symbol, strategy_id, strategy_id,
            entry, stop, target,
            shares, expires_at, timeframe_class,
            screener_name, source_run_label,
            score, signal_grade, c.get('catalyst'), catalyst_verified,
            setup_display, overnight,
        ])
        new_id = cur.fetchone()['id']

        # Mark as promoted
        cur.execute("""
            UPDATE incubator_universe
            SET promoted_to_proposal_at = NOW()
            WHERE id = %s
        """, [c['id']])

        # Queue LLM review for the new proposal
        _queue_llm_review(conn, new_id, symbol, strategy_id)

        conn.commit()
        promoted += 1
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        results.append(f"PROMOTED: {symbol} ({strategy_key}, score={score}, {screener_name})")

    cur.close()
    conn.close()
    return results, promoted, skipped


def _send_pipeline_alert(message):
    """Send Telegram alert for pipeline failures with retry command."""
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from telegram_alert import send_telegram
        send_telegram(message)
    except Exception as e:
        log.error(f"[promoter] Telegram alert failed: {e}")


def main():
    parser = argparse.ArgumentParser(description='Promote incubator candidates to paper-trade proposals')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='Print what would be promoted, no writes')
    mode.add_argument('--run', action='store_true', help='Execute promotions')
    parser.add_argument('--limit', type=int, default=10, help='Max promotions per run (default 10)')
    parser.add_argument('--force-symbol', type=str, default=None, help='Promote regardless of score gate')
    parser.add_argument('--max-proposals-per-symbol', type=int, default=2, help='Max proposals per symbol per run')
    args = parser.parse_args()

    dry_run = args.dry_run

    try:
        with PipelineRun('incubator_proposal_promoter', triggered_by='cli') as pipe:
            results, promoted, skipped = run(
                dry_run=dry_run,
                limit=args.limit,
                force_symbol=args.force_symbol,
                max_per_symbol=args.max_proposals_per_symbol,
            )
            pipe.rows(promoted)

        print()
        prefix = "[DRY RUN] " if dry_run else ""
        print(f"{prefix}Incubator Proposal Promoter")
        print(f"{prefix}{'=' * 40}")
        for line in results:
            print(f"  {line}")
        print(f"\n{prefix}Promoted: {promoted}  Skipped: {skipped}")

        # Send success summary via Telegram (live runs only)
        if not dry_run and promoted > 0:
            symbols = [l.split(":")[1].strip().split(" ")[0] for l in results if l.startswith("PROMOTED")]
            _send_pipeline_alert(
                f"Incubator Promoter\n"
                f"Promoted: {promoted} | Skipped: {skipped}\n"
                f"Symbols: {', '.join(symbols)}\n\n"
                f"Reply: proposals"
            )

    except Exception as e:
        log.error(f"[promoter] FATAL: {e}", exc_info=True)
        error_short = str(e)[:200]
        _send_pipeline_alert(
            f"PIPELINE FAILURE: incubator_proposal_promoter\n"
            f"Error: {error_short}\n\n"
            f"Reply to retry:\n"
            f"  run promoter — retry now\n"
            f"  run promoter dry — dry-run first\n"
            f"  status — system health check"
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
