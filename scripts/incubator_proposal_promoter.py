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

def _get_default_account():
    try:
        from broker_config import get_default_paper_account
        return get_default_paper_account()
    except Exception:
        return os.environ.get("DEFAULT_PAPER_ACCOUNT", "paper")

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

# Strategy groups for per-symbol diversification
STRATEGY_GROUPS = {
    'gap_and_go': 'MOMENTUM', 'momentum_scalp': 'MOMENTUM',
    'swing_breakout': 'MOMENTUM', 'earnings_catalyst': 'MOMENTUM',
    'earnings_post_momentum': 'MOMENTUM', 'earnings_pre_buildup': 'MOMENTUM',
    'income_add': 'INCOME', 'dividend_growth_compounder': 'INCOME',
    'covered_call_income': 'INCOME', 'high_yield_income_bdc': 'INCOME',
    'reit_income': 'INCOME', 'international_dividend': 'INCOME',
    'core_growth_compounder': 'GROWTH', 'sector_rotation': 'GROWTH',
    'defense_thesis': 'GROWTH', 'speculative_growth': 'GROWTH',
    'core_index': 'GROWTH',
    'swing_trade': 'REVERSION', 'recovery_watch': 'REVERSION',
    'bond_income': 'REVERSION', 'cash_or_stable': 'REVERSION',
    'fib_retracement_bounce': 'REVERSION', 'tax_loss_harvest': 'REVERSION',
}
MAX_ACTIVE_PROPOSALS = 20  # global ceiling
MAX_PER_STRATEGY = 5  # per strategy group ceiling


# ---------------------------------------------------------------------------
# Auto-expiry and gate logic
# ---------------------------------------------------------------------------

