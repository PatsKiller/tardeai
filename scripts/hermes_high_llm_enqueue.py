#!/usr/bin/env python3
"""Hermes High-LLM Enqueue Adapter — routes Hermes high-model requests into global queue.

Usage:
    python scripts/hermes_high_llm_enqueue.py [--apply] [--max-jobs N]
"""
import argparse, hashlib, json, os, sys
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
HERMES_JOB_TYPES = [
    {"job_type":"hermes_librarian_deep_review","urgency":0.6,"portfolio_impact":0.5,"operator_value":0.7,"evidence_gap":0.7,"runtime":400,"pool":"hermes_research"},
    {"job_type":"hermes_source_quality_review","urgency":0.4,"portfolio_impact":0.4,"operator_value":0.6,"evidence_gap":0.6,"runtime":300,"pool":"hermes_research"},
    {"job_type":"hermes_advisory_cache_synthesis","urgency":0.5,"portfolio_impact":0.6,"operator_value":0.7,"evidence_gap":0.5,"runtime":350,"pool":"hermes_research"},
    {"job_type":"hermes_portfolio_reflection","urgency":0.5,"portfolio_impact":0.7,"operator_value":0.6,"evidence_gap":0.5,"runtime":400,"pool":"portfolio_risk"},
    {"job_type":"hermes_research_gap_review","urgency":0.6,"portfolio_impact":0.5,"operator_value":0.6,"evidence_gap":0.8,"runtime":300,"pool":"hermes_research"},
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
    for j in HERMES_JOB_TYPES[:args.max_jobs]:
        dh = hashlib.sha256(f"hermes:{j['job_type']}".encode()).hexdigest()[:16]
        cur.execute("SELECT COUNT(*) FROM high_llm_job_queue WHERE duplicate_hash=%s AND status NOT IN ('completed','failed')", (dh,))
        if cur.fetchone()[0] > 0:
            print(f"  SKIP (duplicate): {j['job_type']}")
            continue
        ps = score(j)
        if args.apply:
            cur.execute("""INSERT INTO high_llm_job_queue (job_type,source_system,preferred_model,urgency,portfolio_impact,
                operator_value,evidence_gap_score,expected_runtime_sec,priority_score,quota_pool,status,duplicate_hash)
                VALUES (%s,'hermes','gemma3:12b',%s,%s,%s,%s,%s,%s,%s,'queued_for_review',%s)""",
                (j["job_type"],j["urgency"],j["portfolio_impact"],j["operator_value"],j["evidence_gap"],j["runtime"],ps,j["pool"],dh))
            inserted += 1
        print(f"  {'[APPLY]' if args.apply else '[DRY]'} {j['job_type']} priority={ps} pool={j['pool']}")

    if args.apply:
        conn.commit()
    cur.close(); conn.close()
    print(f"\n{'Applied' if args.apply else 'Dry-run'}: {inserted} Hermes jobs enqueued")

if __name__ == "__main__":
    main()
