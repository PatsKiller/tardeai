#!/usr/bin/env python3
"""Hermes Advisory Event Enqueue — manual event insert.

Usage:
    python scripts/hermes_advisory_event_enqueue.py --source-table hermes_research_intelligence --source-id 12 --event-type research_staged
"""
import argparse, hashlib, json, os, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--event-type", default="research_staged")
    parser.add_argument("--priority", default="normal")
    args = parser.parse_args()

    import psycopg2
    pr = Path(__file__).resolve().parent.parent
    db_pass = [l.split("=",1)[1] for l in (pr/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)
    cur = conn.cursor()

    ph = hashlib.sha256(f"{args.source_table}:{args.source_id}:{args.event_type}".encode()).hexdigest()[:16]
    cur.execute("""
        INSERT INTO hermes_advisory_events (event_type, source_table, source_id, priority, payload_hash, advisory_only, not_execution)
        VALUES (%s, %s, %s, %s, %s, true, true) RETURNING id
    """, (args.event_type, args.source_table, args.source_id, args.priority, ph))
    eid = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    print(f"Enqueued event id={eid}: {args.event_type} for {args.source_table} id={args.source_id}")

if __name__ == "__main__":
    main()
