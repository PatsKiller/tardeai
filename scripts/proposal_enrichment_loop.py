#!/usr/bin/env python3
"""proposal_enrichment_loop.py — Continuous enrichment for pending proposals.

Enriches proposals toward decision-grade packets: price refresh, strategy identity,
technical snapshots, catalyst quality, execution readiness, agent + LLM review queueing.

Usage:
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --dry-run
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --run
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --run --limit 5
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --run --no-llm
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --run --proposal-id 43
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --run --symbol FNKO
    .venv/bin/python3 scripts/proposal_enrichment_loop.py --queue-llm-only --run
"""
import argparse
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

from pipeline_registry import PipelineRun

log = logging.getLogger("proposal_enrichment")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

BATCH_SIZE = 15

# Entry zone thresholds
ZONE_TIGHT = {'valid': 3.0, 'marginal': 7.0}   # intraday, short_swing
ZONE_WIDE = {'valid': 5.0, 'marginal': 12.0}    # swing, event_window, position
WIDE_TIMEFRAMES = {'swing', 'event_window', 'position'}

# Packet completion weights (out of 100)
WEIGHTS = {
    'source': 10, 'strategy': 15, 'catalyst': 15, 'technical': 15,
    'risk': 10, 'execution': 15, 'agents': 10, 'llm': 10,
}


def get_db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ── Quote ──────────────────────────────────────────────────────────────

def get_live_price(symbol):
    """Return (price, source) using market_quote_provider or yfinance fallback."""
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(symbol)
        price = q.get("last_price")
        if price and price > 0:
            return float(price), q.get("provider", "unknown")
    except Exception:
        pass
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        price = t.fast_info.get("lastPrice") or t.fast_info.get("last_price")
        if price and price > 0:
            return float(price), "yfinance"
    except Exception:
        pass
    return None, "none"


def classify_entry_zone(drift_pct, timeframe_class):
    t = ZONE_WIDE if timeframe_class in WIDE_TIMEFRAMES else ZONE_TIGHT
    d = abs(drift_pct)
    if d <= t['valid']:
        return 'ENTRY_ZONE_VALID'
    elif d <= t['marginal']:
        return 'ENTRY_ZONE_MARGINAL'
    return 'ENTRY_MISSED'


# ── Strategy identity ─────────────────────────────────────────────────

