#!/usr/bin/env python3
"""post_trade_thesis_reviewer.py — Compare thesis predictions vs actual outcomes.

For closed paper trades, compares the original proposal thesis (entry/stop/target/R)
against actual results and classifies the thesis outcome.

Uses local LLM for optional narrative review.
PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/post_trade_thesis_reviewer.py --dry-run
    .venv/bin/python scripts/post_trade_thesis_reviewer.py --apply
    .venv/bin/python scripts/post_trade_thesis_reviewer.py --paper-trade-id 123 --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from local_llm_config import get_local_llm_model

log = logging.getLogger("thesis_reviewer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def get_closed_trades(conn, days=30, paper_trade_id=None):
    """Fetch closed paper trades not yet thesis-reviewed."""
    cur = conn.cursor()
    if paper_trade_id:
        cur.execute("""
            SELECT pt.id, pt.symbol, pt.strategy_id, pt.proposal_id,
                   pt.entry_price, pt.exit_price, pt.stop_loss, pt.target_1,
                   pt.shares, pt.pnl, pt.pnl_pct, pt.r_multiple,
                   pt.exit_reason, pt.outcome_verdict, pt.planned_entry,
                   pt.entry_time, pt.exit_time, pt.hold_time_min
            FROM paper_trades pt
            WHERE pt.id = %s
              AND pt.status = 'closed'
              AND NOT EXISTS (
                  SELECT 1 FROM trade_thesis_outcomes tto
                  WHERE tto.paper_trade_id = pt.id
              )
        """, [paper_trade_id])
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cur.execute("""
            SELECT pt.id, pt.symbol, pt.strategy_id, pt.proposal_id,
                   pt.entry_price, pt.exit_price, pt.stop_loss, pt.target_1,
                   pt.shares, pt.pnl, pt.pnl_pct, pt.r_multiple,
                   pt.exit_reason, pt.outcome_verdict, pt.planned_entry,
                   pt.entry_time, pt.exit_time, pt.hold_time_min
            FROM paper_trades pt
            WHERE pt.status = 'closed'
              AND pt.closed_at >= %s
              AND NOT EXISTS (
                  SELECT 1 FROM trade_thesis_outcomes tto
                  WHERE tto.paper_trade_id = pt.id
              )
            ORDER BY pt.closed_at DESC
        """, [cutoff])

    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_proposal(conn, proposal_id):
    """Fetch the original proposal for a trade."""
    if not proposal_id:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
               proposed_target1, proposed_target2, proposed_shares,
               proposed_rr, signal_score, signal_grade
        FROM paper_trade_proposals
        WHERE id = %s
    """, [proposal_id])
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def get_evidence_snapshot(conn, proposal_id):
    """Fetch evidence snapshot for a proposal."""
    if not proposal_id:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT id, scan_snapshot, indicator_snapshot, quote_snapshot,
               catalyst_snapshot, agent_snapshot, quality_snapshot
        FROM proposal_evidence_snapshots
        WHERE proposal_id = %s
        ORDER BY created_at ASC
        LIMIT 1
    """, [proposal_id])
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def get_technical_snapshot(conn, proposal_id):
    """Fetch technical snapshot for a proposal."""
    if not proposal_id:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT id, rsi_14, atr_14, vwap, ema_alignment, macd_state,
               confluence_score, technical_grade, support_1, resistance_1
        FROM proposal_technical_snapshots
        WHERE proposal_id = %s
        ORDER BY computed_at ASC
        LIMIT 1
    """, [proposal_id])
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def classify_thesis_result(trade, proposal):
    """Determine thesis outcome based on actual vs expected."""
    exit_price = float(trade["exit_price"]) if trade.get("exit_price") else None
    entry_price = float(trade["entry_price"]) if trade.get("entry_price") else None
    exit_reason = (trade.get("exit_reason") or "").lower()

    if exit_price is None or entry_price is None:
        return "UNKNOWN", "missing_price_data"

    # Use proposal levels if available, else trade levels
    if proposal:
        expected_stop = float(proposal.get("proposed_stop") or 0) or None
        expected_target = float(proposal.get("proposed_target1") or 0) or None
    else:
        expected_stop = float(trade.get("stop_loss") or 0) or None
        expected_target = float(trade.get("target_1") or 0) or None

    # Manual close detection
    if "manual" in exit_reason or "user" in exit_reason or "abandoned" in exit_reason:
        return "THESIS_ABANDONED", "manual_close"

    # Stop hit detection
    if expected_stop and exit_price <= expected_stop:
        return "THESIS_INVALIDATED", "stop_hit"
    if "stop" in exit_reason:
        return "THESIS_INVALIDATED", "stop_exit_reason"

    # Target hit detection
    if expected_target and exit_price >= expected_target:
        return "THESIS_CONFIRMED", "target_hit"
    if "target" in exit_reason:
        return "THESIS_CONFIRMED", "target_exit_reason"

    # Partial win: profitable but didn't hit target
    pnl = float(trade.get("pnl") or 0)
    if pnl > 0:
        return "THESIS_PARTIAL", "profitable_early_exit"

    # Unprofitable but didn't hit stop
    if pnl <= 0 and expected_stop and exit_price > expected_stop:
        return "THESIS_PARTIAL", "loss_before_stop"

    return "UNKNOWN", "unclassifiable"


