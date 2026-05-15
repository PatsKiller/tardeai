#!/usr/bin/env python3
"""collect_phase5_feedback_observations.py — Collect read-only feedback observations from model outputs/outcomes."""
import argparse, json, hashlib, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase5-collect] {msg}", flush=True)

SOURCES = [
    {"table": "deep_overnight_llm_results", "workflow": "deep_overnight",
     "model_role": "DEEP", "model_field": "model", "output_field": "summary",
     "id_field": "id", "date_field": "created_at", "symbol_field": "symbol"},
    {"table": "decision_outcomes", "workflow": "cio_decision",
     "model_role": "STANDARD", "model_field": None, "output_field": "outcome_notes",
     "id_field": "id", "date_field": "created_at", "symbol_field": "symbol"},
    {"table": "journal_trade_reviews", "workflow": "trade_review",
     "model_role": "STANDARD", "model_field": None, "output_field": "review_text",
     "id_field": "id", "date_field": "created_at", "symbol_field": "symbol"},
    {"table": "watchlist_agent_results", "workflow": "watchlist_agent",
     "model_role": "STANDARD", "model_field": None, "output_field": "summary",
     "id_field": "id", "date_field": "created_at", "symbol_field": "symbol"},
]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if not args.dry_run and not args.apply:
        args.dry_run = True

    conn = get_conn()
    cur = conn.cursor()
    observations = []
    total_seen = 0

    for src in SOURCES:
        try:
            cur.execute(f"SELECT {src['id_field']}, {src.get('symbol_field','NULL')}, "
                        f"{src.get('output_field','NULL')}, {src.get('model_field') or 'NULL'}, "
                        f"{src['date_field']} "
                        f"FROM {src['table']} WHERE {src['date_field']} > NOW() - INTERVAL '{args.since_days} days' "
                        f"ORDER BY {src['date_field']} DESC LIMIT {args.limit}")
            rows = cur.fetchall()
            total_seen += len(rows)

            for row in rows:
                rid, sym, output, model, dt = row
                output_str = str(output or "")[:500]
                obs = {
                    "source_table": src["table"], "source_id": str(rid),
                    "workflow": src["workflow"], "symbol": sym,
                    "model_role": src["model_role"], "model_name": model or "unknown",
                    "output_hash": hashlib.sha256(output_str.encode()).hexdigest()[:16] if output_str else None,
                    "observation_date": dt.strftime("%Y-%m-%d") if dt else None,
                    "quality_score": None, "safety_score": None,
                }
                observations.append(obs)

            if args.verbose:
                log(f"  {src['table']}: {len(rows)} rows")
        except Exception as e:
            if args.verbose:
                log(f"  {src['table']}: SKIP ({e})")

    log(f"Total observations: {len(observations)} from {total_seen} source rows")

    if args.apply and observations:
        inserted = 0
        for obs in observations:
            try:
                cur.execute("""INSERT INTO llm_feedback_observations
                    (observation_date, source_table, source_id, workflow, symbol,
                     model_role, model_name, output_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    [obs.get("observation_date"), obs["source_table"], obs["source_id"],
                     obs["workflow"], obs.get("symbol"), obs["model_role"],
                     obs.get("model_name"), obs.get("output_hash")])
                inserted += cur.rowcount
            except Exception:
                conn.rollback()
        conn.commit()
        log(f"Inserted: {inserted}")

    report = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "mode": "dry_run" if args.dry_run else "applied",
              "sources": len(SOURCES), "total_seen": total_seen,
              "observations": len(observations)}

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).write_text(
            f"# Phase 5 Observation Collection\n\n**Mode:** {report['mode']}\n"
            f"**Sources:** {report['sources']}\n**Observations:** {report['observations']}\n")

    conn.close()

if __name__ == "__main__":
    main()