def ensure_strategy_identity(conn, proposal):
    """Populate primary_strategy_id and setup_stack if missing or generic 'screener'."""
    pid = proposal['id']
    primary = proposal.get('primary_strategy_id')
    if primary and primary != 'screener' and proposal.get('setup_stack'):
        return False  # already set with real strategy

    symbol = proposal['symbol']
    strategy_id = proposal['strategy_id']
    try:
        from strategy_config_loader import load_all_strategy_configs
        from multi_setup_router import route_symbol
        configs = load_all_strategy_configs()
        signal = {
            'strategy_id': strategy_id,
            'symbol': symbol,
            'score': float(proposal.get('signal_score') or 0),
            'rvol': float(proposal.get('rvol') or 0),
            'catalyst_verified': proposal.get('catalyst_verified') or False,
        }
        result = route_symbol(symbol, signal, configs)
        primary = result.get('primary_strategy_id') or strategy_id
        secondaries = result.get('secondary_strategy_ids') or []
        stack = result.get('setup_stack') or []

        cur = conn.cursor()
        cur.execute("""
            UPDATE paper_trade_proposals
            SET primary_strategy_id = %s,
                secondary_strategy_ids = %s,
                setup_stack = %s
            WHERE id = %s AND (primary_strategy_id IS NULL OR setup_stack IS NULL)
        """, [primary, json.dumps(secondaries), json.dumps(stack), pid])
        conn.commit()
        return True
    except Exception as e:
        log.debug(f"[strategy] {symbol}: {e}")
        # Fallback: set primary = strategy_id
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE paper_trade_proposals
                SET primary_strategy_id = COALESCE(primary_strategy_id, strategy_id)
                WHERE id = %s AND primary_strategy_id IS NULL
            """, [pid])
            conn.commit()
        except Exception:
            pass
        return False


# ── Company profile ────────────────────────────────────────────────────

def ensure_symbol_profile(conn, proposal):
    """Build the company profile (symbol_profiles.description_1s) for a proposal symbol that lacks one,
    so a LIVE proposal never shows 'No company profile' (the TECH gap: the symbol wasn't in the 06:45
    build_symbol_profiles --watchlist-top 300 run, so it had no row). One-shot per new symbol — skipped
    once a profile exists."""
    sym = (proposal.get('symbol') or '').upper()
    if not sym:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM symbol_profiles WHERE symbol=%s AND COALESCE(description_1s,'') <> ''", (sym,))
        if cur.fetchone():
            return False  # already profiled
    except Exception:
        return False
    try:
        import subprocess as _sp, sys as _sys
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        _sp.run([_sys.executable, str(root / 'scripts' / 'build_symbol_profiles.py'), '--symbols', sym, '--force'],
                cwd=str(root), capture_output=True, text=True, timeout=120)
        log.info(f"  [profile] built missing company profile for {sym}")
        return True
    except Exception as e:
        log.warning(f"  [profile] failed building profile for {sym}: {str(e)[:120]}")
        return False


# ── Technical snapshot ─────────────────────────────────────────────────

def refresh_technical(conn, proposal):
    """Run technical snapshot if missing or stale (>4h)."""
    pid = proposal['id']
    # Check if we have a recent snapshot
    cur = conn.cursor()
    cur.execute("""
        SELECT computed_at FROM proposal_technical_snapshots
        WHERE proposal_id = %s ORDER BY computed_at DESC LIMIT 1
    """, [pid])
    row = cur.fetchone()
    if row and row[0]:
        age_h = (datetime.now(timezone.utc) - row[0].replace(tzinfo=timezone.utc if row[0].tzinfo is None else row[0].tzinfo)).total_seconds() / 3600
        if age_h < 4:
            return False  # fresh enough

    try:
        from proposal_technical_snapshot import generate_snapshot
        generate_snapshot(conn, proposal_id=pid)
        return True
    except Exception as e:
        log.debug(f"[tech] #{pid}: {e}")
        return False


# ── Catalyst quality ───────────────────────────────────────────────────

def refresh_catalyst(conn, proposal):
    """Evaluate catalyst quality if missing."""
    if proposal.get('catalyst_quality') or not proposal.get('catalyst'):
        return False
    try:
        from proposal_catalyst_quality import assess_proposal as assess_catalyst
        assess_catalyst(conn, proposal)
        return True
    except Exception as e:
        log.debug(f"[catalyst] #{proposal['id']}: {e}")
        return False


# ── Execution readiness ───────────────────────────────────────────────

def refresh_execution(conn, proposal):
    """Check execution readiness if missing or stale."""
    pid = proposal['id']
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at FROM proposal_execution_readiness
        WHERE proposal_id = %s ORDER BY created_at DESC LIMIT 1
    """, [pid])
    row = cur.fetchone()
    if row and row[0]:
        age_h = (datetime.now(timezone.utc) - row[0].replace(tzinfo=timezone.utc if row[0].tzinfo is None else row[0].tzinfo)).total_seconds() / 3600
        if age_h < 1:
            return False

    try:
        from proposal_execution_readiness import assess_proposal as assess_exec, write_readiness
        result = assess_exec(conn, dict(proposal))
        if result:
            write_readiness(conn, result)
            return True
    except Exception as e:
        log.debug(f"[exec] #{pid}: {e}")
    return False


# ── Strategy fit ───────────────────────────────────────────────────────

