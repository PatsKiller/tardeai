#!/usr/bin/env python3
"""approval_revalidator.py — Runs at approval time to validate proposal against
strategy YAML criteria, live market data, and R:R requirements.

Called from api_v2.py when John approves a trade. Returns either:
  - ELIGIBLE: proceed to execution
  - ADJUSTED: trade plan recalculated with current market data (needs display)
  - REJECTED: fails hard criteria, do not execute

This is NOT the execution-time revalidator (paper_execution_revalidator.py).
This runs BEFORE the proposal enters the execution pipeline.
"""
import json, logging, os, sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("approval_revalidator")

def _f(v):
    if v is None: return None
    try: return float(v)
    except: return None


def get_live_price(symbol):
    """Get live price from Alpaca."""
    try:
        from market_quote_provider import fetch_alpaca_quote
        q = fetch_alpaca_quote(symbol)
        if q and q.get('price') and q['price'] > 0:
            return float(q['price'])
    except Exception as e:
        log.warning(f"Live price fetch failed for {symbol}: {e}")
    return None


def load_strategy_criteria(strategy_id):
    """Load strategy YAML config."""
    try:
        from strategy_config_loader import load_strategy_config
        return load_strategy_config(strategy_id)
    except Exception as e:
        log.warning(f"Could not load strategy config for {strategy_id}: {e}")
        return {}