def _auto_expire_stale_proposals(conn):
    """Expire proposals that have gone stale without operator action.
    Runs at the start of every promoter cycle, before the gate check."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    expired = 0

    # Rule 1: PENDING > 3 days with no approval/rejection
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'EXPIRED', expiry_reason = 'AUTO: No operator action in 3 days'
        WHERE status = 'PENDING'
          AND created_at < NOW() - INTERVAL '3 days'
          AND approved_at IS NULL AND rejected_at IS NULL
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: 3 days no action")
    expired += cur.rowcount

    # Rule 2: Past expires_at
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'EXPIRED', expiry_reason = 'AUTO: Past expiration time'
        WHERE status = 'PENDING'
          AND expires_at IS NOT NULL AND expires_at < NOW()
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: past expires_at")
    expired += cur.rowcount

    # Rule 3: PENDING > 2 days AND price drifted >8% from proposed entry
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'EXPIRED', expiry_reason = 'AUTO: Price drifted >8% from entry over 2+ days'
        WHERE status = 'PENDING'
          AND created_at < NOW() - INTERVAL '2 days'
          AND current_price IS NOT NULL AND proposed_entry IS NOT NULL
          AND proposed_entry > 0
          AND ABS(current_price - proposed_entry) / proposed_entry > 0.08
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: price drift >8%")
    expired += cur.rowcount

    # Rule 4: Stop breached — current_price <= proposed_stop
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'EXPIRED', expiry_reason = 'AUTO: Stop breached — price at or below stop'
        WHERE status = 'PENDING'
          AND current_price IS NOT NULL AND proposed_stop IS NOT NULL
          AND proposed_stop > 0
          AND current_price <= proposed_stop
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: stop breached")
    expired += cur.rowcount

    # Rule 5: RSI overbought for non-exempt strategies
    cur.execute("""
        UPDATE paper_trade_proposals SET
            status = 'EXPIRED', expiry_reason = 'AUTO: RSI overbought'
        WHERE status = 'PENDING'
          AND strategy_id NOT IN ('income_add','dividend_growth_compounder',
              'high_yield_income_bdc','covered_call_income','bond_income',
              'cash_or_stable','recovery_watch')
          AND symbol IN (
              SELECT ts.symbol FROM ticker_snapshot_daily ts
              WHERE ts.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
                AND ts.rsi >= 80
          )
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: RSI >= 80")
    expired += cur.rowcount

    # Rule 6: Target hit before approval — the CODX fix
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'EXPIRED', expiry_reason = 'AUTO: Target hit before approval',
            expired_at = NOW(), expired_reason = 'TARGET_HIT_BEFORE_APPROVAL'
        WHERE status = 'PENDING'
          AND current_price IS NOT NULL AND proposed_target1 IS NOT NULL
          AND proposed_target1 > 0
          AND current_price >= proposed_target1
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: target hit before approval")
    expired += cur.rowcount

    # Rule 7: Over-alerted — 5+ alerts, >2h old, still PENDING
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'EXPIRED', expiry_reason = 'AUTO: Over-alerted (5+ alerts, 2h+ old)',
            expired_at = NOW(), expired_reason = 'OVER_ALERTED'
        WHERE status = 'PENDING'
          AND COALESCE(alert_count, 0) >= 5
          AND created_at < NOW() - INTERVAL '2 hours'
        RETURNING id, symbol, strategy_id
    """)
    for r in cur.fetchall():
        log.info(f"  [auto-expire] {r['symbol']} {r['strategy_id']}: over-alerted")
    expired += cur.rowcount

    conn.commit()
    if expired > 0:
        log.info(f"[auto-expiry] Expired {expired} stale proposals")
    return expired


def _check_rsi_gate(symbol, strategy_id, conn):
    """Block overbought promotions. Income/recovery exempt. Returns (allowed, reason, rsi_value)."""
    _EXEMPT = {'income_add', 'dividend_growth_compounder', 'high_yield_income_bdc',
               'covered_call_income', 'bond_income', 'cash_or_stable', 'recovery_watch'}
    if strategy_id in _EXEMPT:
        return True, 'rsi_exempt', None

    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(ts.rsi, CAST(NULLIF(sd.data->>'rsi','') AS FLOAT)) as rsi
        FROM (SELECT 1) d
        LEFT JOIN ticker_snapshot_daily ts ON ts.symbol=%s
            AND ts.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
        LEFT JOIN ticker_snapshot_daily sd ON sd.symbol=%s
            AND sd.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
        LIMIT 1
    """, [symbol, symbol])
    row = cur.fetchone()
    if not row or row[0] is None:
        return True, 'rsi_unavailable', None
    rsi = float(row[0])

    # Strategies that block at RSI >= 80 (aggressive/momentum entries)
    _MOMENTUM = {'momentum_scalp', 'gap_and_go', 'earnings_catalyst', 'speculative_growth',
                 'core_growth_compounder', 'screener'}
    # Strategies that block at RSI >= 75 (swing entries)
    _SWING = {'swing_breakout', 'swing_trade', 'sector_rotation', 'defense_thesis'}

    if strategy_id in _MOMENTUM and rsi >= 80:
        return False, f'RSI_{rsi:.0f}_overbought_blocks_{strategy_id}', rsi
    if strategy_id in _SWING and rsi >= 75:
        return False, f'RSI_{rsi:.0f}_elevated_blocks_{strategy_id}', rsi
    # Catch-all: any strategy at RSI >= 85 is severely overbought
    if rsi >= 85:
        return False, f'RSI_{rsi:.0f}_severely_overbought', rsi
    return True, f'RSI_{rsi:.0f}_ok', rsi