def refresh_strategy_fit(conn, proposal):
    """Score strategy fit if missing."""
    if proposal.get('strategy_fit') and isinstance(proposal.get('strategy_fit'), dict):
        return False
    try:
        from proposal_strategy_fit import score_proposal
        score_proposal(conn, proposal['id'])
        return True
    except Exception as e:
        log.debug(f"[fit] #{proposal['id']}: {e}")
        return False


# ── Agent review queue ─────────────────────────────────────────────────

def queue_agent_reviews(conn, proposal):
    """Queue agent reviews if none exist for this proposal."""
    pid = proposal['id']
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(DISTINCT agent_name) FROM proposal_agent_reviews
        WHERE proposal_id = %s AND status != 'pending'
    """, [pid])
    count = cur.fetchone()[0]
    # Only stand down when ALL THREE agents have reviewed. The old >=1 short-circuit stranded
    # partial sets forever (#1348: steph+risk done, maria's job lost, never re-queued).
    # queue_run dedups per proposal+agent, so re-calling for the missing agent is safe.
    if count >= 3:
        return False

    try:
        from queue_proposal_agent_reviews import run as queue_run
        queue_run(symbol=proposal['symbol'], dry_run=False)
        cur.execute("""
            UPDATE paper_trade_proposals
            SET agent_review_status = 'QUEUED'
            WHERE id = %s AND (agent_review_status IS NULL OR agent_review_status = 'NOT_REQUESTED')
        """, [pid])
        conn.commit()
        return True
    except Exception as e:
        log.debug(f"[agents] #{pid}: {e}")
        return False


# ── LLM review queue ──────────────────────────────────────────────────

def queue_llm_review(conn, proposal):
    """Queue for LLM review if not already queued/complete."""
    pid = proposal['id']
    symbol = proposal['symbol']
    strategy_id = proposal.get('strategy_id')

    cur = conn.cursor()
    # Check if already in queue
    cur.execute("SELECT queue_status FROM proposal_llm_review_queue WHERE proposal_id = %s", [pid])
    row = cur.fetchone()
    if row:
        return False  # already queued

    # Check if already reviewed
    cur.execute("""
        SELECT COUNT(*) FROM paper_proposal_analysis WHERE proposal_id = %s
    """, [pid])
    if cur.fetchone()[0] > 0:
        return False

    try:
        cur.execute("""
            INSERT INTO proposal_llm_review_queue (proposal_id, symbol, strategy_id, priority)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (proposal_id) DO NOTHING
        """, [pid, symbol, strategy_id, 3])
        cur.execute("""
            UPDATE paper_trade_proposals
            SET llm_review_status = 'QUEUED', llm_review_queued_at = NOW()
            WHERE id = %s AND (llm_review_status IS NULL OR llm_review_status = 'NOT_REQUESTED')
        """, [pid])
        conn.commit()
        return True
    except Exception as e:
        log.debug(f"[llm_queue] #{pid}: {e}")
        return False


# ── Missing data computation ──────────────────────────────────────────

def compute_missing_data(proposal):
    """Compute missing_data_by_section dict."""
    missing = {
        'critical': [], 'strategy': [], 'technical': [], 'catalyst': [],
        'execution': [], 'risk_reward': [], 'backtest': [], 'agents': [], 'llm': [],
    }

    # Critical
    if not proposal.get('proposed_entry'):
        missing['critical'].append('proposed_entry_missing')
    if not proposal.get('proposed_stop'):
        missing['critical'].append('proposed_stop_missing')
    if not proposal.get('proposed_shares'):
        missing['critical'].append('proposed_shares_missing')

    # Strategy
    if not proposal.get('primary_strategy_id'):
        missing['strategy'].append('primary_strategy_missing')
    if not proposal.get('setup_stack'):
        missing['strategy'].append('setup_stack_missing')

    # Technical
    if not proposal.get('rsi') and not proposal.get('technical_snapshot'):
        missing['technical'].append('technical_snapshot_missing')
    if not proposal.get('atr'):
        missing['technical'].append('atr_missing')
    if not proposal.get('rsi'):
        missing['technical'].append('rsi_missing')
    if not proposal.get('vwap_distance') and proposal.get('vwap_distance') != 0:
        missing['technical'].append('vwap_missing')

    # Catalyst
    if not proposal.get('catalyst'):
        missing['catalyst'].append('catalyst_missing')
    if not proposal.get('catalyst_verified'):
        missing['catalyst'].append('catalyst_unverified')
    if not proposal.get('news') and not proposal.get('recent_headlines'):
        missing['catalyst'].append('recent_news_missing')

    # Execution
    er = proposal.get('execution_readiness') or {}
    if not er:
        missing['execution'].append('execution_readiness_missing')
    elif not er.get('quote_price'):
        missing['execution'].append('quote_provider_missing')
    if proposal.get('entry_zone_status') in ('NEEDS_PRICE_CHECK', None):
        missing['execution'].append('entry_zone_needs_price_check')

    # Risk/Reward
    entry = float(proposal.get('proposed_entry') or 0)
    stop = float(proposal.get('proposed_stop') or 0)
    t1 = float(proposal.get('proposed_target1') or 0)
    if entry and stop and t1:
        rr = (t1 - entry) / (entry - stop) if entry > stop else 0
        if rr < 2.0:
            missing['risk_reward'].append('rr_below_strategy_minimum')
    if not proposal.get('risk_gate_result'):
        missing['risk_reward'].append('risk_gate_pending')

    # Backtest
    bt = proposal.get('backtest_summary')
    if not bt:
        missing['backtest'].append('backtest_missing')
    elif isinstance(bt, dict) and (bt.get('sample_size') or 0) < 20:
        missing['backtest'].append('backtest_learning_mode')

    # Agents
    reviews = proposal.get('agent_reviews') or []
    if not reviews or len(reviews) == 0:
        missing['agents'].append('agent_reviews_missing')

    # LLM
    llm = proposal.get('llm_analysis')
    if not llm:
        missing['llm'].append('llm_review_missing')
    elif isinstance(llm, dict) and 'fallback' in str(llm.get('narrative_source', '')).lower():
        missing['llm'].append('llm_review_fallback_only')

    return missing


def compute_completion_pct(missing):
    """Compute packet completion percentage from missing data sections."""
    total = sum(WEIGHTS.values())
    earned = 0
    for section, weight in WEIGHTS.items():
        items = missing.get(section, [])
        if not items:
            earned += weight
        elif len(items) == 1:
            earned += weight * 0.5  # partially complete
    return round(earned / total * 100, 1)


# ── Action state ──────────────────────────────────────────────────────

def compute_action_state(proposal, missing):
    """Compute action_state, action_label, top_blocker, next_actions."""
    rg = proposal.get('risk_gate_result')
    er = proposal.get('execution_readiness') or {}
    rs = er.get('readiness_state', '')
    ez = proposal.get('entry_zone_status', '')
    lc = proposal.get('lifecycle_status', '')

    # BLOCKED
    if rg in ('REJECTED', 'FAIL'):
        return 'BLOCKED', 'Risk Gate Rejected', f'Risk gate: {rg}', ['Review risk parameters']
    if 'BLOCKED' in rs.upper():
        return 'BLOCKED', f'Execution Blocked', rs, ['Check execution readiness']

    # NEEDS_REVIEW
    if ez == 'ENTRY_MISSED' or lc == 'ENTRY_MISSED':
        return 'NEEDS_REVIEW', 'Entry Missed', f'Price drifted from zone', ['Review entry or dismiss']

    # Count critical missing
    all_missing = sum(len(v) for v in missing.values())
    critical_missing = len(missing.get('critical', []))
    if critical_missing > 0:
        return 'MISSING_DATA', f'{critical_missing} critical fields missing', missing['critical'][0], ['Fill critical data']

    if all_missing >= 6:
        return 'MISSING_DATA', f'{all_missing} data gaps', 'Multiple sections incomplete', _build_next_actions(missing)

    # LEARNING_MODE
    bt = proposal.get('backtest_summary')
    if isinstance(bt, dict) and (bt.get('sample_size') or 0) < 20 and all_missing < 4:
        return 'LEARNING_MODE', 'Backtest learning mode', 'Insufficient sample size', ['Run more backtests']

    # PAPER_READY
    if all_missing <= 2 and ez in ('ENTRY_ZONE_VALID', 'ENTRY_ZONE_MARGINAL'):
        if rs in ('READY_FOR_PAPER_SUBMIT', 'READY_ORB_CONFIRMED', 'CAUTION_EXECUTABLE') or not rs:
            return 'PAPER_READY', 'Paper Ready', 'None', []

    # CAUTION
    return 'CAUTION', 'Review before proceeding', _build_top_blocker(missing), _build_next_actions(missing)


def _build_top_blocker(missing):
    for section in ['critical', 'execution', 'technical', 'catalyst', 'agents', 'llm']:
        items = missing.get(section, [])
        if items:
            return items[0]
    return 'None'


def _build_next_actions(missing):
    actions = []
    if missing.get('technical'):
        actions.append('Run Technical Snapshot')
    if missing.get('execution'):
        actions.append('Check Execution Readiness')
    if missing.get('catalyst'):
        actions.append('Run Research')
    if missing.get('agents'):
        actions.append('Run AI Review')
    if missing.get('llm'):
        actions.append('Queue LLM Review')
    if missing.get('backtest'):
        actions.append('Run Backtest')
    return actions[:4]


# ── Packet state ──────────────────────────────────────────────────────

def compute_packet_state(action_state, completion_pct, missing):
    """Derive packet_state from action_state and completion."""
    if action_state == 'BLOCKED':
        return 'BLOCKED'
    if action_state == 'PAPER_READY':
        return 'READY_FOR_REVIEW'
    if action_state == 'MISSING_DATA':
        return 'MISSING_DATA'
    all_missing = sum(len(v) for v in missing.values())
    if all_missing == 0:
        return 'READY_FOR_REVIEW'
    if completion_pct >= 50:
        return 'PARTIAL'
    return 'ENRICHING'


# ── Write audit event ─────────────────────────────────────────────────

def write_event(conn, pid, symbol, event_type, stage=None, status=None, message=None, payload=None):
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO proposal_enrichment_events
                (proposal_id, symbol, event_type, stage, status, message, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, [pid, symbol, event_type, stage, status, message, json.dumps(payload) if payload else None])
        conn.commit()
    except Exception:
        pass


# ── Main enrichment for one proposal ──────────────────────────────────

def fetch_pending_proposals(conn, limit=BATCH_SIZE, proposal_id=None, symbol=None):
    """Get pending proposals for enrichment."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if proposal_id:
        cur.execute("SELECT * FROM paper_trade_proposals WHERE id = %s", [proposal_id])
    elif symbol:
        cur.execute("SELECT * FROM paper_trade_proposals WHERE symbol = %s AND status = 'PENDING' ORDER BY created_at DESC", [symbol.upper()])
    else:
        cur.execute("""
            SELECT * FROM paper_trade_proposals
            WHERE status = 'PENDING'
              AND proposed_entry IS NOT NULL AND proposed_entry > 0
            ORDER BY
                CASE WHEN COALESCE(sizing_basis->>'routing_lane','') = 'live_2fa' THEN 0
                     WHEN COALESCE(target_account, proposed_account,'') LIKE 'schwab%%' THEN 0
                     ELSE 1 END,
                CASE lifecycle_status
                    WHEN 'ENTRY_ZONE_VALID' THEN 1 WHEN 'ACTIVE' THEN 2
                    WHEN 'NEEDS_REVIEW' THEN 3 WHEN 'ENTRY_MISSED' THEN 4 ELSE 5
                END,
                packet_last_enriched_at ASC NULLS FIRST
            LIMIT %s
        """, [limit])
    return [dict(r) for r in cur.fetchall()]


