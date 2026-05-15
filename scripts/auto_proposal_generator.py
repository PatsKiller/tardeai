#!/usr/bin/env python3
"""auto_proposal_generator.py — Stage 18f: Auto-create PENDING paper proposals from planned strategy signals.

Creates PENDING paper proposals from current-day planned strategy signals.
Does NOT approve trades or submit orders. Populates the review queue.

Usage:
    .venv/bin/python scripts/auto_proposal_generator.py --run-label 1000 --dry-run
    .venv/bin/python scripts/auto_proposal_generator.py --run-label 1000 --apply
    .venv/bin/python scripts/auto_proposal_generator.py --today --apply --limit 10
    .venv/bin/python scripts/auto_proposal_generator.py --symbol EVC --dry-run
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("auto_proposal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

DEFAULT_MAX_DOLLAR_SIZE = 2000
DEFAULT_MAX_DOLLAR_RISK = 150
DEFAULT_RISK_PER_TRADE = 150
STRATEGY_PRIORITY = ["momentum_scalp", "gap_and_go", "swing_breakout", "earnings_catalyst", "sector_rotation",
                     "speculative_growth", "recovery_watch", "fib_retracement_bounce", "earnings_post_momentum", "swing_trade"]

BASE = str(PROJECT_ROOT)
PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")


def _enrich_proposal_async(proposal_id: int, symbol: str):
    """Kick off enrichment pipeline for a new proposal in a background thread.

    Sequence: queue agent reviews → warm Ollama → LLM analysis → quality review.
    Non-blocking — runs in a daemon thread so it doesn't delay proposal creation.
    """
    import threading

    def _run():
        import subprocess, time

        log.info(f"Starting async enrichment for proposal #{proposal_id} ({symbol})")

        # Step 1: Queue agent reviews
        try:
            r = subprocess.run(
                [PYTHON, f'{BASE}/scripts/queue_proposal_agent_reviews.py',
                 '--proposal-id', str(proposal_id), '--apply'],
                capture_output=True, text=True, timeout=60, cwd=BASE
            )
            log.info(f"Agent reviews queued for #{proposal_id}: "
                     f"{r.stdout.strip()[-100:] if r.stdout else 'done'}")
        except Exception as e:
            log.warning(f"Agent review queue failed for #{proposal_id}: {e}")

        # Brief pause to let agent processor pick up jobs
        time.sleep(10)

        # Step 2: Warm up Ollama
        try:
            subprocess.run(
                ['ollama', 'run', 'qwen3:14b', 'ready'],
                capture_output=True, text=True, timeout=30, cwd=BASE
            )
        except Exception:
            pass  # non-fatal

        # Step 3: LLM analysis
        try:
            r = subprocess.run(
                [PYTHON, f'{BASE}/scripts/proposal_intelligence_analyzer.py',
                 '--proposal-id', str(proposal_id), '--apply'],
                capture_output=True, text=True, timeout=180, cwd=BASE
            )
            log.info(f"LLM analysis for #{proposal_id}: "
                     f"{'OK' if r.returncode == 0 else 'FAILED'}")
            if r.returncode != 0 and r.stderr:
                log.warning(f"Analyzer stderr: {r.stderr[-200:]}")
        except subprocess.TimeoutExpired:
            log.warning(f"LLM analysis timed out for #{proposal_id}")
        except Exception as e:
            log.warning(f"LLM analysis failed for #{proposal_id}: {e}")

        # Step 4: Quality review
        try:
            subprocess.run(
                [PYTHON, f'{BASE}/scripts/proposal_quality_reviewer.py',
                 '--proposal-id', str(proposal_id), '--apply'],
                capture_output=True, text=True, timeout=60, cwd=BASE
            )
            log.info(f"Quality review complete for #{proposal_id}")
        except Exception as e:
            log.warning(f"Quality review failed for #{proposal_id}: {e}")

        log.info(f"Enrichment complete for proposal #{proposal_id} ({symbol})")

    t = threading.Thread(target=_run, daemon=True, name=f'enrich-{proposal_id}')
    t.start()
    return t


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def _get_available_cols(conn, table: str) -> set:
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table])
    return {r[0] for r in cur.fetchall()}


def _load_strategy_config(strategy_id: str) -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / f"{strategy_id}.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _load_shared_risk_rules() -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / "shared_risk_rules.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _validate_against_strategy_criteria(strategy_id: str, signal: dict) -> tuple:
    """Hard-validate a signal against its strategy YAML criteria.
    Returns (passes: bool, fail_reason: str, fallback_strategy: str|None).
    """
    cfg = _load_strategy_config(strategy_id)
    if not cfg:
        return True, '', None

    filters = cfg.get('screen_filters', {})
    rvol = float(signal.get('rvol') or 0)
    price = float(signal.get('price') or signal.get('entry_high') or 0)
    float_m = float(signal.get('float_m') or 0)
    gap_pct = abs(float(signal.get('gap_pct') or 0))

    min_rvol = float(filters.get('min_rvol', 0))
    min_price = float(filters.get('min_price', 0))
    max_price = float(filters.get('max_price', 99999))
    max_float = float(filters.get('max_float_m', 99999))
    min_gap = float(filters.get('min_gap_pct', 0))

    reasons = []
    if min_rvol > 0 and rvol < min_rvol:
        reasons.append(f"RVOL {rvol:.1f}x < {min_rvol}x")
    if price < min_price or price > max_price:
        reasons.append(f"Price ${price:.2f} outside ${min_price}-${max_price}")
    if max_float < 99999 and float_m > 0 and float_m > max_float:
        reasons.append(f"Float {float_m:.0f}M > {max_float}M")
    if min_gap > 0 and gap_pct < min_gap:
        reasons.append(f"Gap {gap_pct:.1f}% < {min_gap}%")

    if reasons:
        # Suggest fallback based on strategy type
        fallback = None
        if strategy_id == 'momentum_scalp':
            fallback = 'gap_and_go'
        elif strategy_id == 'gap_and_go':
            fallback = 'swing_breakout'
        return False, ' | '.join(reasons), fallback

    return True, '', None


def get_eligible_signals(conn, run_label=None, symbol=None, min_score=40) -> list:
    """Get current-day planned strategy signals eligible for auto-proposal."""
    cur = conn.cursor()
    sql = """
        SELECT id, symbol, strategy_id, setup_description, signal_grade, signal_score,
               price, rvol, float_m, gap_pct,
               catalyst, catalyst_verified, intel_readiness,
               entry_high, entry_low, stop_loss, target_1, target_2,
               shares, dollar_risk, risk_reward,
               sector, source_table, scan_run_label, discovery_source,
               fired_at
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND entry_high IS NOT NULL AND stop_loss IS NOT NULL
        AND target_1 IS NOT NULL AND shares IS NOT NULL
        AND (signal_grade IN ('A','A+') OR signal_score >= %s)
        AND status IN ('active','ACTIVE')
    """
    params = [min_score]
    if run_label:
        sql += " AND (scan_run_label = %s OR scan_run_label IS NULL)"
        params.append(run_label)
    if symbol:
        sql += " AND symbol = %s"
        params.append(symbol)
    sql += " ORDER BY signal_score DESC NULLS LAST"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def check_duplicate(conn, signal_id: int, symbol: str, strategy_id: str) -> dict | None:
    """Check for existing active proposal. Returns proposal dict if duplicate."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status FROM paper_trade_proposals
        WHERE (
            source_signal_id = %s
            OR (
                symbol = %s AND strategy_id = %s
                AND created_at::date = CURRENT_DATE
                AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED')
            )
        )
        AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED')
        LIMIT 1
    """, [signal_id, symbol, strategy_id])
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]} if row else None


def check_open_paper_trade(conn, symbol: str, strategy_id: str) -> dict | None:
    """Check for existing open paper trade."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status FROM paper_trades
        WHERE symbol = %s
        AND COALESCE(strategy_id, '') = COALESCE(%s, '')
        AND status IN ('open','pending','submitted')
        LIMIT 1
    """, [symbol, strategy_id])
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]} if row else None


def check_recently_closed(conn, symbol: str, strategy_id: str, cooldown_hours: int = 48) -> dict | None:
    """Block if any paper trade with this symbol closed within cooldown window, regardless of strategy."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, strategy_id, pnl, outcome_verdict,
               closed_at, exit_reason
        FROM paper_trades
        WHERE symbol = %s
          AND lifecycle_state = 'closed'
          AND closed_at > NOW() - make_interval(hours => %s)
        ORDER BY closed_at DESC LIMIT 1
    """, [symbol, cooldown_hours])
    row = cur.fetchone()
    if not row:
        return None
    prior_id, prior_strat, pnl, verdict, closed_at, exit_reason = row
    pnl_f = float(pnl) if pnl is not None else 0
    from datetime import datetime, timezone
    hours_since = (datetime.now(timezone.utc) - closed_at.astimezone(timezone.utc)).total_seconds() / 3600
    return {
        "reason": "SKIPPED_RECENTLY_CLOSED",
        "detail": (f"trade #{prior_id} ({symbol}/{prior_strat}) closed {closed_at} "
                   f"verdict={verdict} pnl=${pnl_f:.2f} via {exit_reason} — "
                   f"{hours_since:.1f}h ago, cooldown {cooldown_hours}h"),
        "prior_trade_id": prior_id,
        "prior_strategy": prior_strat,
        "prior_pnl": pnl_f,
        "prior_verdict": verdict,
        "hours_since_close": round(hours_since, 1),
    }


def rank_proposals_for_symbol(conn, symbol: str, window_hours: int = 24):
    """Rank all proposals for a symbol created within the window.

    Rules (from design doc, operator decisions Q1/Q2):
    - Rank within screener-matched set only (don't invent new strategies)
    - Sort by signal_score DESC
    - Top score gets is_top_pick=True, rank=1
    - Anything within 5% of top AND confidence_score > 65 is tied (also top_pick)
    - Everything else gets is_top_pick=False
    - All get rank_among_peers and peer_group_id for audit

    Returns number of proposals ranked.
    """
    cur = conn.cursor()
    # Get all proposals for this symbol in the time window
    cur.execute("""
        SELECT id, strategy_id, signal_score, confidence_score
        FROM paper_trade_proposals
        WHERE symbol = %s
          AND created_at > NOW() - (%s || ' hours')::interval
          AND status NOT IN ('REJECTED', 'RISK_BLOCKED')
        ORDER BY COALESCE(signal_score, 0) DESC, COALESCE(confidence_score, 0) DESC
    """, [symbol, str(window_hours)])
    rows = cur.fetchall()
    if len(rows) <= 1:
        # Single proposal or none — mark it as top pick if it exists
        if rows:
            cur.execute("""UPDATE paper_trade_proposals
                SET is_top_pick=TRUE, rank_among_peers=1, peer_group_id=%s
                WHERE id=%s""", [f"{symbol}_{rows[0][0]}", rows[0][0]])
            conn.commit()
        return len(rows)

    peer_group_id = f"{symbol}_{rows[0][0]}"
    top_score = float(rows[0][2] or 0)
    threshold_5pct = top_score * 0.95  # within 5% of top

    ranked = 0
    for rank_idx, (pid, strat, score, conf) in enumerate(rows):
        score_f = float(score or 0)
        conf_f = float(conf or 0)
        is_top = False
        if rank_idx == 0:
            is_top = True
        elif score_f >= threshold_5pct and conf_f >= 65:
            is_top = True  # tied — within 5% and high confidence
        cur.execute("""UPDATE paper_trade_proposals
            SET is_top_pick=%s, rank_among_peers=%s, peer_group_id=%s
            WHERE id=%s""", [is_top, rank_idx + 1, peer_group_id, pid])
        ranked += 1

    conn.commit()
    log.info(f"[ranker] {symbol}: ranked {ranked} proposals, "
             f"top_score={top_score}, threshold={threshold_5pct:.1f}")
    return ranked


def check_rejection_cooldown(conn, symbol: str, force: bool = False) -> dict | None:
    """Check if symbol was recently rejected (24h cooldown). Returns skip reason or None."""
    if force:
        return None
    cur = conn.cursor()
    # Recent rejection or risk-gate rejection in last 24h
    cur.execute("""
        SELECT id, status, rejection_reason, risk_gate_result, rejected_at
        FROM paper_trade_proposals
        WHERE symbol = %s
        AND (
            (status = 'REJECTED' AND rejected_at > NOW() - INTERVAL '24 hours')
            OR (risk_gate_result ILIKE '%%BLOCK%%' AND created_at > NOW() - INTERVAL '24 hours')
        )
        ORDER BY created_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row:
        return {
            "reason": "SKIPPED_RECENTLY_REJECTED",
            "detail": f"proposal #{row[0]} {row[1]} — {row[2] or row[3] or 'unknown reason'}",
            "cooldown_until": str(row[4] + timedelta(hours=24)) if row[4] else None,
        }
    return None


def check_scan_decision(conn, symbol: str) -> dict | None:
    """Check if latest scan decision is not GO. Returns skip reason or None."""
    cur = conn.cursor()
    cur.execute("""
        SELECT decision, score, grade, critic_verdict
        FROM trade_ai_scans
        WHERE symbol = %s AND scanned_at::date = CURRENT_DATE
        ORDER BY scanned_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if not row:
        return None  # no scan today, let other checks handle

    decision, score, grade, critic = row

    if decision in ('WAIT', 'NO_GO', 'AVOID'):
        return {"reason": "SKIPPED_NOT_GO", "detail": f"scan decision={decision}"}

    if grade not in ('A', 'A+') and (score is None or score < 40):
        return {"reason": "SKIPPED_LOW_SCORE", "detail": f"grade={grade} score={score}"}

    if critic == 'DOWNGRADE':
        return {"reason": "SKIPPED_CRITIC_DOWNGRADE", "detail": f"critic={critic}"}

    if critic == 'BLOCK':
        return {"reason": "SKIPPED_CRITIC_BLOCK", "detail": f"critic={critic}"}

    return None


def normalize_size(signal: dict, strategy_cfg: dict, shared_rules: dict) -> dict:
    """Normalize proposal sizing. Returns sizing dict."""
    entry = float(signal.get("entry_high") or signal.get("price") or 0)
    stop = float(signal.get("stop_loss") or 0)
    original_shares = int(signal.get("shares") or 0)

    if entry <= 0 or stop <= 0 or original_shares <= 0:
        return {"valid": False, "reason": "MISSING_PLAN_DATA"}

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"valid": False, "reason": "ZERO_RISK_PER_SHARE"}

    # Get caps from strategy config and shared rules
    live_rules = strategy_cfg.get("live_trade_rules", {})
    max_dollar_size = float(live_rules.get("max_position_size", DEFAULT_MAX_DOLLAR_SIZE))
    max_dollar_risk = float(live_rules.get("max_dollar_risk", DEFAULT_MAX_DOLLAR_RISK))
    risk_per_trade = float(shared_rules.get("risk_limits", {}).get("default_risk_per_trade", DEFAULT_RISK_PER_TRADE))

    # Use the more conservative risk cap
    max_dollar_risk = min(max_dollar_risk, risk_per_trade)

    original_dollar_size = round(original_shares * entry, 2)
    original_dollar_risk = round(original_shares * risk_per_share, 2)

    # Calculate max shares by each constraint
    max_shares_by_size = int(max_dollar_size / entry) if entry > 0 else 0
    max_shares_by_risk = int(max_dollar_risk / risk_per_share) if risk_per_share > 0 else 0
    adjusted_shares = min(original_shares, max_shares_by_size, max_shares_by_risk)
    adjusted_shares = max(adjusted_shares, 0)

    if adjusted_shares < 1:
        return {
            "valid": False,
            "reason": "SIZE_TOO_SMALL",
            "original_shares": original_shares,
            "max_shares_by_size": max_shares_by_size,
            "max_shares_by_risk": max_shares_by_risk,
        }

    sizing_adjusted = adjusted_shares != original_shares
    sizing_reason = None
    if sizing_adjusted:
        reasons = []
        if adjusted_shares < original_shares and max_shares_by_size < original_shares:
            reasons.append(f"dollar_size {original_dollar_size:.0f}>{max_dollar_size:.0f}")
        if adjusted_shares < original_shares and max_shares_by_risk < original_shares:
            reasons.append(f"dollar_risk {original_dollar_risk:.0f}>{max_dollar_risk:.0f}")
        sizing_reason = "; ".join(reasons) if reasons else "reduced_to_fit_limits"

    adjusted_dollar_size = round(adjusted_shares * entry, 2)
    adjusted_dollar_risk = round(adjusted_shares * risk_per_share, 2)
    rr = round((float(signal.get("target_1") or 0) - entry) / risk_per_share, 2) if risk_per_share > 0 else 0

    return {
        "valid": True,
        "original_shares": original_shares,
        "adjusted_shares": adjusted_shares,
        "original_dollar_size": original_dollar_size,
        "adjusted_dollar_size": adjusted_dollar_size,
        "original_dollar_risk": original_dollar_risk,
        "adjusted_dollar_risk": adjusted_dollar_risk,
        "sizing_adjusted": sizing_adjusted,
        "sizing_reason": sizing_reason,
        "stop_pct": round(risk_per_share / entry, 4) if entry > 0 else 0,
        "rr": rr,
    }


def check_risk_gate(conn, symbol: str, strategy_id: str, plan: dict) -> dict:
    """Run risk gate precheck. Returns {approved, result, codes}."""
    try:
        from risk_gate import RiskGate
        gate = RiskGate(conn)
        decision = gate.check(
            symbol=symbol,
            strategy_id=strategy_id,
            trade_plan=plan,
            account="ALPACA_PAPER",
            mode="paper",
            action_context="paper_proposal",
        )
        return {
            "approved": decision.approved,
            "result": decision.result,
            "codes": decision.reason_codes,
        }
    except Exception as e:
        log.warning(f"  {symbol}: risk gate error — {e}")
        return {"approved": False, "result": "RISK_GATE_ERROR", "codes": [str(e)]}


def check_quality(signal: dict, sizing: dict) -> tuple:
    """Quality filter. Returns (pass, reason_codes)."""
    reasons = []
    score = int(signal.get("signal_score") or 0)
    rr = sizing.get("rr", 0)
    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)

    if score < 40:
        reasons.append("LOW_SCORE")
    if rr < 1.2:
        reasons.append("BAD_RR")
    if entry <= 0 or stop <= 0 or target <= 0:
        reasons.append("NO_PLAN")
    if stop >= entry:
        reasons.append("PRICE_ORDER_INVALID")
    if target <= entry:
        reasons.append("TARGET_BELOW_ENTRY")

    # Source cap: reject social-only or youtube-only
    source = (signal.get("discovery_source") or "").lower()
    if source in ("social", "stocktwits", "reddit") and not signal.get("catalyst_verified"):
        reasons.append("SOURCE_CAP_SOCIAL_ONLY")

    return len(reasons) == 0, reasons


def create_auto_proposal(conn, signal: dict, sizing: dict, risk_gate: dict,
                         auto_run_id: int, available_cols: set,
                         auto_context: dict = None) -> int | None:
    """Insert a PENDING paper proposal. Returns proposal_id."""
    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)
    target2 = float(signal.get("target_2") or 0) if signal.get("target_2") else None
    shares = sizing["adjusted_shares"]
    # Session 24A: Strategy-aware expiry
    _strat = signal.get("strategy_id", "momentum_scalp")
    try:
        from proposal_lifecycle import (get_expiry_datetime, get_max_expiry_datetime,
                                        get_timeframe_class, is_overnight)
        _now = datetime.now(timezone.utc)
        expires = get_expiry_datetime(_strat, _now)
        _max_expires = get_max_expiry_datetime(_strat, _now)
        _base_expires = expires
        _timeframe_class = get_timeframe_class(_strat)
        _overnight = is_overnight(_strat)
    except Exception:
        expires = datetime.now(timezone.utc) + timedelta(hours=4)
        _max_expires = expires
        _base_expires = expires
        _timeframe_class = "intraday"
        _overnight = False

    data = {
        "symbol": signal["symbol"],
        "strategy_id": signal.get("strategy_id", "momentum_scalp"),
        "setup_type": signal.get("setup_description"),
        "signal_score": signal.get("signal_score"),
        "signal_grade": signal.get("signal_grade"),
        "signal_decision": "GO",
        "source_signal_id": signal["id"],
        "rvol": signal.get("rvol"),
        "float_m": signal.get("float_m"),
        "gap_pct": signal.get("gap_pct"),
        "catalyst": (signal.get("catalyst") or "")[:200],
        "catalyst_verified": signal.get("catalyst_verified", False),
        "intel_readiness": signal.get("intel_readiness"),
        "proposed_account": "ALPACA_PAPER",
        "proposed_entry": entry,
        "proposed_stop": stop,
        "proposed_target1": target,
        "proposed_target2": target2,
        "proposed_shares": shares,
        "proposed_dollar_size": sizing["adjusted_dollar_size"],
        "proposed_dollar_risk": sizing["adjusted_dollar_risk"],
        "proposed_stop_pct": sizing.get("stop_pct", 0),
        "proposed_rr": sizing.get("rr", 0),
        "risk_gate_result": risk_gate.get("result", "UNKNOWN"),
        "risk_gate_codes": json.dumps(risk_gate.get("codes", [])),
        "proposed_by": "auto_proposal_generator",
        "status": "PENDING",
        "expires_at": expires,
        "base_expires_at": _base_expires,
        "max_expires_at": _max_expires,
        "lifecycle_status": "ACTIVE",
        "proposal_timeframe_class": _timeframe_class,
        "overnight_monitoring_enabled": _overnight,
        "auto_created": True,
        "auto_proposal_run_id": auto_run_id,
        "sizing_adjusted": sizing.get("sizing_adjusted", False),
        "original_shares": sizing.get("original_shares"),
        "adjusted_shares": sizing.get("adjusted_shares"),
        "sizing_reason": sizing.get("sizing_reason"),
        "sector": signal.get("sector"),
        "discovery_source": signal.get("discovery_source"),
        "setup_description": signal.get("setup_description"),
        "source_run_label": signal.get("scan_run_label"),
        "auto_execution_label": auto_context.get("execution_label", "manual") if auto_context else "manual",
    }

    # Filter to existing columns
    insert_data = {k: v for k, v in data.items() if k in available_cols and v is not None}
    cols_str = ", ".join(insert_data.keys())
    placeholders = ", ".join(["%s"] * len(insert_data))

    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO paper_trade_proposals ({cols_str}) VALUES ({placeholders}) RETURNING id",
        list(insert_data.values())
    )
    return cur.fetchone()[0]


def record_decision(conn, run_label: str, signal: dict, decision: str,
                     reason_codes: list, proposal_id: int | None,
                     sizing: dict | None, risk_gate: dict | None):
    """Record auto-proposal decision for diagnostics."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO auto_proposal_decisions
            (run_label, source_signal_id, symbol, strategy_id, decision, reason_codes,
             proposal_id, original_shares, adjusted_shares,
             original_dollar_size, adjusted_dollar_size,
             original_dollar_risk, adjusted_dollar_risk,
             risk_gate_result, risk_gate_codes, quality_pass, source_cap_pass)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        run_label, signal.get("id"), signal["symbol"], signal.get("strategy_id"),
        decision, json.dumps(reason_codes),
        proposal_id,
        sizing.get("original_shares") if sizing else None,
        sizing.get("adjusted_shares") if sizing else None,
        sizing.get("original_dollar_size") if sizing else None,
        sizing.get("adjusted_dollar_size") if sizing else None,
        sizing.get("original_dollar_risk") if sizing else None,
        sizing.get("adjusted_dollar_risk") if sizing else None,
        risk_gate.get("result") if risk_gate else None,
        json.dumps(risk_gate.get("codes", [])) if risk_gate else None,
        "SOURCE_CAP" not in " ".join(reason_codes) if reason_codes else True,
        "SOURCE_CAP" not in " ".join(reason_codes) if reason_codes else True,
    ])


