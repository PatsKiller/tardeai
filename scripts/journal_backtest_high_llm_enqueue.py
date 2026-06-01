#!/usr/bin/env python3
"""Journal/Backtest High-LLM Enqueue — routes learning jobs into global queue.

Reads safe views only. No journal/backtest mutation. No model calls.
"""
import argparse, hashlib, json, os, sys
from pathlib import Path

PR = Path(__file__).resolve().parent.parent

JB_JOBS = [
    {"job_type":"journal_trade_lesson_deep_review","urgency":0.7,"portfolio_impact":0.7,"operator_value":0.8,"evidence_gap":0.9,"runtime":500,"pool":"journal_backtest"},
    {"job_type":"backtest_strategy_contradiction_review","urgency":0.8,"portfolio_impact":0.9,"operator_value":0.9,"evidence_gap":0.8,"runtime":600,"pool":"journal_backtest"},
    {"job_type":"rejected_proposal_replay_review","urgency":0.5,"portfolio_impact":0.6,"operator_value":0.7,"evidence_gap":0.7,"runtime":400,"pool":"journal_backtest"},
    {"job_type":"strategy_underperformance_deep_review","urgency":0.7,"portfolio_impact":0.8,"operator_value":0.8,"evidence_gap":0.7,"runtime":500,"pool":"journal_backtest"},
    {"job_type":"failed_setup_pattern_review","urgency":0.5,"portfolio_impact":0.5,"operator_value":0.6,"evidence_gap":0.6,"runtime":300,"pool":"journal_backtest"},
]

def score(j):
    return round(3.0*j["urgency"]+2.5*j["portfolio_impact"]+2.0*j["evidence_gap"]+1.5*j["operator_value"], 2)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=5)
    args = parser.parse_args()

    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)
    cur = conn.cursor()

    inserted = 0
    for j in JB_JOBS[:args.max_jobs]:
        dh = hashlib.sha256(f"journal_backtest:{j['job_type']}".encode()).hexdigest()[:16]
        cur.execute("SELECT COUNT(*) FROM high_llm_job_queue WHERE duplicate_hash=%s AND status NOT IN ('completed','failed')", (dh,))
        if cur.fetchone()[0] > 0:
            continue
        ps = score(j)
        if args.apply:
            cur.execute("""INSERT INTO high_llm_job_queue (job_type,source_system,preferred_model,urgency,portfolio_impact,
                operator_value,evidence_gap_score,expected_runtime_sec,priority_score,quota_pool,status,duplicate_hash)
                VALUES (%s,'tradeai_learning','gemma3:12b',%s,%s,%s,%s,%s,%s,%s,'queued_for_review',%s)""",
                (j["job_type"],j["urgency"],j["portfolio_impact"],j["operator_value"],j["evidence_gap"],j["runtime"],ps,j["pool"],dh))
            inserted += 1
        print(f"  {'[APPLY]' if args.apply else '[DRY]'} {j['job_type']} priority={ps}")

    if args.apply: conn.commit()
    cur.close(); conn.close()
    print(f"\n{'Applied' if args.apply else 'Dry-run'}: {inserted} journal/backtest jobs enqueued")

if __name__ == "__main__":
    main()
