#!/usr/bin/env python3
"""champion_challenger.py — Shadow-mode experiments for learning recommendations.

Compares champion (current) vs challenger (proposed) rules in shadow mode.
No active config changes. No broker actions. No auto-promotion.

Usage:
    .venv/bin/python scripts/champion_challenger.py --list --json
    .venv/bin/python scripts/champion_challenger.py --create-from-recommendation REC_ID --dry-run --json
    .venv/bin/python scripts/champion_challenger.py --run EXP_ID --dry-run --json
    .venv/bin/python scripts/champion_challenger.py --summarize EXP_ID --json
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def list_experiments(conn):
    """List all experiments."""
    cur = conn.cursor()
    cur.execute("""
        SELECT experiment_id, hypothesis_id, name, domain, experiment_type,
               status, actual_sample_size, min_sample_size, conclusion, created_at
        FROM learning_experiments ORDER BY created_at DESC LIMIT 20
    """)
    return [{"experiment_id": r[0], "hypothesis_id": r[1], "name": r[2],
             "domain": r[3], "type": r[4], "status": r[5],
             "sample": r[6], "min_sample": r[7], "conclusion": r[8],
             "created_at": str(r[9])}
            for r in cur.fetchall()]


def create_from_recommendation(conn, rec_id, dry_run=True):
    """Create a shadow experiment from a learning recommendation."""
    from learning_governance import create_experiment

    cur = conn.cursor()
    cur.execute("""
        SELECT recommendation_id, hypothesis_id, domain, recommendation_type,
               title, summary, sample_size
        FROM learning_recommendations WHERE recommendation_id=%s
    """, [rec_id])
    rec = cur.fetchone()
    if not rec:
        return {"error": f"Recommendation {rec_id} not found"}

    result = {
        "recommendation_id": rec[0],
        "hypothesis_id": rec[1],
        "domain": rec[2],
        "type": rec[3],
        "title": rec[4],
        "experiment_name": f"Shadow: {rec[4][:80]}",
    }

    if not dry_run:
        xid = create_experiment(conn, rec[1], result["experiment_name"],
                                rec[2], "paper_shadow",
                                champion_config={"current": "active_config"},
                                challenger_config={"proposed": rec[5]})
        result["experiment_id"] = xid
        result["status"] = "created"
    else:
        result["status"] = "dry_run"

    return result


def run_experiment(conn, exp_id, dry_run=True):
    """Run/update a shadow experiment with current data."""
    from learning_governance import update_experiment_metrics

    cur = conn.cursor()
    cur.execute("""
        SELECT experiment_id, hypothesis_id, domain, experiment_type,
               champion_config, challenger_config, min_sample_size, status
        FROM learning_experiments WHERE experiment_id=%s
    """, [exp_id])
    exp = cur.fetchone()
    if not exp:
        return {"error": f"Experiment {exp_id} not found"}

    # Gather current metrics based on domain
    domain = exp[2]
    metrics = {"domain": domain, "evaluated_at": str(datetime.now(timezone.utc))}

    if domain == "strategy":
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE status='closed') as closed,
                   COUNT(*) FILTER (WHERE pnl > 0) as wins,
                   AVG(r_multiple) FILTER (WHERE status='closed') as avg_r
            FROM paper_trades
        """)
        row = cur.fetchone()
        metrics["closed_trades"] = row[0]
        metrics["wins"] = row[1]
        metrics["avg_r"] = _f(row[2])
        sample = row[0]
    elif domain == "ingestion":
        cur.execute("SELECT COUNT(*) FROM trade_ai_scans WHERE scanned_at > now() - interval '30 days'")
        sample = cur.fetchone()[0]
        metrics["recent_scans"] = sample
    else:
        sample = 0
        metrics["note"] = "generic experiment — manual evaluation needed"

    conclusion = None
    action = None
    if sample >= (exp[6] or 30):
        conclusion = "sufficient_sample_collected"
        action = "review_for_promotion"
    elif exp[7] == "running":
        conclusion = None
        action = "continue_collecting"

    if not dry_run:
        update_experiment_metrics(conn, exp_id, metrics, sample,
                                  conclusion=conclusion, recommended_action=action)

    return {
        "experiment_id": exp_id,
        "domain": domain,
        "sample": sample,
        "min_sample": exp[6],
        "sufficient": sample >= (exp[6] or 30),
        "metrics": metrics,
        "conclusion": conclusion,
        "action": action,
        "mode": "dry_run" if dry_run else "applied",
    }


def summarize_experiment(conn, exp_id):
    """Get full experiment summary."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM learning_experiments WHERE experiment_id=%s", [exp_id])
    row = cur.fetchone()
    if not row:
        return {"error": f"Experiment {exp_id} not found"}
    cols = [d[0] for d in cur.description]
    result = {c: str(v) if v is not None else None for c, v in zip(cols, row)}
    return result


def main():
    parser = argparse.ArgumentParser(description="Champion/Challenger Shadow Experiments")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--create-from-recommendation", dest="create_rec")
    parser.add_argument("--run", dest="run_exp")
    parser.add_argument("--summarize", dest="summarize_exp")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = _get_conn()
    try:
        if args.list:
            exps = list_experiments(conn)
            if args.json:
                print(json.dumps(exps, indent=2, default=str))
            else:
                if not exps:
                    print("No experiments yet.")
                for e in exps:
                    print(f"  {e['experiment_id']}: {e['name']} [{e['status']}] "
                          f"sample={e['sample']}/{e['min_sample']}")

        if args.create_rec:
            result = create_from_recommendation(conn, args.create_rec, dry_run=args.dry_run)
            print(json.dumps(result, indent=2, default=str) if args.json else str(result))

        if args.run_exp:
            result = run_experiment(conn, args.run_exp, dry_run=args.dry_run)
            print(json.dumps(result, indent=2, default=str) if args.json else str(result))

        if args.summarize_exp:
            result = summarize_experiment(conn, args.summarize_exp)
            print(json.dumps(result, indent=2, default=str) if args.json else str(result))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