def run_auto_proposals(conn, run_label: str = None, symbol: str = None,
                       min_score: int = 40, limit: int = 20,
                       dry_run: bool = True,
                       execution_label: str = "manual",
                       force: bool = False) -> dict:
    """Main auto-proposal generation. Returns audit summary."""
    shared_rules = _load_shared_risk_rules()
    proposal_cols = _get_available_cols(conn, "paper_trade_proposals")
    cur = conn.cursor()

    # Record run start
    auto_run_id = None
    if not dry_run:
        cur.execute("""
            INSERT INTO auto_proposal_runs (run_label, run_date, status, started_at,
                                            execution_label, source_run_label)
            VALUES (%s, CURRENT_DATE, 'RUNNING', NOW(), %s, %s) RETURNING id
        """, [run_label or "manual", execution_label, run_label])
        auto_run_id = cur.fetchone()[0]
        conn.commit()

    signals = get_eligible_signals(conn, run_label=run_label, symbol=symbol, min_score=min_score)
    log.info(f"Found {len(signals)} eligible signals for auto-proposal")

    # Deduplicate: keep best signal per symbol (highest score, best strategy priority)
    best_by_symbol = {}
    for sig in signals:
        sym = sig["symbol"]
        sid = sig.get("strategy_id", "")
        priority = STRATEGY_PRIORITY.index(sid) if sid in STRATEGY_PRIORITY else 99
        existing = best_by_symbol.get(sym)
        if not existing:
            best_by_symbol[sym] = (sig, priority)
        else:
            _, ex_priority = existing
            if priority < ex_priority or (priority == ex_priority and (sig.get("signal_score") or 0) > (existing[0].get("signal_score") or 0)):
                best_by_symbol[sym] = (sig, priority)

    deduped = [sig for sig, _ in best_by_symbol.values()]
    deduped.sort(key=lambda s: -(s.get("signal_score") or 0))
    if limit:
        deduped = deduped[:limit]

    stats = {
        "signals_checked": len(deduped),
        "proposals_created": 0,
        "proposals_skipped": 0,
        "duplicates_skipped": 0,
        "risk_rejected": 0,
        "quality_rejected": 0,
        "source_cap_rejected": 0,
        "sizing_adjusted": 0,
        "errors": 0,
        "details": [],
    }

    for sig in deduped:
        sym = sig["symbol"]
        sid = sig.get("strategy_id", "momentum_scalp")
        sig_id = sig["id"]

        try:
            # 1. Duplicate check
            dup = check_duplicate(conn, sig_id, sym, sid)
            if dup:
                stats["duplicates_skipped"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_DUPLICATE (proposal #{dup['id']} {dup['status']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_DUPLICATE", [reason], None, None, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_DUPLICATE", "reason": reason})
                continue

            # 2. Open trade check
            open_trade = check_open_paper_trade(conn, sym, sid)
            if open_trade:
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_OPEN_TRADE (trade #{open_trade['id']} {open_trade['status']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_OPEN_TRADE", [reason], None, None, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_OPEN_TRADE", "reason": reason})
                continue

            # 2a. Recently closed trade cooldown (48h, any strategy)
            closed_block = check_recently_closed(conn, sym, sid, cooldown_hours=48)
            if closed_block:
                stats["proposals_skipped"] += 1
                reason = f"{closed_block['reason']} ({closed_block['detail']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, closed_block["reason"], [closed_block["detail"]], None, None, None)
                stats["details"].append({"symbol": sym, "decision": closed_block["reason"], "reason": reason})
                continue

            # 2b. Rejection cooldown check (24h)
            cooldown = check_rejection_cooldown(conn, sym, force=force)
            if cooldown:
                stats["proposals_skipped"] += 1
                reason = f"{cooldown['reason']} ({cooldown['detail']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, cooldown["reason"], [cooldown["detail"]], None, None, None)
                stats["details"].append({"symbol": sym, "decision": cooldown["reason"], "reason": reason})
                continue

            # 2c. Scan decision gate
            scan_block = check_scan_decision(conn, sym)
            if scan_block:
                stats["proposals_skipped"] += 1
                reason = f"{scan_block['reason']} ({scan_block['detail']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, scan_block["reason"], [scan_block["detail"]], None, None, None)
                stats["details"].append({"symbol": sym, "decision": scan_block["reason"], "reason": reason})
                continue

            # 2d. Strategy criteria hard validation
            passes, fail_reason, fallback_sid = _validate_against_strategy_criteria(sid, sig)
            if not passes:
                if fallback_sid:
                    passes2, _, _ = _validate_against_strategy_criteria(fallback_sid, sig)
                    if passes2:
                        log.info(f"  {sym}: {sid} fails ({fail_reason}), reassigned to {fallback_sid}")
                        sid = fallback_sid
                        sig['strategy_id'] = fallback_sid
                    else:
                        stats["proposals_skipped"] += 1
                        reason = f"SKIPPED_STRATEGY_CRITERIA ({sid}: {fail_reason})"
                        log.info(f"  {sym}: {reason}")
                        if not dry_run:
                            record_decision(conn, run_label, sig, "SKIPPED_STRATEGY_CRITERIA", [fail_reason], None, None, None)
                        stats["details"].append({"symbol": sym, "decision": "SKIPPED_STRATEGY_CRITERIA", "reason": reason})
                        continue
                else:
                    stats["proposals_skipped"] += 1
                    reason = f"SKIPPED_STRATEGY_CRITERIA ({sid}: {fail_reason})"
                    log.info(f"  {sym}: {reason}")
                    if not dry_run:
                        record_decision(conn, run_label, sig, "SKIPPED_STRATEGY_CRITERIA", [fail_reason], None, None, None)
                    stats["details"].append({"symbol": sym, "decision": "SKIPPED_STRATEGY_CRITERIA", "reason": reason})
                    continue

            # 3. Normalize sizing
            strategy_cfg = _load_strategy_config(sid)
            sizing = normalize_size(sig, strategy_cfg, shared_rules)
            if not sizing.get("valid"):
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_SIZE ({sizing.get('reason')})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_SIZE", [sizing.get("reason", "")], None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_SIZE", "reason": reason})
                continue

            if sizing.get("sizing_adjusted"):
                stats["sizing_adjusted"] += 1
                log.info(f"  {sym}: sizing adjusted {sizing['original_shares']}→{sizing['adjusted_shares']} shares ({sizing.get('sizing_reason')})")

            # 4. Quality check
            q_pass, q_reasons = check_quality(sig, sizing)
            if not q_pass:
                source_cap = any("SOURCE_CAP" in r for r in q_reasons)
                if source_cap:
                    stats["source_cap_rejected"] += 1
                else:
                    stats["quality_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_QUALITY ({', '.join(q_reasons)})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_QUALITY", q_reasons, None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_QUALITY", "reason": reason})
                continue

            # 5. Risk gate precheck
            plan_for_gate = {
                "stop_loss": float(sig.get("stop_loss") or 0),
                "dollar_size": sizing["adjusted_dollar_size"],
                "dollar_risk": sizing["adjusted_dollar_risk"],
            }
            rg = check_risk_gate(conn, sym, sid, plan_for_gate)
            if not rg["approved"]:
                stats["risk_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_RISK_GATE ({rg['result']}: {', '.join(rg.get('codes', []))})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_RISK_GATE", rg.get("codes", []), None, sizing, rg)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_RISK_GATE", "reason": reason})
                continue

            # 6. Create proposal
            if dry_run:
                log.info(f"  {sym}: WOULD CREATE proposal — {sid} score={sig.get('signal_score')} "
                         f"entry=${float(sig.get('entry_high') or 0):.2f} stop=${float(sig.get('stop_loss') or 0):.2f} "
                         f"shares={sizing['adjusted_shares']} risk=${sizing['adjusted_dollar_risk']:.0f} rr={sizing['rr']:.1f}")
                stats["proposals_created"] += 1
                stats["details"].append({"symbol": sym, "decision": "WOULD_CREATE", "strategy_id": sid,
                                         "shares": sizing["adjusted_shares"], "dollar_risk": sizing["adjusted_dollar_risk"]})
            else:
                proposal_id = create_auto_proposal(conn, sig, sizing, rg, auto_run_id, proposal_cols,
                                                   auto_context={"execution_label": execution_label})
                conn.commit()
                record_decision(conn, run_label, sig, "CREATED", [], proposal_id, sizing, rg)
                conn.commit()
                stats["proposals_created"] += 1
                log.info(f"  {sym}: CREATED proposal #{proposal_id} — {sid} score={sig.get('signal_score')} "
                         f"shares={sizing['adjusted_shares']} risk=${sizing['adjusted_dollar_risk']:.0f}")
                stats["details"].append({"symbol": sym, "decision": "CREATED", "proposal_id": proposal_id,
                                         "strategy_id": sid, "shares": sizing["adjusted_shares"]})

                # Session 23: kick off enrichment pipeline in background
                _enrich_proposal_async(proposal_id, sym)

        except Exception as e:
            stats["errors"] += 1
            stats["proposals_skipped"] += 1
            log.error(f"  {sym}: ERROR — {e}")
            stats["details"].append({"symbol": sym, "decision": "ERROR", "error": str(e)})
            if not dry_run:
                try:
                    record_decision(conn, run_label, sig, "ERROR", [str(e)], None, None, None)
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Post-run: rank proposals per symbol (Phase 6)
    if not dry_run:
        created_symbols = set(d["symbol"] for d in stats["details"] if d.get("decision") == "CREATED")
        for sym in created_symbols:
            try:
                rank_proposals_for_symbol(conn, sym, window_hours=24)
            except Exception as e:
                log.warning(f"[ranker] Failed to rank {sym}: {e}")

    # Finalize run record
    if not dry_run and auto_run_id:
        reason_summary = {}
        for d in stats["details"]:
            dec = d.get("decision", "UNKNOWN")
            reason_summary[dec] = reason_summary.get(dec, 0) + 1
        cur.execute("""
            UPDATE auto_proposal_runs
            SET status = 'COMPLETED',
                signals_checked = %s, proposals_created = %s, proposals_skipped = %s,
                duplicates_skipped = %s, risk_rejected = %s, quality_rejected = %s,
                source_cap_rejected = %s, sizing_adjusted = %s,
                reason_summary = %s, finished_at = NOW()
            WHERE id = %s
        """, [
            stats["signals_checked"], stats["proposals_created"], stats["proposals_skipped"],
            stats["duplicates_skipped"], stats["risk_rejected"], stats["quality_rejected"],
            stats["source_cap_rejected"], stats["sizing_adjusted"],
            json.dumps(reason_summary), auto_run_id,
        ])
        conn.commit()

    log.info(f"\nAuto-proposal summary: checked={stats['signals_checked']} "
             f"created={stats['proposals_created']} skipped={stats['proposals_skipped']} "
             f"(dup={stats['duplicates_skipped']} risk={stats['risk_rejected']} "
             f"quality={stats['quality_rejected']} source_cap={stats['source_cap_rejected']} "
             f"sizing_adj={stats['sizing_adjusted']})")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Auto-generate PENDING paper proposals from strategy signals")
    parser.add_argument("--run-label", type=str, help="Filter by run label")
    parser.add_argument("--today", action="store_true", help="Process all today's signals")
    parser.add_argument("--symbol", type=str, help="Process single symbol")
    parser.add_argument("--apply", action="store_true", help="Actually create proposals (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--limit", type=int, default=20, help="Max proposals to create")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum signal score")
    parser.add_argument("--force", action="store_true", help="Override rejection cooldown")
    args = parser.parse_args()

    if not args.run_label and not args.today and not args.symbol:
        print("Usage: --run-label 1000 or --today or --symbol MNKD")
        print("       Add --apply to actually create proposals")
        sys.exit(1)

    dry_run = not args.apply
    conn = get_conn()
    try:
        result = run_auto_proposals(
            conn,
            run_label=args.run_label,
            symbol=args.symbol,
            min_score=args.min_score,
            limit=args.limit,
            dry_run=dry_run,
            force=args.force,
        )
        print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2, default=str))
        if result.get("details"):
            print("\nDetails:")
            for d in result["details"]:
                print(f"  {d.get('symbol','?')}: {d.get('decision','?')} {d.get('reason','')}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
