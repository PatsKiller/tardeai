#!/usr/bin/env python3
"""feedback_loop_processor.py — Close feedback loops across the system.

Runs daily. Connects:
  1. Proposals → paper trades → P&L outcomes → agent calibration
  2. CIO decisions → alert effectiveness scoring
  3. Strategy performance snapshots (weekly)
  4. Agent sample size tracking
  5. Recovery watch outcome detection

Usage:
    .venv/bin/python scripts/feedback_loop_processor.py
    .venv/bin/python scripts/feedback_loop_processor.py --dry-run
"""
import argparse
import json
import os
import sys
from datetime import datetime, date, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    import psycopg2
    pw = os.getenv("DB_PASSWORD", "")
    return psycopg2.connect(host="127.0.0.1", port=5432,
                            dbname="trade_ai", user="trade_ai", password=pw)


# ── 1. Proposal → Trade → Outcome Chain ─────────────────────────────────

def link_proposal_outcomes(conn, dry_run=False):
    """Find proposals that have been linked to paper trades and track outcomes."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find proposals not yet in the chain
    cur.execute("""
        SELECT p.id, p.symbol, p.strategy_id, p.status, p.proposed_by, p.created_at
        FROM paper_trade_proposals p
        WHERE NOT EXISTS (
            SELECT 1 FROM proposal_outcome_chain poc WHERE poc.proposal_id = p.id
        )
        AND p.status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST', 'REJECTED', 'EXPIRED', 'expired')
        ORDER BY p.created_at DESC LIMIT 100
    """)
    proposals = cur.fetchall()

    linked = 0
    for p in proposals:
        # Try to find a matching paper trade
        cur.execute("""
            SELECT id, status, pnl, r_multiple
            FROM paper_trades
            WHERE symbol = %s AND strategy_id = %s
            AND created_at >= %s
            ORDER BY created_at ASC LIMIT 1
        """, (p["symbol"], p["strategy_id"], p["created_at"]))
        trade = cur.fetchone()

        chain_status = "pending"
        trade_id = None
        trade_pnl = None
        trade_r = None
        trade_status = None

        if trade:
            trade_id = trade["id"]
            trade_status = trade["status"]
            trade_pnl = _f(trade.get("pnl"))
            trade_r = _f(trade.get("r_multiple"))
            if trade_status == "closed":
                chain_status = "closed"
            else:
                chain_status = "linked"
        elif p["status"] in ("REJECTED", "EXPIRED", "expired"):
            chain_status = "orphaned"

        if not dry_run:
            cur.execute("""
                INSERT INTO proposal_outcome_chain
                    (proposal_id, symbol, strategy_id, proposing_agent,
                     proposal_created, proposal_status, paper_trade_id,
                     trade_status, trade_pnl, trade_r_multiple, chain_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id) DO UPDATE SET
                    trade_status = EXCLUDED.trade_status,
                    trade_pnl = EXCLUDED.trade_pnl,
                    trade_r_multiple = EXCLUDED.trade_r_multiple,
                    chain_status = EXCLUDED.chain_status,
                    updated_at = NOW()
            """, (p["id"], p["symbol"], p["strategy_id"], p.get("proposed_by"),
                  p["created_at"], p["status"], trade_id,
                  trade_status, trade_pnl, trade_r, chain_status))
        linked += 1

    if not dry_run:
        conn.commit()
    return linked


# ── 2. Feed closed outcomes back to agent calibration ────────────────────

def feed_outcomes_to_agents(conn, dry_run=False):
    """For closed chains, feed P&L back to agent calibration."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, proposal_id, symbol, strategy_id, proposing_agent,
               trade_pnl, trade_r_multiple
        FROM proposal_outcome_chain
        WHERE chain_status = 'closed' AND outcome_fed_back = false
        AND trade_pnl IS NOT NULL
    """)
    closed = cur.fetchall()

    fed = 0
    for c in closed:
        agent = c.get("proposing_agent")
        if not agent:
            continue

        pnl = _f(c.get("trade_pnl", 0))
        verdict = "CORRECT" if pnl > 0 else "WRONG"

        if not dry_run:
            # Update the chain record
            cur.execute("""
                UPDATE proposal_outcome_chain
                SET outcome_fed_back = true, feedback_at = NOW()
                WHERE id = %s
            """, (c["id"],))

            # Insert into agent_recommendation_outcomes if not exists
            cur.execute("""
                INSERT INTO agent_recommendation_outcomes
                    (agent_name, symbol, recommendation, recommendation_date,
                     entry_date, realized_pnl, pnl_pct, verdict, verdict_score)
                VALUES (%s, %s, 'approve_trade', NOW(), NOW(), %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (agent, c["symbol"], pnl,
                  round(pnl / 100, 2) if pnl else 0,  # rough pnl_pct
                  verdict, 1.0 if verdict == "CORRECT" else -1.0))
        fed += 1

    if not dry_run:
        conn.commit()
    return fed