def compute_expected_r(proposal):
    """Compute expected R from proposal."""
    if not proposal:
        return None
    entry = float(proposal.get("proposed_entry") or 0)
    stop = float(proposal.get("proposed_stop") or 0)
    target = float(proposal.get("proposed_target1") or 0)
    if entry and stop and target and entry != stop:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        return round(reward / risk, 2) if risk > 0 else None
    return None


def compute_actual_r(trade):
    """Compute actual R from trade results."""
    entry = float(trade.get("entry_price") or 0)
    exit_p = float(trade.get("exit_price") or 0)
    stop = float(trade.get("stop_loss") or 0)
    if entry and exit_p and stop and entry != stop:
        risk = abs(entry - stop)
        actual_move = exit_p - entry
        return round(actual_move / risk, 2) if risk > 0 else None
    return trade.get("r_multiple")


def generate_llm_review(trade, proposal, evidence, technical, thesis_result):
    """Generate LLM narrative review if available."""
    try:
        import urllib.request
        from local_llm_config import get_local_llm_base_url
        _base = get_local_llm_base_url().rstrip("/")
        req = urllib.request.Request(f"{_base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        return None, None

    model = get_local_llm_model()

    prompt = f"""You are a professional trade reviewer. Analyze this closed paper trade concisely.

Trade: {trade['symbol']} ({trade.get('strategy_id', 'unknown')})
Entry: {trade.get('entry_price')} | Exit: {trade.get('exit_price')} | PnL: {trade.get('pnl')} ({trade.get('pnl_pct')}%)
R-multiple: {trade.get('r_multiple')} | Hold: {trade.get('hold_time_min')} min | Exit reason: {trade.get('exit_reason')}
Thesis result: {thesis_result}
"""

    if proposal:
        prompt += f"""
Proposal: entry={proposal.get('proposed_entry')} stop={proposal.get('proposed_stop')} target={proposal.get('proposed_target1')} R:R={proposal.get('proposed_rr')}
Score: {proposal.get('signal_score')} Grade: {proposal.get('signal_grade')}
"""

    if technical:
        prompt += f"""
Technicals at entry: RSI={technical.get('rsi_14')} ATR={technical.get('atr_14')} VWAP={technical.get('vwap')} EMA={technical.get('ema_alignment')} Grade={technical.get('technical_grade')}
"""

    prompt += """
Provide a 2-3 sentence review covering: (1) Was the thesis setup valid? (2) What could improve? Keep it factual and brief. Respond in plain text only."""

    try:
        from local_llm import generate
        text = generate(prompt, timeout=60,
                        caller="post_trade_thesis_reviewer", process_type="STANDARD")
        return (text.strip() if text else None), model
    except Exception as e:
        log.warning(f"LLM review failed: {e}")
        return None, None


def review_trade(conn, trade):
    """Review a single closed trade against its thesis."""
    proposal = get_proposal(conn, trade.get("proposal_id"))
    evidence = get_evidence_snapshot(conn, trade.get("proposal_id"))
    technical = get_technical_snapshot(conn, trade.get("proposal_id"))

    thesis_result, reason = classify_thesis_result(trade, proposal)

    expected_entry = float(proposal["proposed_entry"]) if proposal and proposal.get("proposed_entry") else None
    expected_stop = float(proposal["proposed_stop"]) if proposal and proposal.get("proposed_stop") else float(trade.get("stop_loss") or 0) or None
    expected_target = float(proposal["proposed_target1"]) if proposal and proposal.get("proposed_target1") else float(trade.get("target_1") or 0) or None
    expected_r = compute_expected_r(proposal)
    actual_r = compute_actual_r(trade)

    # Determine if invalidation was hit
    exit_price = float(trade["exit_price"]) if trade.get("exit_price") else None
    invalidation_hit = False
    if expected_stop and exit_price:
        invalidation_hit = exit_price <= expected_stop

    # LLM narrative review
    llm_review, llm_model = generate_llm_review(trade, proposal, evidence, technical, thesis_result)

    review_payload = {
        "thesis_result": thesis_result,
        "classification_reason": reason,
        "proposal_available": proposal is not None,
        "evidence_available": evidence is not None,
        "technical_available": technical is not None,
        "trade_pnl": trade.get("pnl"),
        "trade_pnl_pct": trade.get("pnl_pct"),
        "exit_reason": trade.get("exit_reason"),
        "hold_time_min": trade.get("hold_time_min"),
    }
    if llm_review:
        review_payload["llm_narrative"] = llm_review

    return {
        "paper_trade_id": trade["id"],
        "proposal_id": trade.get("proposal_id"),
        "symbol": trade["symbol"],
        "strategy_id": trade.get("strategy_id"),
        "thesis_snapshot_id": evidence.get("id") if evidence else None,
        "expected_entry": expected_entry,
        "expected_stop": expected_stop,
        "expected_target": expected_target,
        "expected_r": expected_r,
        "actual_entry": float(trade["entry_price"]) if trade.get("entry_price") else None,
        "actual_exit": exit_price,
        "actual_r": actual_r,
        "thesis_result": thesis_result,
        "invalidation_hit": invalidation_hit,
        "kill_condition_triggered": reason if thesis_result == "THESIS_INVALIDATED" else None,
        "llm_review_model": llm_model,
        "review_payload": review_payload,
    }


def insert_result(conn, result):
    """Insert thesis outcome into DB."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO trade_thesis_outcomes
            (paper_trade_id, proposal_id, symbol, strategy_id,
             thesis_snapshot_id, expected_entry, expected_stop, expected_target,
             expected_r, actual_entry, actual_exit, actual_r,
             thesis_result, invalidation_hit, kill_condition_triggered,
             llm_review_model, review_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        result["paper_trade_id"], result.get("proposal_id"),
        result["symbol"], result.get("strategy_id"),
        result.get("thesis_snapshot_id"),
        result.get("expected_entry"), result.get("expected_stop"), result.get("expected_target"),
        result.get("expected_r"), result.get("actual_entry"), result.get("actual_exit"),
        result.get("actual_r"), result["thesis_result"], result["invalidation_hit"],
        result.get("kill_condition_triggered"), result.get("llm_review_model"),
        json.dumps(result.get("review_payload"), default=str) if result.get("review_payload") else None,
    ])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Post-trade thesis reviewer")
    parser.add_argument("--paper-trade-id", type=int, help="Review a specific closed paper trade")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write to DB")
    parser.add_argument("--apply", action="store_true", help="Write results to DB")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    conn = get_conn()
    try:
        trades = get_closed_trades(conn, paper_trade_id=args.paper_trade_id)

        if not trades:
            output = {"status": "no_data", "message": "No closed trades to review", "results": []}
            print(json.dumps(output, indent=2, default=str))
            return

        results = []
        for trade in trades:
            result = review_trade(conn, trade)
            results.append(result)

            if args.apply:
                insert_result(conn, result)
                log.info(f"Inserted thesis outcome for trade {result['paper_trade_id']} "
                         f"({result['symbol']}): {result['thesis_result']}")

        # Summary
        result_counts = {}
        for r in results:
            tr = r["thesis_result"]
            result_counts[tr] = result_counts.get(tr, 0) + 1

        output = {
            "status": "dry_run" if args.dry_run else "applied",
            "trades_reviewed": len(results),
            "thesis_summary": result_counts,
            "results": results,
        }
        print(json.dumps(output, indent=2, default=str))

    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Phase 5 — Post-trade price recovery analysis (2026-05-14)
# ──────────────────────────────────────────────────────────────

STRATEGY_HOLD_NORMS = {
    'momentum_scalp':            {'min': 0.25, 'norm': 1.0,  'max': 4.0},
    'earnings_catalyst':         {'min': 4.0,  'norm': 24.0, 'max': 120.0},
    'swing_breakout':            {'min': 8.0,  'norm': 48.0, 'max': 168.0},
    'swing_trade':               {'min': 8.0,  'norm': 48.0, 'max': 168.0},
    'dividend_growth_compounder':{'min': 168.0,'norm': 720.0,'max': 8760.0},
    'gap_and_go':                {'min': 0.5,  'norm': 2.0,  'max': 8.0},
    'speculative_growth':        {'min': 24.0, 'norm': 96.0, 'max': 336.0},
    'recovery_watch':            {'min': 48.0, 'norm': 168.0,'max': 720.0},
    'DEFAULT':                   {'min': 1.0,  'norm': 24.0, 'max': 168.0},
}


def fetch_post_exit_bars(symbol, exit_time):
    """Pull 15min bars from Alpaca for 4h window after exit, plus EOD."""
    import os, requests
    key = os.getenv('ALPACA_API_KEY', '')
    secret = os.getenv('ALPACA_SECRET_KEY', '')
    headers = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}
    result = {
        'price_15min': None, 'price_1h': None, 'price_4h': None,
        'price_eod': None, 'max_favorable_4h': None, 'max_adverse_4h': None,
        'bars_fetched': 0, 'error': None,
    }
    try:
        start = exit_time
        end = exit_time + timedelta(hours=4)
        r = requests.get('https://data.alpaca.markets/v2/stocks/{}/bars'.format(symbol),
                         params={'timeframe': '15Min', 'start': start.isoformat(),
                                 'end': end.isoformat(), 'limit': 20},
                         headers=headers, timeout=15)
        if not r.ok:
            result['error'] = f'bars_http_{r.status_code}'
            return result
        bars = r.json().get('bars', [])
        result['bars_fetched'] = len(bars)
        if not bars:
            result['error'] = 'no_bars_returned'
            return result
        if len(bars) >= 1:
            result['price_15min'] = float(bars[0]['c'])
        if len(bars) >= 4:
            result['price_1h'] = float(bars[3]['c'])
        if len(bars) >= 16:
            result['price_4h'] = float(bars[15]['c'])
        result['max_favorable_4h'] = max(float(b['h']) for b in bars)
        result['max_adverse_4h'] = min(float(b['l']) for b in bars)

        # EOD bar
        r2 = requests.get('https://data.alpaca.markets/v2/stocks/{}/bars'.format(symbol),
                          params={'timeframe': '1Day', 'start': exit_time.strftime('%Y-%m-%d'),
                                  'end': (exit_time + timedelta(days=1)).strftime('%Y-%m-%d'), 'limit': 1},
                          headers=headers, timeout=15)
        if r2.ok:
            eod_bars = r2.json().get('bars', [])
            if eod_bars:
                result['price_eod'] = float(eod_bars[0]['c'])
    except Exception as e:
        result['error'] = str(e)[:200]
        log.error(f"Bars fetch failed for {symbol}: {e}")
    return result


def compute_recovery_verdicts(trade, bars_data):
    """Compute stop_too_tight, would_have_recovered, held_too_short/long, thesis_outcome."""
    entry = float(trade['entry_price']) if trade.get('entry_price') else None
    stop = float(trade['stop_loss']) if trade.get('stop_loss') else None
    target = float(trade['target_1']) if trade.get('target_1') else None
    exit_reason = trade.get('exit_reason', '') or ''
    verdicts = {'stop_too_tight': None, 'would_have_recovered': None,
                'held_too_short': None, 'held_too_long': None, 'thesis_outcome': 'INCONCLUSIVE'}

    # stop_too_tight: price recovered 2%+ above stop within 4h
    if stop and bars_data.get('max_favorable_4h') and 'stop' in exit_reason.lower():
        verdicts['stop_too_tight'] = bars_data['max_favorable_4h'] >= stop * 1.02

    # would_have_recovered: EOD > entry
    if entry and bars_data.get('price_eod'):
        verdicts['would_have_recovered'] = bars_data['price_eod'] > entry

    # hold time
    norms = STRATEGY_HOLD_NORMS.get(trade.get('strategy_id', ''), STRATEGY_HOLD_NORMS['DEFAULT'])
    hold_hours = trade.get('hold_hours')
    if hold_hours is not None:
        verdicts['held_too_short'] = hold_hours < norms['min']
        verdicts['held_too_long'] = hold_hours > norms['max']

    # thesis outcome
    if target and entry and bars_data.get('max_favorable_4h'):
        if bars_data['max_favorable_4h'] >= target:
            verdicts['thesis_outcome'] = 'FULL'
        elif bars_data['max_favorable_4h'] > entry:
            verdicts['thesis_outcome'] = 'PARTIAL'
        else:
            verdicts['thesis_outcome'] = 'FAILED'
    return verdicts


def generate_lesson_qwen3(trade, bars_data, verdicts):
    """Call qwen3:14b for a 1-2 sentence lesson. Returns (text, tokens)."""
    import requests as _req
    prompt = f"""/no_think Analyze this paper trade and give ONE specific lesson in 1-2 sentences.

Trade: {trade.get('symbol')} {trade.get('strategy_id')}
Entry: ${trade.get('entry_price')} Exit: ${trade.get('exit_price')} (reason: {trade.get('exit_reason')})
Stop: ${trade.get('stop_loss')} PnL: ${trade.get('pnl')} Hold: {trade.get('hold_hours', '?')}h

Post-exit: 15min=${bars_data.get('price_15min')}, 1h=${bars_data.get('price_1h')}, max_favorable_4h=${bars_data.get('max_favorable_4h')}, EOD=${bars_data.get('price_eod')}
Verdicts: stop_too_tight={verdicts.get('stop_too_tight')}, would_have_recovered={verdicts.get('would_have_recovered')}, thesis={verdicts.get('thesis_outcome')}

Output ONLY the lesson. Be concrete: "Don't use X% stops on Y when ..." or "Hold Z at least N hours because ...".
"""
    try:
        r = _req.post('http://localhost:11434/api/generate',
                      json={'model': 'qwen3:14b', 'prompt': prompt, 'stream': False,
                            'options': {'num_predict': 1000, 'temperature': 0.3}},
                      timeout=120)
        r.raise_for_status()
        d = r.json()
        lesson = (d.get('response') or '').strip()
        if not lesson and d.get('thinking'):
            # Extract useful content from thinking if response empty
            lesson = d['thinking'].strip()[-300:]
        return lesson[:500], d.get('eval_count', 0)
    except Exception as e:
        log.error(f"qwen3 lesson failed: {e}")
        return f"Lesson generation failed: {e}", 0


def run_price_recovery_analysis(trade_id, conn):
    """Orchestrator: fetch bars, compute verdicts, generate lesson, write row."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, proposal_id, symbol, strategy_id,
               entry_price, exit_price, stop_loss, target_1,
               entry_time, closed_at, pnl, exit_reason,
               EXTRACT(EPOCH FROM (closed_at - entry_time))/3600
        FROM paper_trades WHERE id = %s AND lifecycle_state = 'closed'
    """, [trade_id])
    row = cur.fetchone()
    if not row:
        return None
    trade = dict(zip(['id', 'proposal_id', 'symbol', 'strategy_id', 'entry_price',
                       'exit_price', 'stop_loss', 'target_1', 'entry_time', 'closed_at',
                       'pnl', 'exit_reason', 'hold_hours'], row))

    bars = fetch_post_exit_bars(trade['symbol'], trade['closed_at'])
    verdicts = compute_recovery_verdicts(trade, bars)
    lesson, tokens = generate_lesson_qwen3(trade, bars, verdicts)

    cur.execute("""
        INSERT INTO post_trade_price_analysis (
            trade_id, proposal_id, symbol, strategy_id,
            entry_price, exit_price, stop_loss, target_1,
            price_15min_after, price_1h_after, price_4h_after, price_eod,
            max_favorable_4h, max_adverse_4h,
            stop_too_tight, would_have_recovered, held_too_short, held_too_long,
            thesis_outcome, lesson_text, lesson_model, bars_fetched, fetch_errors, backfilled
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, 'qwen3:14b', %s, %s, %s
        ) ON CONFLICT (trade_id) DO UPDATE SET
            price_15min_after=EXCLUDED.price_15min_after, price_1h_after=EXCLUDED.price_1h_after,
            price_4h_after=EXCLUDED.price_4h_after, price_eod=EXCLUDED.price_eod,
            stop_too_tight=EXCLUDED.stop_too_tight, would_have_recovered=EXCLUDED.would_have_recovered,
            lesson_text=EXCLUDED.lesson_text, analyzed_at=NOW()
        RETURNING id
    """, [trade['id'], trade['proposal_id'], trade['symbol'], trade['strategy_id'],
          trade['entry_price'], trade['exit_price'], trade['stop_loss'], trade['target_1'],
          bars.get('price_15min'), bars.get('price_1h'), bars.get('price_4h'), bars.get('price_eod'),
          bars.get('max_favorable_4h'), bars.get('max_adverse_4h'),
          verdicts.get('stop_too_tight'), verdicts.get('would_have_recovered'),
          verdicts.get('held_too_short'), verdicts.get('held_too_long'),
          verdicts.get('thesis_outcome'), lesson, bars.get('bars_fetched', 0),
          bars.get('error'), False])
    rid = cur.fetchone()[0]
    conn.commit()
    log.info(f"Price recovery analysis written for trade {trade_id}: row {rid}")
    return rid


if __name__ == "__main__":
    main()
