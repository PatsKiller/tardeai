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
        import urllib.request
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }).encode()
        req = urllib.request.Request(
            f"{_base}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip(), model
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


if __name__ == "__main__":
    main()