def enrich_one(conn, proposal, dry_run=False, no_llm=False, queue_llm_only=False):
    """Enrich a single proposal. Returns summary dict."""
    pid = proposal['id']
    symbol = proposal['symbol']
    entry = float(proposal.get('proposed_entry') or 0)
    timeframe = proposal.get('proposal_timeframe_class') or 'short_swing'
    actions = []

    if queue_llm_only:
        queued = queue_llm_review(conn, proposal)
        if queued:
            actions.append('llm_queued')
        return {'id': pid, 'symbol': symbol, 'actions': actions}

    # 1. Strategy identity
    if ensure_strategy_identity(conn, proposal):
        actions.append('strategy_identity')

    # 1a. Company profile — build it if this symbol has none, so the card never shows
    # "No company profile" on a live proposal (the TECH gap).
    if not dry_run and ensure_symbol_profile(conn, proposal):
        actions.append('company_profile')

    # 1b. Sector/industry backfill from latest scan
    if not dry_run and not proposal.get('sector'):
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE paper_trade_proposals p
                SET sector = s.sector, industry = s.industry
                FROM (
                    SELECT sector, industry FROM trade_ai_scans
                    WHERE symbol = %s AND sector IS NOT NULL
                    ORDER BY scanned_at DESC LIMIT 1
                ) s
                WHERE p.id = %s AND p.sector IS NULL
            """, [symbol, pid])
            if cur.rowcount > 0:
                conn.commit()
                actions.append('sector_backfill')
            else:
                conn.rollback()
        except Exception:
            try: conn.rollback()
            except: pass

    # 2. Price refresh
    price, source = get_live_price(symbol)
    if price and entry > 0:
        drift_pct = round((price - entry) / entry * 100, 2)
        zone = classify_entry_zone(drift_pct, timeframe)
        new_lifecycle = 'ENTRY_ZONE_VALID' if zone == 'ENTRY_ZONE_VALID' else (
            'ACTIVE' if zone == 'ENTRY_ZONE_MARGINAL' else 'ENTRY_MISSED')
        expired = zone == 'ENTRY_MISSED' and abs(drift_pct) > 15

        if not dry_run:
            cur = conn.cursor()
            if expired:
                cur.execute("""
                    UPDATE paper_trade_proposals
                    SET current_price=%s, price_drift_pct=%s, entry_zone_status=%s,
                        lifecycle_status='EXPIRED', status='EXPIRED',
                        lifecycle_message='Entry missed — price drifted >15%%',
                        last_price_checked_at=NOW(), last_price_source=%s, updated_at=NOW()
                    WHERE id=%s
                """, [price, drift_pct, zone, source, pid])
            else:
                cur.execute("""
                    UPDATE paper_trade_proposals
                    SET current_price=%s, price_drift_pct=%s, entry_zone_status=%s,
                        lifecycle_status=%s, last_price_checked_at=NOW(),
                        last_price_source=%s, updated_at=NOW()
                    WHERE id=%s
                """, [price, drift_pct, zone, new_lifecycle, source, pid])
            conn.commit()

        actions.append(f'price={price:.2f} drift={drift_pct:+.1f}% zone={zone}')
        if expired:
            actions.append('AUTO_EXPIRED')
            return {'id': pid, 'symbol': symbol, 'actions': actions, 'expired': True}

        # Immediate ATM trigger when proposal reaches ENTRY_ZONE_VALID (safe_flock + in-process flock)
        if new_lifecycle == 'ENTRY_ZONE_VALID' and not dry_run:
            try:
                import subprocess as _sp
                _proj = Path(__file__).resolve().parent.parent
                _atm_log = _proj / "logs" / "atm_immediate.log"
                _atm_log.parent.mkdir(parents=True, exist_ok=True)
                _log_fh = open(_atm_log, "a")
                _sp.Popen(
                    [
                        "bash",
                        str(_proj / "scripts" / "safe_flock.sh"),
                        "/tmp/tradeai_atm.lock",
                        sys.executable,
                        str(_proj / "scripts" / "atm_auto_approver.py"),
                    ],
                    stdout=_log_fh,
                    stderr=_log_fh,
                    cwd=str(_proj),
                )
                log.info(f"  ⚡ Triggered immediate ATM evaluation for {symbol} (ENTRY_ZONE_VALID)")
                actions.append('ATM_TRIGGERED')
            except Exception as _atm_err:
                log.warning(f"  ATM immediate trigger failed: {_atm_err}")

        # Update local proposal dict for downstream computations
        proposal['current_price'] = price
        proposal['price_drift_pct'] = drift_pct
        proposal['entry_zone_status'] = zone
        proposal['lifecycle_status'] = new_lifecycle

    # 2b. Close history for support/resistance / backtest / broker curator (same path as watchlist)
    if not dry_run:
        try:
            from price_db_sync import ensure_price_history
            _ph = ensure_price_history([symbol])
            if (_ph.get("quotes_synced") or 0) > 0 or (_ph.get("yfinance") or {}).get("filled"):
                actions.append("price_history")
        except Exception as e:
            log.debug(f"[price_history] #{pid} {symbol}: {e}")

    # 3. Technical snapshot (non-blocking)
    if not dry_run:
        try:
            if refresh_technical(conn, proposal):
                actions.append('technical')
        except Exception:
            pass

    # 4. Execution readiness (non-blocking)
    if not dry_run:
        try:
            if refresh_execution(conn, proposal):
                actions.append('execution')
        except Exception:
            pass

    # 5. Strategy fit (non-blocking)
    if not dry_run:
        try:
            if refresh_strategy_fit(conn, proposal):
                actions.append('strategy_fit')
        except Exception:
            pass

    # 6. Agent review queue
    if not dry_run:
        try:
            if queue_agent_reviews(conn, proposal):
                actions.append('agents_queued')
        except Exception:
            pass

    # 6b. Stale LLM review detection — re-queue if data changed materially
    if not dry_run:
        try:
            llm_stage = proposal.get('llm_review_stage')
            if llm_stage == 'catalyst':  # all 4 chunks done — check if stale
                _stale = False
                _reason = None
                # Check if technical snapshot is newer than last LLM review
                _tech_at = proposal.get('last_technical_snapshot_at')
                _llm_at = proposal.get('packet_last_enriched_at') or proposal.get('updated_at')
                if _tech_at and _llm_at and _tech_at > _llm_at:
                    _stale = True
                    _reason = 'technical_refreshed'
                # Check if entry zone changed
                _prev_zone = proposal.get('prev_entry_zone_status') or proposal.get('entry_zone_status')
                _curr_zone = proposal.get('entry_zone_status')
                if _prev_zone and _curr_zone and _prev_zone != _curr_zone:
                    _stale = True
                    _reason = f'zone_changed:{_prev_zone}->{_curr_zone}'
                # Check if price drifted >10% since last review
                _drift = abs(float(proposal.get('price_drift_pct') or 0))
                if _drift > 10:
                    _stale = True
                    _reason = f'price_drift_{_drift:.1f}pct'
                # Check if catalyst changed
                _cat_changed = proposal.get('catalyst_verified') and not proposal.get('llm_review_chunks', {}).get('catalyst')
                if _cat_changed:
                    _stale = True
                    _reason = 'catalyst_new'

                if _stale:
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE paper_trade_proposals
                        SET llm_review_stage = NULL, llm_review_chunks = NULL
                        WHERE id = %s
                    """, [pid])
                    conn.commit()
                    actions.append(f'llm_stale_reset:{_reason}')
                    log.info(f"  #{pid} {symbol}: LLM review reset — {_reason}")
        except Exception:
            pass

    # 7. LLM review queue
    if not dry_run and not no_llm:
        try:
            if queue_llm_review(conn, proposal):
                actions.append('llm_queued')
        except Exception:
            pass

    # 8. Compute missing data + action state + packet state
    missing = compute_missing_data(proposal)
    completion = compute_completion_pct(missing)
    action_state, action_label, top_blocker, next_actions = compute_action_state(proposal, missing)
    packet_state = compute_packet_state(action_state, completion, missing)

    if not dry_run:
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE paper_trade_proposals
                SET missing_data_by_section = %s,
                    packet_completion_pct = %s,
                    action_state = %s,
                    action_label = %s,
                    top_blocker = %s,
                    next_actions = %s,
                    packet_state = %s,
                    packet_last_enriched_at = NOW(),
                    enrichment_attempt_count = COALESCE(enrichment_attempt_count, 0) + 1,
                    last_enrichment_error = NULL
                WHERE id = %s
            """, [
                json.dumps(missing), completion,
                action_state, action_label, top_blocker,
                json.dumps(next_actions), packet_state, pid,
            ])
            conn.commit()
        except Exception as e:
            log.warning(f"[packet] #{pid}: {e}")

    actions.append(f'packet={packet_state} {completion}%')

    # Write audit event
    if not dry_run:
        write_event(conn, pid, symbol, 'enrichment_pass', status=packet_state,
                     message=f'{len(actions)} steps', payload={'actions': actions, 'completion': completion})

    return {'id': pid, 'symbol': symbol, 'actions': actions, 'packet_state': packet_state,
            'completion': completion, 'action_state': action_state}


# ── Main ──────────────────────────────────────────────────────────────

def run(dry_run=False, limit=BATCH_SIZE, no_llm=False, queue_llm_only=False,
        proposal_id=None, symbol=None):
    conn = get_db()
    try:
        proposals = fetch_pending_proposals(conn, limit=limit, proposal_id=proposal_id, symbol=symbol)
        log.info(f"Processing {len(proposals)} pending proposals")

        results = []
        seen_prices = {}  # symbol -> (price, source) cache

        for p in proposals:
            sym = p['symbol']
            try:
                result = enrich_one(conn, p, dry_run=dry_run, no_llm=no_llm, queue_llm_only=queue_llm_only)
                results.append(result)
                log.info(f"[enrich] #{p['id']} {sym}: {', '.join(result.get('actions', []))}")
            except Exception as e:
                log.warning(f"[enrich] #{p['id']} {sym}: ERROR {e}")
                if not dry_run:
                    try:
                        cur = conn.cursor()
                        cur.execute("""
                            UPDATE paper_trade_proposals
                            SET last_enrichment_error = %s,
                                enrichment_attempt_count = COALESCE(enrichment_attempt_count, 0) + 1
                            WHERE id = %s
                        """, [str(e)[:500], p['id']])
                        conn.commit()
                    except Exception:
                        pass
                results.append({'id': p['id'], 'symbol': sym, 'actions': [f'ERROR: {e}']})

            time.sleep(0.3)

        return results
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Proposal enrichment loop")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=BATCH_SIZE)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--queue-llm-only", action="store_true")
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--symbol", type=str)
    args = parser.parse_args()

    with PipelineRun('proposal_enrichment_loop', triggered_by='cli') as pipe:
        results = run(
            dry_run=args.dry_run, limit=args.limit,
            no_llm=args.no_llm, queue_llm_only=args.queue_llm_only,
            proposal_id=args.proposal_id, symbol=args.symbol,
        )
        pipe.rows(len(results))

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{prefix}Proposal Enrichment Loop")
    print(f"{prefix}{'=' * 50}")
    print(f"  Processed: {len(results)}")

    states = {}
    for r in results:
        s = r.get('packet_state', 'N/A')
        states[s] = states.get(s, 0) + 1
    for s, c in sorted(states.items()):
        print(f"  {s}: {c}")

    expired = sum(1 for r in results if r.get('expired'))
    if expired:
        print(f"  Auto-expired: {expired}")


if __name__ == "__main__":
    main()
