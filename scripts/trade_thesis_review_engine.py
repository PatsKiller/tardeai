#!/usr/bin/env python3
"""trade_thesis_review_engine.py — Enhanced post-trade thesis review with scoring.

Reviews each closed/cancelled paper trade against original thesis, scores
execution/risk/agent alignment, and generates learning evidence.

Usage:
    .venv/bin/python scripts/trade_thesis_review_engine.py --dry-run --json
    .venv/bin/python scripts/trade_thesis_review_engine.py --apply --json
    .venv/bin/python scripts/trade_thesis_review_engine.py --trade-id 1 --dry-run --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="TTR_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def get_reviewable(conn, trade_id=None, symbol=None):
    cur = conn.cursor()
    conds = ["pt.status IN ('closed', 'cancelled')"]
    params = []
    if trade_id:
        conds.append("pt.id = %s"); params.append(trade_id)
    if symbol:
        conds.append("pt.symbol = %s"); params.append(symbol)
    conds.append("NOT EXISTS (SELECT 1 FROM trade_thesis_reviews r WHERE r.paper_trade_id = pt.id)")

    # DISTINCT ON (pt.id): the proposal LEFT JOIN matches every same-symbol proposal in a ±7d
    # window, which fans one trade out to N rows → N duplicate reviews. Collapse to one row per
    # trade, keeping the nearest proposal (smallest |proposal - trade| creation gap).
    cur.execute(f"""
        SELECT * FROM (
            SELECT DISTINCT ON (pt.id)
                   pt.id, pt.symbol, pt.strategy_id, pt.status, pt.pnl, pt.r_multiple,
                   pt.entry_price, pt.exit_price, pt.stop_loss, pt.target_1,
                   pt.created_at, pt.closed_at,
                   pp.id as proposal_id, pp.proposed_entry, pp.proposed_stop,
                   pp.proposed_target1, pp.catalyst, pp.signal_score
            FROM paper_trades pt
            LEFT JOIN paper_trade_proposals pp ON pt.symbol = pp.symbol
                AND pp.created_at BETWEEN pt.created_at - interval '7 days' AND pt.created_at + interval '7 days'
            WHERE {' AND '.join(conds)}
            ORDER BY pt.id, abs(extract(epoch FROM pp.created_at - pt.created_at)) NULLS LAST
        ) q
        ORDER BY q.created_at DESC LIMIT 100
    """, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_agent_views(conn, symbol, around):
    if not around: return []
    cur = conn.cursor()
    cur.execute("""
        SELECT agent_name, recommendation_type, confidence, recommendation_time
        FROM agent_recommendation_registry
        WHERE symbol=%s AND recommendation_time BETWEEN %s - interval '7 days' AND %s + interval '1 day'
        ORDER BY recommendation_time DESC LIMIT 10
    """, [symbol, around, around])
    return [{"agent": r[0], "rec": r[1], "confidence": _f(r[2])} for r in cur.fetchall()]


def review(conn, t):
    sym = t["symbol"]
    pnl = _f(t.get("pnl"))
    r_m = _f(t.get("r_multiple"))
    status = t["status"]
    agents = get_agent_views(conn, sym, t.get("created_at"))

    entry_plan = {"proposed": _f(t.get("proposed_entry")), "actual": _f(t.get("entry_price")),
                  "stop": _f(t.get("proposed_stop")), "target": _f(t.get("proposed_target1"))}

    ts, ex, rk, ag, src, oc = 50, 50, 50, 50, 50, 0
    validity = "unresolved"
    mistakes, strengths = [], []

    if status == "closed":
        if pnl and pnl > 0:
            validity = "held"; ts = 70; oc = min(100, int(50 + (r_m or 0) * 20))
            strengths.append("thesis_confirmed")
        elif pnl and pnl < 0:
            validity = "failed"; ts = 30; oc = max(-100, int(-50 + (r_m or 0) * 20))
            mistakes.append("thesis_failed")

        pe, ae = _f(t.get("proposed_entry")), _f(t.get("entry_price"))
        if pe and ae:
            slip = abs(ae - pe) / pe * 100
            if slip < 0.5: ex = 80; strengths.append("good_entry_execution")
            elif slip > 2: ex = 30; mistakes.append("poor_entry_timing")

        if r_m and r_m < -1.5: rk = 30; mistakes.append("stop_too_loose")
        elif r_m and r_m > 1: rk = 80; strengths.append("stop_protected_capital")
    elif status == "cancelled":
        validity = "invalidated_before_entry"; ts = 40

    if agents:
        bull = sum(1 for a in agents if a["rec"] in ("buy", "add", "approve_trade"))
        bear = sum(1 for a in agents if a["rec"] in ("sell", "trim", "avoid", "reject_trade"))
        if pnl and pnl > 0 and bull > bear: ag = 75; strengths.append("agent_alignment_confirmed")
        elif pnl and pnl < 0 and bear > bull: ag = 70; mistakes.append("ignored_agent_warning")

    lesson = f"{sym}: thesis {validity}"
    if pnl: lesson += f", PnL=${pnl:.2f}" + (f", R={r_m:.1f}" if r_m else "")

    return {
        "review_id": _uid(), "paper_trade_id": t["id"], "proposal_id": t.get("proposal_id"),
        "symbol": sym, "strategy_id": t.get("strategy_id"), "trade_status": status,
        "review_type": "post_close" if status == "closed" else "cancelled_before_entry",
        "original_thesis": t.get("catalyst") or "",
        "original_entry_plan": entry_plan,
        "original_risk_plan": {"stop": _f(t.get("proposed_stop")), "target": _f(t.get("proposed_target1"))},
        "original_catalyst": {"catalyst": t.get("catalyst")},
        "original_agent_views": agents,
        "actual_outcome": {"pnl": pnl, "r_multiple": r_m, "status": status},
        "thesis_validity": validity, "thesis_score": ts, "execution_score": ex,
        "risk_management_score": rk, "agent_alignment_score": ag,
        "source_quality_score": src, "outcome_score": oc,
        "lesson_summary": lesson, "mistake_tags": mistakes,
        "strength_tags": strengths, "low_sample_size": True,
    }


def save(conn, reviews, dry_run=True):
    if dry_run: return
    cur = conn.cursor()
    for r in reviews:
        cur.execute("""
            INSERT INTO trade_thesis_reviews
                (review_id, paper_trade_id, proposal_id, symbol, strategy_id,
                 trade_status, review_type, original_thesis, original_entry_plan,
                 original_risk_plan, original_catalyst, original_agent_views,
                 actual_outcome, thesis_validity, thesis_score, execution_score,
                 risk_management_score, agent_alignment_score, source_quality_score,
                 outcome_score, lesson_summary, mistake_tags, strength_tags, low_sample_size)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (review_id) DO NOTHING
        """, [r["review_id"], r.get("paper_trade_id"), r.get("proposal_id"),
              r["symbol"], r.get("strategy_id"), r["trade_status"], r["review_type"],
              r.get("original_thesis", ""),
              json.dumps(r.get("original_entry_plan"), default=str),
              json.dumps(r.get("original_risk_plan"), default=str),
              json.dumps(r.get("original_catalyst"), default=str),
              json.dumps(r.get("original_agent_views"), default=str),
              json.dumps(r.get("actual_outcome"), default=str),
              r["thesis_validity"], r["thesis_score"], r["execution_score"],
              r["risk_management_score"], r["agent_alignment_score"],
              r["source_quality_score"], r["outcome_score"], r["lesson_summary"],
              json.dumps(r["mistake_tags"]), json.dumps(r["strength_tags"]),
              r["low_sample_size"]])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Post-Trade Thesis Review Engine")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--trade-id", type=int)
    parser.add_argument("--symbol")
    parser.add_argument("--open-checkpoints", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        trades = get_reviewable(conn, trade_id=args.trade_id, symbol=args.symbol)
        reviews = [review(conn, t) for t in trades]
        # save() defaults to dry_run=True — must pass the real flag or --apply silently no-ops
        # (if dry_run: return), which is why trade_thesis_reviews stayed empty despite --apply.
        if not dry_run: save(conn, reviews, dry_run=False)

        out = {"mode": "dry_run" if dry_run else "applied", "trades_reviewed": len(reviews),
               "by_validity": {}, "low_sample_size": True}
        for r in reviews:
            out["by_validity"][r["thesis_validity"]] = out["by_validity"].get(r["thesis_validity"], 0) + 1
        if args.json:
            out["reviews"] = [{k: v for k, v in r.items() if k != "original_agent_views"} for r in reviews]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Thesis Reviews: {out['trades_reviewed']} ({out['mode']})")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