# ── 3. Alert Effectiveness Scoring ───────────────────────────────────────

def score_alert_effectiveness(conn, dry_run=False):
    """Score alerts from the last 7 days based on whether action was taken."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get alerts sent in last 7 days
    cur.execute("""
        SELECT notification_type, notification_date,
               payload::text as payload_text
        FROM notification_log
        WHERE status = 'sent' AND notification_date > CURRENT_DATE - 7
        AND notification_type NOT IN ('alert_fatigue_meta')
        ORDER BY notification_date
    """)
    alerts = cur.fetchall()

    scored = 0
    for alert in alerts:
        ntype = alert["notification_type"]
        ndate = alert["notification_date"]

        # Check if already scored
        cur.execute("""
            SELECT 1 FROM alert_effectiveness
            WHERE notification_type = %s AND alert_date = %s
            LIMIT 1
        """, (ntype, ndate))
        if cur.fetchone():
            continue

        # Determine if action was taken based on type
        action_taken = False
        action_desc = None

        # Check john_decision_queue for responses
        if ntype in ("urgent_alert", "draft_alert", "recovery_escalation"):
            cur.execute("""
                SELECT COUNT(*) as cnt FROM john_decision_queue
                WHERE status != 'pending_john'
                AND created_at::date = %s
            """, (ndate,))
            row = cur.fetchone()
            if row and row["cnt"] > 0:
                action_taken = True
                action_desc = f"{row['cnt']} decision(s) resolved"

        # Check agent_feedback_log for proposal responses
        elif ntype == "proposal_aging":
            cur.execute("""
                SELECT COUNT(*) as cnt FROM agent_feedback_log
                WHERE created_at::date = %s
            """, (ndate,))
            row = cur.fetchone()
            if row and row["cnt"] > 0:
                action_taken = True
                action_desc = f"{row['cnt']} proposal feedback"

        score = 1.0 if action_taken else 0.0

        if not dry_run:
            cur.execute("""
                INSERT INTO alert_effectiveness
                    (notification_type, alert_date, action_taken,
                     action_description, effectiveness_score)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (notification_type, symbol, alert_date) DO NOTHING
            """, (ntype, ndate, action_taken, action_desc, score))
        scored += 1

    if not dry_run:
        conn.commit()
    return scored


# ── 4. Strategy Performance Snapshots ────────────────────────────────────

def snapshot_strategy_performance(conn, dry_run=False):
    """Generate weekly strategy performance snapshots."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    today = date.today()

    # Only run on Sundays or if no snapshot exists this week
    cur.execute("""
        SELECT 1 FROM strategy_performance_snapshots
        WHERE snapshot_date > CURRENT_DATE - 7
        LIMIT 1
    """)
    if cur.fetchone():
        return 0  # Already have a recent snapshot

    cur.execute("""
        SELECT strategy_id,
               COUNT(*) FILTER (WHERE status='closed') as closed,
               COUNT(*) FILTER (WHERE status='closed' AND pnl > 0) as wins,
               COUNT(*) FILTER (WHERE status='closed' AND pnl <= 0) as losses,
               COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gp,
               COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gl,
               AVG(r_multiple) FILTER (WHERE status='closed') as avg_r,
               SUM(pnl) FILTER (WHERE status='closed') as total_pnl
        FROM paper_trades
        WHERE created_at > NOW() - INTERVAL '90 days'
        GROUP BY strategy_id
    """)
    strategies = cur.fetchall()

    saved = 0
    for s in strategies:
        strat = s["strategy_id"] or "unknown"
        closed = s["closed"] or 0
        wins = s["wins"] or 0
        losses = s["losses"] or 0
        gp = _f(s["gp"]) or 0
        gl = _f(s["gl"]) or 0
        wr = round(wins / max(closed, 1), 3)
        pf = round(gp / max(gl, 0.01), 3) if gl else 0

        rec = "maintain_current"
        if closed >= 5:
            if wr < 0.3:
                rec = "review_rules"
            elif pf < 0.8:
                rec = "review_risk_reward"

        if not dry_run:
            cur.execute("""
                INSERT INTO strategy_performance_snapshots
                    (snapshot_date, strategy_id, trades_closed, wins, losses,
                     win_rate, profit_factor, avg_r, total_pnl, recommendation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_date, strategy_id) DO NOTHING
            """, (today, strat, closed, wins, losses, wr, pf,
                  _f(s.get("avg_r")), _f(s.get("total_pnl")), rec))
        saved += 1

    if not dry_run:
        conn.commit()
    return saved


# ── 5. Agent Sample Size Tracking ────────────────────────────────────────

