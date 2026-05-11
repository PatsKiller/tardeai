#!/usr/bin/env python3
"""agent_calibration_engine.py — Score agent recommendations against outcomes.

Generates calibration events, windows, learning evidence and recommendations.
No active config changes. Dry-run safe.

Usage:
    .venv/bin/python scripts/agent_calibration_engine.py --dry-run --json
    .venv/bin/python scripts/agent_calibration_engine.py --apply --json
    .venv/bin/python scripts/agent_calibration_engine.py --agent Maria --dry-run --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(prefix="ACE_"): return f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

AGENT_SAMPLE_INSIGHT = 25
AGENT_SAMPLE_SHADOW = 100

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def score_recommendations(conn, agent_filter=None, window_days=90):
    """Score linked recommendations against outcomes."""
    cur = conn.cursor()
    sql = """
        SELECT r.recommendation_id, r.agent_name, r.symbol, r.strategy_id,
               r.recommendation_type, r.confidence, r.recommendation_time,
               l.outcome_type, l.paper_trade_id, l.proposal_id, l.link_confidence
        FROM agent_recommendation_registry r
        JOIN agent_recommendation_outcome_links l ON r.recommendation_id = l.recommendation_id
        WHERE r.recommendation_time > now() - interval '%s days'
    """ % window_days
    params = []
    if agent_filter:
        sql += " AND r.agent_name ILIKE %s"
        params.append(f"%{agent_filter}%")
    sql += " ORDER BY r.recommendation_time DESC LIMIT 2000"
    cur.execute(sql, params)

    events = []
    for row in cur.fetchall():
        rec_id, agent, symbol, strat, rec_type, conf, rec_time = row[:7]
        outcome_type, trade_id, proposal_id, link_conf = row[7:]

        actual = "unresolved"
        outcome_score = 0
        pnl = None
        r_mult = None
        explanation = "no_outcome_data"

        # ── Check if this symbol is a relist (no true stop-out) ──
        is_relist = False
        try:
            cur.execute("""
                SELECT 1 FROM stopped_out_watch
                WHERE symbol = %s AND is_active = true
                  AND explicit_stop_out = false
                  AND (relisted_without_stop_out = true OR market_reconnection_event = true)
                LIMIT 1
            """, [symbol])
            is_relist = cur.fetchone() is not None
        except Exception:
            pass  # table may not have new columns yet

        # Check paper trade outcome
        if trade_id:
            cur.execute("SELECT status, pnl, r_multiple FROM paper_trades WHERE id=%s", [trade_id])
            trade = cur.fetchone()
            if trade:
                status, t_pnl, t_r = trade
                pnl = _f(t_pnl)
                r_mult = _f(t_r)
                if status == "closed":
                    if rec_type in ("buy", "add", "approve_trade"):
                        if (pnl or 0) > 0:
                            actual = "correct"
                            outcome_score = 1
                        elif is_relist:
                            # Relist: loss is market noise, not recommendation failure
                            actual = "relist_neutral"
                            outcome_score = 0
                        else:
                            actual = "incorrect"
                            outcome_score = -1
                        explanation = f"trade closed pnl={pnl}" + (" [relist]" if is_relist else "")
                    elif rec_type in ("sell", "trim", "avoid", "reject_trade"):
                        if (pnl or 0) <= 0:
                            actual = "correct"
                            outcome_score = 1
                        elif is_relist:
                            actual = "relist_neutral"
                            outcome_score = 0
                        else:
                            actual = "incorrect"
                            outcome_score = -1
                        explanation = f"contrarian trade closed pnl={pnl}" + (" [relist]" if is_relist else "")
                    else:
                        actual = "neutral"
                        explanation = f"non-directional rec, trade closed pnl={pnl}"
                else:
                    actual = "unresolved"
                    explanation = f"trade still {status}"

        # Check proposal outcome
        elif proposal_id:
            cur.execute("SELECT status FROM paper_trade_proposals WHERE id=%s", [proposal_id])
            prop = cur.fetchone()
            if prop:
                if prop[0] == "REJECTED":
                    if rec_type in ("avoid", "wait", "reject_trade"):
                        actual = "correct"
                        outcome_score = 0.5
                        explanation = "proposal rejected, rec was cautious"
                    else:
                        actual = "neutral"
                        explanation = "proposal rejected"
                elif prop[0] in ("APPROVED", "APPROVED_FOR_PAPER_TEST"):
                    if rec_type in ("buy", "add", "approve_trade"):
                        actual = "partially_correct"
                        outcome_score = 0.3
                        explanation = "proposal approved, awaiting trade outcome"
                    else:
                        actual = "neutral"
                        explanation = "proposal approved"
                else:
                    actual = "unresolved"
                    explanation = f"proposal status={prop[0]}"

        # Calibration error — skip relist_neutral (market event, not cal signal)
        cal_error = None
        overconf = None
        underconf = None
        if conf is not None and actual in ("correct", "incorrect"):
            c = float(conf)
            expected = c
            realized = 1.0 if actual == "correct" else 0.0
            cal_error = abs(expected - realized)
            overconf = max(0, expected - realized)
            underconf = max(0, realized - expected)
        # relist_neutral: no calibration error — this was a market event

        events.append({
            "calibration_event_id": _uid(),
            "recommendation_id": rec_id,
            "agent_name": agent,
            "symbol": symbol,
            "strategy_id": strat,
            "outcome_type": outcome_type,
            "scoring_window": f"{window_days}d",
            "predicted_action": rec_type,
            "predicted_confidence": _f(conf),
            "actual_outcome": actual,
            "outcome_score": outcome_score,
            "pnl": pnl,
            "r_multiple": r_mult,
            "calibration_error": cal_error,
            "overconfidence": overconf,
            "underconfidence": underconf,
            "explanation": explanation,
        })

    return events


def aggregate_windows(events, window_days=90):
    """Aggregate calibration events into per-agent windows."""
    now = datetime.now(timezone.utc)
    windows = {}

    for ev in events:
        agent = ev["agent_name"]
        if agent not in windows:
            windows[agent] = {
                "window_id": _uid("ACW_"),
                "agent_name": agent,
                "window_start": str(now - timedelta(days=window_days)),
                "window_end": str(now),
                "domain": "general",
                "recommendations": 0, "resolved": 0,
                "correct": 0, "incorrect": 0, "neutral": 0,
                "partially_correct": 0, "unresolved": 0,
                "relist_neutral": 0,
                "confidences": [], "outcome_scores": [], "cal_errors": [],
                "overconfs": [], "underconfs": [], "r_multiples": [],
            }

        w = windows[agent]
        w["recommendations"] += 1
        w[ev["actual_outcome"]] = w.get(ev["actual_outcome"], 0) + 1
        if ev["actual_outcome"] not in ("unresolved", "relist_neutral"):
            # relist_neutral is excluded from resolved count — it's a market event
            w["resolved"] += 1
        if ev["predicted_confidence"] is not None:
            w["confidences"].append(ev["predicted_confidence"])
        if ev["outcome_score"]:
            w["outcome_scores"].append(ev["outcome_score"])
        if ev["calibration_error"] is not None:
            w["cal_errors"].append(ev["calibration_error"])
        if ev["overconfidence"] is not None:
            w["overconfs"].append(ev["overconfidence"])
        if ev["underconfidence"] is not None:
            w["underconfs"].append(ev["underconfidence"])
        if ev["r_multiple"] is not None:
            w["r_multiples"].append(ev["r_multiple"])

    results = []
    for agent, w in windows.items():
        resolved = w["resolved"]
        w["accuracy"] = round(w["correct"] / resolved, 4) if resolved > 0 else None
        w["avg_confidence"] = round(sum(w["confidences"]) / len(w["confidences"]), 4) if w["confidences"] else None
        w["calibration_error"] = round(sum(w["cal_errors"]) / len(w["cal_errors"]), 4) if w["cal_errors"] else None
        w["overconfidence_score"] = round(sum(w["overconfs"]) / len(w["overconfs"]), 4) if w["overconfs"] else None
        w["underconfidence_score"] = round(sum(w["underconfs"]) / len(w["underconfs"]), 4) if w["underconfs"] else None
        w["avg_outcome_score"] = round(sum(w["outcome_scores"]) / len(w["outcome_scores"]), 4) if w["outcome_scores"] else None
        w["avg_r_multiple"] = round(sum(w["r_multiples"]) / len(w["r_multiples"]), 4) if w["r_multiples"] else None
        w["low_sample_size"] = resolved < AGENT_SAMPLE_INSIGHT
        if resolved < AGENT_SAMPLE_INSIGHT:
            w["sample_size_status"] = "insight_only"
        elif resolved < AGENT_SAMPLE_SHADOW:
            w["sample_size_status"] = "shadow_only"
        else:
            w["sample_size_status"] = "proposal_allowed"

        relist_note = f", {w.get('relist_neutral', 0)} relist-excluded" if w.get("relist_neutral", 0) > 0 else ""
        w["learning_summary"] = f"{agent}: {resolved} resolved{relist_note}, acc={w['accuracy']}, cal_err={w['calibration_error']}"
        w["recommendation"] = "insufficient_data" if resolved < 10 else (
            "review_overconfidence" if (w["overconfidence_score"] or 0) > 0.3 else "maintain_current")

        # Remove temp lists
        for k in ("confidences", "outcome_scores", "cal_errors", "overconfs", "underconfs", "r_multiples"):
            del w[k]
        results.append(w)

    return results


def save_events(conn, events, dry_run=True):
    if dry_run:
        return
    cur = conn.cursor()
    for ev in events:
        cur.execute("""
            INSERT INTO agent_calibration_events
                (calibration_event_id, recommendation_id, agent_name, symbol, strategy_id,
                 outcome_type, scoring_window, predicted_action, predicted_confidence,
                 actual_outcome, outcome_score, pnl, r_multiple, calibration_error,
                 overconfidence, underconfidence, explanation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (calibration_event_id) DO NOTHING
        """, [ev["calibration_event_id"], ev["recommendation_id"], ev["agent_name"],
              ev["symbol"], ev.get("strategy_id"), ev.get("outcome_type"),
              ev["scoring_window"], ev["predicted_action"], ev.get("predicted_confidence"),
              ev["actual_outcome"], ev["outcome_score"], ev.get("pnl"), ev.get("r_multiple"),
              ev.get("calibration_error"), ev.get("overconfidence"), ev.get("underconfidence"),
              ev["explanation"]])
    conn.commit()


def save_windows(conn, windows, dry_run=True):
    if dry_run:
        return
    cur = conn.cursor()
    for w in windows:
        cur.execute("""
            INSERT INTO agent_calibration_windows
                (window_id, agent_name, window_start, window_end, domain,
                 recommendations, resolved, correct, incorrect, neutral,
                 partially_correct, unresolved, accuracy, avg_confidence,
                 calibration_error, overconfidence_score, underconfidence_score,
                 avg_outcome_score, avg_r_multiple, low_sample_size,
                 sample_size_status, learning_summary, recommendation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (agent_name, window_start, window_end, domain, strategy_id) DO UPDATE SET
                resolved=EXCLUDED.resolved, correct=EXCLUDED.correct, accuracy=EXCLUDED.accuracy,
                calibration_error=EXCLUDED.calibration_error, recommendation=EXCLUDED.recommendation
        """, [w["window_id"], w["agent_name"], w["window_start"], w["window_end"],
              w.get("domain"), w["recommendations"], w["resolved"], w["correct"],
              w["incorrect"], w["neutral"], w["partially_correct"], w["unresolved"],
              w.get("accuracy"), w.get("avg_confidence"), w.get("calibration_error"),
              w.get("overconfidence_score"), w.get("underconfidence_score"),
              w.get("avg_outcome_score"), w.get("avg_r_multiple"),
              w["low_sample_size"], w.get("sample_size_status"),
              w.get("learning_summary"), w.get("recommendation")])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Agent Calibration Engine")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--agent", help="Filter by agent")
    parser.add_argument("--window", default="90d", help="Window (e.g. 30d, 90d)")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    window_days = int(args.window.replace("d", ""))
    conn = _get_conn()
    try:
        events = score_recommendations(conn, agent_filter=args.agent, window_days=window_days)
        windows = aggregate_windows(events, window_days=window_days)

        if not dry_run:
            save_events(conn, events)
            save_windows(conn, windows)

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "calibration_events": len(events),
            "agent_windows": len(windows),
            "window_days": window_days,
            "agents": [{k: v for k, v in w.items() if k != "payload"} for w in windows],
            "low_sample_warning": all(w.get("low_sample_size", True) for w in windows),
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Calibration: {out['calibration_events']} events, {out['agent_windows']} windows ({out['mode']})")
            if out["low_sample_warning"]:
                print("  WARNING: All agents have low sample size")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