def _check_promotion_gate(conn):
    """Strategy-aware promotion gate. Returns (can_promote, reason)."""
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE status = 'PENDING'
          AND NOT (
            COALESCE(origin, '') = 'watchlist'
            AND (
              lower(COALESCE(intended_broker, target_account, proposed_account, '')) LIKE 'schwab%%'
              OR lower(COALESCE(intended_broker, target_account, proposed_account, '')) LIKE 'fidelity%%'
            )
          )
    """)
    total = cur.fetchone()[0]
    if total >= MAX_ACTIVE_PROPOSALS:
        return False, f"Global gate: {total}/{MAX_ACTIVE_PROPOSALS} review-queue proposals"

    cur.execute("""
        SELECT strategy_id, COUNT(*) as cnt FROM paper_trade_proposals
        WHERE status = 'PENDING' GROUP BY strategy_id ORDER BY cnt DESC
    """)
    maxed = [r[0] for r in cur.fetchall() if r[1] >= MAX_PER_STRATEGY]
    if len(maxed) >= 3:
        return False, f"Strategy concentration: {maxed} all at {MAX_PER_STRATEGY}"

    return True, "OK"


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
    """Return incubator rows eligible for promotion (screener-sourced)."""
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


# Strategies that don't come from screener scans — need classification-based promotion
_CLASSIFICATION_STRATEGIES = {
    'income_add', 'dividend_growth_compounder', 'covered_call_income',
    'high_yield_income_bdc', 'reit_income', 'bond_income',
    'recovery_watch', 'defense_thesis', 'swing_trade',
    'core_growth_compounder', 'sector_rotation',
    'international_dividend',
}

# MAP-5: Lower score floor for income/dividend/non-momentum strategies
_DIVERSITY_SCORE_FLOOR = 15


def fetch_classification_candidates(cur, limit=10):
    """Return candidates from strategy classifications + incubator for non-screener strategies.

    These are strategies like income, dividend, recovery, defense that rarely
    appear in screener scans but have many classified symbols in the incubator.
    """
    strat_list = ",".join(f"'{s}'" for s in _CLASSIFICATION_STRATEGIES)
    cur.execute(f"""
        SELECT iu.*,
               'WAIT' as scan_decision,
               tsc.strategy_type as classified_strategy,
               tsc.confidence as classification_confidence
        FROM incubator_universe iu
        JOIN ticker_strategy_classifications tsc
            ON tsc.symbol = iu.symbol
            AND tsc.strategy_type = iu.strategy_id
            AND tsc.active = true
        WHERE iu.status = 'ACTIVE'
          AND iu.strategy_id IN ({strat_list})
          AND iu.latest_score >= {_DIVERSITY_SCORE_FLOOR}
          AND iu.promoted_to_proposal_at IS NULL
          AND iu.days_active >= 1
          AND COALESCE(iu.llm_screen_verdict, 'HOLD') != 'DROP'
          -- Skip strategies that already have pending proposals
          AND iu.strategy_id NOT IN (
              SELECT DISTINCT strategy_id FROM paper_trade_proposals
              WHERE status = 'PENDING'
          )
        ORDER BY
            -- Prioritize strategies with zero proposals ever
            CASE WHEN iu.strategy_id NOT IN (
                SELECT DISTINCT strategy_id FROM paper_trade_proposals
            ) THEN 0 ELSE 1 END,
            tsc.confidence DESC NULLS LAST,
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
    """Return (price, screener_label) from most recent trade_ai_scans row (max 3 days old)."""
    cur.execute("""
        SELECT price, screener_label FROM trade_ai_scans
        WHERE symbol = %s
        AND scanned_at > NOW() - INTERVAL '3 days'
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

def run(dry_run=True, limit=10, force_symbol=None, max_per_symbol=1):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Auto-expire stale proposals first (always, even on dry-run preview)
    if not dry_run:
        _auto_expire_stale_proposals(conn)

    # Strategy-aware promotion gate
    can_promote, gate_reason = _check_promotion_gate(conn)
    if not can_promote and not force_symbol:
        log.warning(f"[promoter] Gate blocked: {gate_reason}")
        return [f"GATE BLOCKED: {gate_reason}"], 0, 0

    # Merge screener candidates + classification-based candidates for diversity
    candidates = fetch_candidates(cur, force_symbol=force_symbol, limit=limit)
    if not force_symbol:
        classification_candidates = fetch_classification_candidates(cur, limit=max(5, limit // 2))
        # Deduplicate by (symbol, strategy_id)
        seen = {(c['symbol'], c['strategy_id']) for c in candidates}
        for cc in classification_candidates:
            if (cc['symbol'], cc['strategy_id']) not in seen:
                candidates.append(cc)
                seen.add((cc['symbol'], cc['strategy_id']))
        log.info(f"[promoter] {len(candidates)} candidates ({len(classification_candidates)} from classifications)")
    promoted = 0
    skipped = 0
    results = []
    symbol_counts: dict = {}  # track groups promoted per symbol this run {symbol: set(groups)}

    # Load existing PENDING proposals per symbol+group for strategy-group dedup
    cur.execute("""SELECT symbol, strategy_id FROM paper_trade_proposals WHERE status='PENDING'""")
    existing_groups: dict = {}  # {symbol: set of groups}
    existing_pending: dict = {}  # {symbol: count}
    for r in cur.fetchall():
        s = r['symbol']
        g = STRATEGY_GROUPS.get(r['strategy_id'], 'OTHER')
        existing_groups.setdefault(s, set()).add(g)
        existing_pending[s] = existing_pending.get(s, 0) + 1

    for c in candidates:
        symbol = c['symbol']
        strategy_id = c['strategy_id']

        # Strategy performance gate (operator 2026-06-19, Task 4): block promotion from a strategy with a
        # real losing record (>=10 closed at <25% WR). <5 closed = eligible. Read-only, dormant today.
        try:
            import strategy_utils as _su
            _gok, _greason = _su.is_strategy_promotable(strategy_id, conn)
            if not _gok:
                results.append(f"SKIPPED: {symbol} (strategy gate: {_greason})")
                skipped += 1
                if not dry_run:
                    _su.log_suppression(conn, symbol, strategy_id, _greason)
                continue
        except Exception:
            pass

        # Symbol-wide active guard (includes APPROVED_FOR_PAPER_TEST / broker queue rows)
        try:
            from broker_queue_hygiene import find_active_symbol_proposal
            _active = find_active_symbol_proposal(symbol)
            if _active:
                results.append(
                    f"SKIPPED: {symbol} (active proposal #{_active.get('id')} {_active.get('status')})"
                )
                skipped += 1
                continue
        except Exception:
            pass

        # Strategy-group dedup: max 1 proposal per symbol per strategy group
        group = STRATEGY_GROUPS.get(strategy_id, 'OTHER')
        sym_groups = existing_groups.get(symbol, set()) | symbol_counts.get(symbol, set())
        if group in sym_groups:
            results.append(f"SKIPPED: {symbol} (group {group} already pending)")
            skipped += 1
            continue
        # Max 2 total per symbol (across all groups)
        total_pending = existing_pending.get(symbol, 0) + len(symbol_counts.get(symbol, set()))
        if total_pending >= max_per_symbol:
            results.append(f"SKIPPED: {symbol} (total_pending={total_pending} >= max={max_per_symbol})")
            skipped += 1
            continue
        score = c['latest_score']
        days_active = c['days_active'] or 0
        catalyst_verified = c['catalyst_verified']

        # Gate check (force-symbol bypasses score gates but not pending check)
        if not force_symbol:
            # Classification strategies (income, dividend, etc.) don't require catalysts
            is_classification = strategy_id in _CLASSIFICATION_STRATEGIES
            if not is_classification and not catalyst_verified and (score is None or score < 45):
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

        # Price lookup — scan → evidence → live quote fallback
        scan_price, screener_label = get_scan_price(cur, symbol)
        if scan_price is None:
            scan_price = extract_evidence_price(c.get('evidence_payload'))
        if scan_price is None:
            try:
                from market_quote_provider import get_best_quote
                _lq = get_best_quote(symbol)
                if _lq and _lq.get('last_price') and _lq['last_price'] > 0:
                    scan_price = _lq['last_price']
                    screener_label = f"live_quote_{_lq.get('provider', 'unknown')}"
            except Exception:
                pass
        if scan_price is None or scan_price <= 0:
            results.append(f"SKIPPED: {symbol} (no_price)")
            skipped += 1
            continue
        if scan_price < 1.0:
            results.append(f"SKIPPED: {symbol} (penny_stock ${scan_price:.2f})")
            skipped += 1
            continue

        # Live price validation — reject if scan price drifted >3% from live
        try:
            from market_quote_provider import get_best_quote as _gpq
            _live = _gpq(symbol)
            if _live and _live.get('last_price') and _live['last_price'] > 0:
                _live_px = float(_live['last_price'])
                _drift = abs(_live_px - scan_price) / scan_price * 100
                if _drift > 3.0:
                    log.warning(f"  {symbol}: scan price ${scan_price:.2f} drifted {_drift:.1f}% from live ${_live_px:.2f} — using live price")
                    scan_price = _live_px
        except Exception:
            pass

        # Strategy-aware minimum price — momentum/scalp need higher floor
        _MOMENTUM_STRATEGIES = {'momentum_scalp', 'gap_and_go', 'earnings_catalyst',
                                'screener', 'speculative_growth', 'earnings_post_momentum'}
        _min_price = 3.0 if strategy_id in _MOMENTUM_STRATEGIES else 1.0
        if scan_price < _min_price:
            results.append(f"SKIPPED: {symbol} (below_min_price ${scan_price:.2f} < ${_min_price:.0f} for {strategy_id})")
            skipped += 1
            continue

        # Spread gate — family-specific threshold (MAP-4)
        try:
            from market_quote_provider import get_best_quote
            from promoter_family_threshold_policy import get_family_thresholds, get_strategy_family
            _quote = get_best_quote(symbol)
            _spread = _quote.get("spread_pct") if _quote else None
            _family_th = get_family_thresholds(strategy_id)
            _max_spread = _family_th.get("max_spread_pct", 3.0)
            _family = get_strategy_family(strategy_id)
            if _spread is not None and _spread > _max_spread:
                results.append(f"SKIPPED: {symbol} (spread_{_spread:.1f}pct > {_max_spread}% for {_family})")
                skipped += 1
                continue
        except Exception:
            pass  # If quote/policy fetch fails, let later gates catch it

        # RSI gate — block overbought at promotion time
        can_rsi, rsi_reason, rsi_value = _check_rsi_gate(symbol, strategy_id, conn)
        if not can_rsi:
            results.append(f"SKIPPED: {symbol} ({rsi_reason})")
            skipped += 1
            continue

        # MAP-4: Block generic strategy_id='screener' — must be a real strategy
        if strategy_id == 'screener':
            results.append(f"SKIPPED: {symbol} (generic_strategy_id_screener — classify first)")
            skipped += 1
            continue

        entry, stop, target, shares = compute_levels(scan_price)

        # Compute R:R (BUGFIX-RR-1: was undefined, caused NameError in pre-promotion + Telegram alert)
        rr = round((target - entry) / (entry - stop), 2) if entry > stop and target > entry else 0

        # Timeframe + strategy type stamp
        strategy_key = strategy_id if isinstance(strategy_id, str) else str(strategy_id)
        timeframe_class, expires_hours = TIMEFRAME_MAP.get(strategy_key, DEFAULT_TIMEFRAME)
        try:
            from proposal_lifecycle import get_strategy_metadata
            _strat_type = get_strategy_metadata(strategy_key).get("strategy_type")
        except Exception:
            _strat_type = (timeframe_class or "").upper()
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

        # ATP-5: Get scan age for quote-age gate
        # MAP-5D: Also check market_quote_snapshots for quote age
        _scan_age_hours = None
        _quote_age_hours = None
        _quote_checked_at = None
        try:
            cur.execute("""SELECT EXTRACT(EPOCH FROM NOW() - MAX(scanned_at))/3600 as age_h
                FROM trade_ai_scans WHERE symbol = %s""", [symbol])
            _sa_row = cur.fetchone()
            if _sa_row and _sa_row.get('age_h') is not None:
                _scan_age_hours = float(_sa_row['age_h'])
        except Exception as _e1:
            log.warning(f"[promoter] scan_age query failed for {symbol}: {_e1}")
            try: conn.rollback()
            except: pass
        try:
            cur.execute("""SELECT EXTRACT(EPOCH FROM NOW() - MAX(created_at))/3600 as age_h,
                MAX(created_at) as checked_at
                FROM market_quote_snapshots WHERE symbol = %s""", [symbol])
            _qa_row = cur.fetchone()
            if _qa_row and _qa_row.get('age_h') is not None:
                _quote_age_hours = float(_qa_row['age_h'])
                _quote_checked_at = _qa_row.get('checked_at')
        except Exception as _e2:
            log.warning(f"[promoter] quote_age query failed for {symbol}: {_e2}")
            try: conn.rollback()
            except: pass

        # PROMOTE-1: Pre-promotion readiness gate (with ATP-5 quote-age data)
        try:
            from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
            _gate_input = {
                "symbol": symbol, "strategy_id": strategy_id,
                "proposed_entry": entry, "proposed_stop": stop, "proposed_target1": target,
                "proposed_rr": rr, "catalyst": c.get("catalyst"), "catalyst_verified": catalyst_verified,
                "discovery_source": "incubator",
                "scan_age_hours": _scan_age_hours,
                "quote_age_hours": _quote_age_hours,
                "quote_checked_at": _quote_checked_at,
            }
            log.debug(f"[promoter] gate: {symbol} scan_age={_scan_age_hours}, quote_age={_quote_age_hours}")
            _pre_check = evaluate_pre_promotion_readiness(_gate_input)
            if _pre_check["blockers"]:
                log.warning(f"[promoter] BLOCKED by pre-promotion gate: {symbol} — {_pre_check['blockers']}")
                skipped += 1
                results.append(f"BLOCKED_PRE_PROMOTION: {symbol} ({strategy_key}) — {_pre_check['blockers'][:2]}")
                continue
        except Exception as _e:
            log.warning(f"[promoter] Pre-promotion check failed for {symbol}: {_e}")

        # Risk gate check
        _rg_result = None
        _rg_codes = None
        try:
            from risk_gate import RiskGate
            _rg = RiskGate(conn)
            _rg_plan = {"entry": entry, "stop": stop, "target1": target, "shares": shares, "rr": rr}
            _rg_decision = _rg.check(symbol, strategy_id, trade_plan=_rg_plan, mode='paper')
            _rg_result = _rg_decision.result
            _rg_codes = _rg_decision.codes if hasattr(_rg_decision, 'codes') else []
        except Exception as _rg_e:
            log.warning(f"[promoter] Risk gate check failed for {symbol}: {_rg_e}")
            _rg_result = "PASS"  # fail-open for promoter path — downstream gates still protect

        # INSERT proposal
        cur.execute("""
            INSERT INTO paper_trade_proposals
                (symbol, strategy_id, primary_strategy_id,
                 proposed_entry, proposed_stop, proposed_target1,
                 proposed_shares, proposed_rr, proposed_dollar_risk,
                 target_account,
                 status, expires_at, lifecycle_status,
                 entry_zone_status, proposal_timeframe_class, strategy_type,
                 screener_name, source_table, discovery_source, source_run_label,
                 signal_score, signal_grade, catalyst, catalyst_verified,
                 setup_type, proposed_by, overnight_monitoring_enabled,
                 rsi, risk_gate_result, risk_gate_codes,
                 packet_state, packet_completion_pct,
                 llm_review_status, agent_review_status)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    'PENDING', %s, 'ACTIVE',
                    'NEEDS_PRICE_CHECK', %s, %s,
                    %s, 'incubator_universe', 'incubator', %s,
                    %s, %s, %s, %s,
                    %s, 'incubator_promoter', %s,
                    %s, %s, %s,
                    'NEW', 0,
                    'NOT_REQUESTED', 'NOT_REQUESTED')
            RETURNING id
        """, [
            symbol, strategy_id, strategy_id,
            entry, stop, target,
            shares, rr, round(abs(entry - stop) * shares, 2),
            None,  # target_account unset — operator picks paper or broker at promote/approve
            expires_at, timeframe_class, _strat_type,
            screener_name, source_run_label,
            score, signal_grade, c.get('catalyst'), catalyst_verified,
            setup_display, overnight,
            rsi_value, _rg_result, json.dumps(_rg_codes or []),
        ])
        new_id = cur.fetchone()['id']

        # SP-2C: Generate route audit evidence
        try:
            from proposal_route_audit_integration import ensure_route_audit_for_proposal
            _candidate = {
                "symbol": symbol, "price": entry, "rvol": c.get("rvol_latest"),
                "float_m": c.get("float_m"), "gap_pct": c.get("gap_latest"),
                "score": score, "decision": "GO",
                "catalyst": c.get("catalyst"), "catalyst_verified": catalyst_verified,
                "sector": c.get("sector"), "industry": c.get("industry"),
            }
            ensure_route_audit_for_proposal(
                conn, new_id, symbol, strategy_id,
                _candidate, source="incubator_promoter"
            )
        except Exception as _e:
            log.warning(f"[route_audit] Failed for promoted proposal #{new_id}: {_e}")

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
        symbol_counts.setdefault(symbol, set()).add(STRATEGY_GROUPS.get(strategy_id, 'OTHER'))

        # ALERT-1: Send Telegram alert for new proposal
        try:
            from telegram_proposal_alert_policy import build_proposal_alert_packet, format_telegram_message
            _alert_pr = {
                "id": new_id, "symbol": symbol, "strategy_id": strategy_id,
                "proposed_entry": entry, "proposed_stop": stop, "proposed_target1": target,
                "proposed_shares": shares, "proposed_rr": rr, "status": "PENDING",
                "catalyst": c.get("catalyst"), "catalyst_verified": catalyst_verified,
                "sector": c.get("sector"), "industry": c.get("industry"),
                "operator_verdict": "NEEDS_REVIEW",
                "approval_allowed": False,
                "approval_blockers": [
                    {"reason": "New proposal — run Check Execution for live quote"},
                    {"reason": "Enrichment pending — review in Command Center → Trading → Proposals"},
                ],
            }
            _pkt = build_proposal_alert_packet(_alert_pr)
            _msg = format_telegram_message(_pkt)
            from telegram_alert import send_telegram
            send_telegram(_msg)
        except Exception as _ae:
            log.warning(f"[alert] Telegram alert failed for #{new_id}: {_ae}")
        results.append(f"PROMOTED: {symbol} ({strategy_key}, score={score}, {screener_name})")

    # Post-run: rank proposals per symbol (Phase 6)
    promoted_symbols = set()
    for r in results:
        if r.startswith("PROMOTED:"):
            sym = r.split("PROMOTED:")[1].strip().split(" ")[0]
            promoted_symbols.add(sym)
    if promoted_symbols:
        try:
            from auto_proposal_generator import rank_proposals_for_symbol
            for sym in promoted_symbols:
                rank_proposals_for_symbol(conn, sym, window_hours=24)
        except Exception as e:
            log.warning(f"[promoter] Ranking pass failed: {e}")

    cur.close()
    if conn and not conn.closed:
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
    parser.add_argument('--max-proposals-per-symbol', type=int, default=1, help='Max proposals per symbol (strongest strategy only)')
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