def track_agent_samples(conn, dry_run=False):
    """Snapshot agent calibration sample sizes and project time to next tier."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    today = date.today()

    cur.execute("""
        SELECT agent_name,
               recommendations, resolved, correct, incorrect,
               accuracy, sample_size_status
        FROM agent_calibration_windows
        WHERE window_end::date >= CURRENT_DATE - 7
        ORDER BY agent_name, created_at DESC
    """)
    windows = cur.fetchall()

    # Dedup by agent
    seen = set()
    tracked = 0
    for w in windows:
        agent = w["agent_name"]
        if agent in seen:
            continue
        seen.add(agent)

        resolved = w.get("resolved", 0) or 0
        correct = w.get("correct", 0) or 0
        wrong = w.get("incorrect", 0) or 0
        accuracy = _f(w.get("accuracy")) if w.get("accuracy") is not None else None
        tier = w.get("sample_size_status", "insight_only")

        # Estimate days to next tier
        daily_rate = max(resolved / 90, 0.1)  # average resolved per day
        if tier == "insight_only":
            needed = 25 - resolved
            days_to_next = max(0, round(needed / daily_rate))
        elif tier == "shadow_allowed":
            needed = 100 - resolved
            days_to_next = max(0, round(needed / daily_rate))
        else:
            days_to_next = 0

        if not dry_run:
            cur.execute("""
                INSERT INTO agent_sample_tracking
                    (agent_name, snapshot_date, total_recommendations, resolved,
                     correct, wrong, sample_tier, accuracy_pct, days_to_next_tier)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_name, snapshot_date) DO NOTHING
            """, (agent, today, w.get("recommendations", 0), resolved,
                  correct, wrong, tier,
                  round(accuracy * 100, 2) if accuracy else None, days_to_next))
        tracked += 1

    if not dry_run:
        conn.commit()
    return tracked


# ── 6. Recovery Outcome Detection ────────────────────────────────────────

def detect_recovery_outcomes(conn, dry_run=False):
    """Detect when recovery watch items have resolved."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find closed/reentered watch items not yet in outcome log
    cur.execute("""
        SELECT sow.id, sow.symbol, sow.exit_type, sow.patience_score,
               sow.stopped_out_at, sow.analyst_verdict, sow.status
        FROM stopped_out_watch sow
        WHERE sow.status IN ('closed', 'reentered')
        AND NOT EXISTS (
            SELECT 1 FROM recovery_outcome_log rol WHERE rol.watch_id = sow.id
        )
    """)
    resolved = cur.fetchall()

    logged = 0
    for r in resolved:
        days = (date.today() - r["stopped_out_at"]).days if r.get("stopped_out_at") else 0
        final = "reentered" if r["status"] == "reentered" else "abandoned"

        # Check if there's a paper trade for this symbol after the stop date
        cur.execute("""
            SELECT pnl FROM paper_trades
            WHERE symbol = %s AND created_at > %s AND status = 'closed'
            ORDER BY created_at DESC LIMIT 1
        """, (r["symbol"], r.get("stopped_out_at")))
        trade = cur.fetchone()
        reentry_pnl = _f(trade["pnl"]) if trade else None

        patience_correct = None
        if final == "reentered" and reentry_pnl is not None:
            patience_correct = reentry_pnl > 0  # patience was right if reentry was profitable

        if not dry_run:
            cur.execute("""
                INSERT INTO recovery_outcome_log
                    (watch_id, symbol, exit_type, final_verdict, patience_score,
                     days_monitored, reentry_pnl, patience_correct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (watch_id) DO NOTHING
            """, (r["id"], r["symbol"], r.get("exit_type"), final,
                  _f(r.get("patience_score")), days, reentry_pnl, patience_correct))
        logged += 1

    if not dry_run:
        conn.commit()
    return logged


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Feedback Loop Processor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[feedback_loop] Starting — {datetime.now().isoformat()}")
    conn = _get_conn()

    try:
        linked = link_proposal_outcomes(conn, dry_run=args.dry_run)
        print(f"  Proposal chains linked: {linked}")

        fed = feed_outcomes_to_agents(conn, dry_run=args.dry_run)
        print(f"  Outcomes fed to agents: {fed}")

        scored = score_alert_effectiveness(conn, dry_run=args.dry_run)
        print(f"  Alerts scored: {scored}")

        snaps = snapshot_strategy_performance(conn, dry_run=args.dry_run)
        print(f"  Strategy snapshots: {snaps}")

        tracked = track_agent_samples(conn, dry_run=args.dry_run)
        print(f"  Agent samples tracked: {tracked}")

        recovery = detect_recovery_outcomes(conn, dry_run=args.dry_run)
        print(f"  Recovery outcomes logged: {recovery}")

    finally:
        conn.close()

    print(f"[feedback_loop] Complete — {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