def get_proposal(conn, proposal_id):
    """Load proposal from DB."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1,
               proposed_target2, proposed_shares, proposed_dollar_size, proposed_dollar_risk,
               rvol, float_m, gap_pct, catalyst, catalyst_verified, catalyst_confidence,
               signal_score, signal_grade, data_quality_score, intel_readiness,
               vix_at_proposal, market_regime, proposed_account, sector,
               created_at, status
        FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def get_trade_history(symbol, strategy_id):
    """Get past trade outcomes from RAG."""
    try:
        from rag_retrieval import get_rag_context
        results = get_rag_context(symbol=symbol, strategy_focus=strategy_id, limit=5)
        return [r for r in results if r.get('source_type') == 'trade_outcome']
    except Exception:
        return []


def validate_at_approval(conn, proposal_id):
    """Full validation at approval time. Returns validation result dict."""
    proposal = get_proposal(conn, proposal_id)
    if not proposal:
        return {"status": "error", "reason": "Proposal not found"}

    symbol = proposal['symbol']
    strategy_id = proposal.get('strategy_id', 'unknown')
    config = load_strategy_criteria(strategy_id)

    # Get live price
    live_price = get_live_price(symbol)

    # Original plan
    proposed_entry = _f(proposal.get('proposed_entry'))
    proposed_stop = _f(proposal.get('proposed_stop'))
    proposed_target = _f(proposal.get('proposed_target1'))
    proposed_shares = int(proposal.get('proposed_shares') or 0)

    blockers = []
    warnings = []
    adjustments = []

    # ── 1. LIVE PRICE VS STOP CHECK ──
    if live_price and proposed_stop:
        if live_price <= proposed_stop:
            blockers.append(f"STOP_BREACHED: Live price ${live_price:.2f} <= stop ${proposed_stop:.2f}. Trade would immediately stop out.")

    # ── 2. PRICE DRIFT CHECK ──
    drift_pct = None
    if live_price and proposed_entry and proposed_entry > 0:
        drift_pct = (live_price - proposed_entry) / proposed_entry * 100
        if abs(drift_pct) > 10:
            blockers.append(f"EXCESSIVE_DRIFT: Price moved {drift_pct:+.1f}% from proposed entry ${proposed_entry:.2f} to ${live_price:.2f}")
        elif abs(drift_pct) > 5:
            warnings.append(f"SIGNIFICANT_DRIFT: Price moved {drift_pct:+.1f}% — trade plan should be recalculated")

    # ── 3. R:R RATIO CHECK (with live price) ──
    effective_entry = live_price if live_price else proposed_entry
    if effective_entry and proposed_stop and proposed_target:
        risk = abs(effective_entry - proposed_stop)
        reward = abs(proposed_target - effective_entry)
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < 1.5:
            blockers.append(f"INSUFFICIENT_RR: R:R = {rr_ratio:.2f} (minimum 1.5:1). Risk ${risk:.2f} vs reward ${reward:.2f}")
        elif rr_ratio < 2.0:
            warnings.append(f"MARGINAL_RR: R:R = {rr_ratio:.2f} (preferred >= 2.0:1)")

        # If live price changed, recalculate the trade plan
        if live_price and proposed_entry and abs(drift_pct or 0) > 2:
            # Recalculate using ATR-based stop from strategy
            new_risk = abs(live_price - proposed_stop)
            new_reward = abs(proposed_target - live_price)
            new_rr = new_reward / new_risk if new_risk > 0 else 0
            # Recalculate shares based on same dollar risk
            orig_dollar_risk = _f(proposal.get('proposed_dollar_risk')) or (abs(proposed_entry - proposed_stop) * proposed_shares if proposed_entry and proposed_stop else 0)
            new_shares = int(orig_dollar_risk / new_risk) if new_risk > 0 and orig_dollar_risk else proposed_shares
            adjustments.append({
                "field": "entry_price",
                "old": proposed_entry,
                "new": live_price,
                "reason": f"Market moved {drift_pct:+.1f}%"
            })
            if new_shares != proposed_shares:
                adjustments.append({
                    "field": "shares",
                    "old": proposed_shares,
                    "new": new_shares,
                    "reason": f"Resized to maintain ${orig_dollar_risk:.0f} risk at new entry"
                })

    # ── 4. STRATEGY YAML CRITERIA ──
    if config:
        filters = config.get('screen_filters', {})

        # Price range
        if live_price:
            min_price = filters.get('min_price')
            max_price = filters.get('max_price')
            if min_price and live_price < float(min_price):
                blockers.append(f"BELOW_MIN_PRICE: ${live_price:.2f} < strategy min ${min_price}")
            if max_price and live_price > float(max_price):
                blockers.append(f"ABOVE_MAX_PRICE: ${live_price:.2f} > strategy max ${max_price}")

        # RVOL
        min_rvol = filters.get('min_rvol')
        actual_rvol = _f(proposal.get('rvol'))
        if min_rvol and actual_rvol and actual_rvol < float(min_rvol):
            blockers.append(f"LOW_RVOL: {actual_rvol:.1f}x < strategy min {min_rvol}x")

        # Float
        max_float = filters.get('max_float_m')
        actual_float = _f(proposal.get('float_m'))
        if max_float and actual_float and actual_float > float(max_float):
            blockers.append(f"HIGH_FLOAT: {actual_float:.0f}M > strategy max {max_float}M")

        # Score
        min_score = filters.get('min_score')
        actual_score = proposal.get('signal_score')
        if min_score and actual_score is not None and int(actual_score) < int(min_score):
            blockers.append(f"LOW_SCORE: {actual_score} < strategy min {min_score}")

        # Catalyst requirement
        setup_qual = config.get('setup_qualification', {})
        if setup_qual.get('catalyst_present') == 'required':
            if not proposal.get('catalyst'):
                blockers.append("NO_CATALYST: Strategy requires a catalyst")
            elif setup_qual.get('catalyst_verified_for_live') and not proposal.get('catalyst_verified'):
                warnings.append("UNVERIFIED_CATALYST: Catalyst present but not verified")

        # Account eligibility
        eligible = config.get('eligible_accounts', [])
        forbidden = config.get('forbidden_accounts', [])
        acct = (proposal.get('proposed_account') or '').lower()
        if forbidden and acct:
            for f in forbidden:
                if f.lower() in acct:
                    blockers.append(f"FORBIDDEN_ACCOUNT: {acct} is forbidden for {strategy_id}")

        # Auto-disqualifiers
        for dq in config.get('auto_disqualifiers', []):
            dq_id = dq.get('id', 'UNKNOWN')
            cond = dq.get('condition', '')
            # Evaluate simple conditions
            if 'price >' in cond and live_price:
                threshold = float(cond.split('>')[-1].strip())
                if live_price > threshold:
                    blockers.append(f"AUTO_DQ_{dq_id}: price ${live_price:.2f} > ${threshold}")
            if 'float_m >' in cond and actual_float:
                threshold = float(cond.split('>')[-1].strip())
                if actual_float > threshold:
                    blockers.append(f"AUTO_DQ_{dq_id}: float {actual_float:.0f}M > {threshold}M")

    # ── 5. PAST TRADE HISTORY CHECK ──
    history = get_trade_history(symbol, strategy_id)
    losses = [h for h in history if 'loss' in h.get('title', '').lower() or 'WRONG' in h.get('title', '')]
    if losses:
        warnings.append(f"PAST_LOSSES: {len(losses)} prior loss(es) with {symbol}/{strategy_id}: " +
                        "; ".join(h.get('title', '')[:60] for h in losses[:2]))

    # ── 6. PROPOSAL STALENESS ──
    created = proposal.get('created_at')
    if created:
        age_hours = (datetime.now(timezone.utc) - (created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created)).total_seconds() / 3600
        staleness_config = {
            'INTRADAY': 2, 'SHORT_SWING': 72, 'MEDIUM_SWING': 120, 'POSITION': 240
        }
        timeframe_class = config.get('timeframe_class', 'SHORT_SWING') if config else 'SHORT_SWING'
        max_hours = staleness_config.get(timeframe_class, 72)
        if age_hours > max_hours:
            blockers.append(f"STALE_PROPOSAL: {age_hours:.0f}h old > {max_hours}h max for {timeframe_class}")
        elif age_hours > max_hours * 0.75:
            warnings.append(f"AGING_PROPOSAL: {age_hours:.0f}h old ({max_hours}h max)")

    # ── DETERMINE STATUS ──
    if blockers:
        status = "REJECTED"
    elif adjustments:
        status = "ADJUSTED"
    elif warnings:
        status = "ELIGIBLE_WITH_WARNINGS"
    else:
        status = "ELIGIBLE"

    result = {
        "status": status,
        "proposal_id": proposal_id,
        "symbol": symbol,
        "strategy_id": strategy_id,
        "live_price": live_price,
        "proposed_entry": proposed_entry,
        "drift_pct": round(drift_pct, 2) if drift_pct else None,
        "rr_ratio": round(rr_ratio, 2) if 'rr_ratio' in dir() and rr_ratio else None,
        "blockers": blockers,
        "warnings": warnings,
        "adjustments": adjustments,
        "past_losses": len(losses) if 'losses' in dir() else 0,
        "strategy_config_loaded": bool(config),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persist result to DB
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE paper_trade_proposals
            SET execution_eligibility_status = %s,
                execution_eligibility_reason = %s,
                live_price_at_execution = %s,
                live_price_timestamp = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, [
            status,
            json.dumps({"blockers": blockers, "warnings": warnings, "adjustments": adjustments})[:500],
            live_price,
            proposal_id
        ])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to persist validation result: {e}")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-id", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    from session13_db import get_conn
    conn = get_conn()
    result = validate_at_approval(conn, args.proposal_id)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Status: {result['status']}")
        print(f"Symbol: {result['symbol']} | Strategy: {result['strategy_id']}")
        if result['live_price']:
            print(f"Live price: ${result['live_price']:.2f} (drift: {result.get('drift_pct', 'N/A')}%)")
        if result.get('rr_ratio'):
            print(f"R:R ratio: {result['rr_ratio']:.2f}")
        for b in result['blockers']:
            print(f"  BLOCKER: {b}")
        for w in result['warnings']:
            print(f"  WARNING: {w}")
        for a in result['adjustments']:
            print(f"  ADJUST: {a['field']}: {a['old']} → {a['new']} ({a['reason']})")
