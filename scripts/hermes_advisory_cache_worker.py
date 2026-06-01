#!/usr/bin/env python3
"""Hermes Advisory Cache Worker — refreshes llm_intelligence_cache from events.

Usage:
    python scripts/hermes_advisory_cache_worker.py [--apply] [--max-events N]

Default: dry-run. --apply updates cache and marks events processed.

Safety:
    - Writes only to llm_intelligence_cache (hermes_* sections)
    - Writes only to hermes_advisory_events (status updates)
    - No proposals/trades/journal/holdings/broker
    - No embeddings, no promotions
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
MAX_EVENTS = 5
MAX_SECTIONS = 10

def get_db():
    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS)
    args = parser.parse_args()
    dry = not args.apply

    conn = get_db()
    cur = conn.cursor()

    # Check current hermes cache section count
    cur.execute("SELECT COUNT(*) FROM llm_intelligence_cache WHERE section LIKE 'hermes_%'")
    current_sections = cur.fetchone()[0]

    # Read pending events for promoted/staged research
    cur.execute("""
        SELECT e.id, e.event_type, e.source_table, e.source_id, e.created_at
        FROM hermes_advisory_events e
        WHERE e.event_status = 'pending'
        ORDER BY e.created_at
        LIMIT %s
    """, (args.max_events,))
    events = cur.fetchall()

    processed = 0
    for eid, etype, stbl, sid, cat in events:
        now = datetime.now(timezone.utc)
        lat = int((now - cat.replace(tzinfo=timezone.utc if cat.tzinfo is None else cat.tzinfo)).total_seconds() * 1000)

        # Read source row
        cur.execute("SELECT symbol, research_type, topic, summary, thesis, confidence_score, status FROM hermes_research_intelligence WHERE id=%s", (sid,))
        row = cur.fetchone()
        if not row:
            print(f"  event={eid}: source id={sid} not found — skipping")
            if not dry:
                cur.execute("UPDATE hermes_advisory_events SET event_status='skipped', processed_at=NOW(), latency_ms=%s WHERE id=%s", (lat, eid))
                conn.commit()
            continue

        sym, rtype, topic, summary, thesis, conf, status = row
        section = f"hermes_{rtype}_{sym or 'SYSTEM'}"

        # Only refresh if already promoted OR if this is a high-quality staged row
        if status != 'promoted' and (conf or 0) < 0.45:
            print(f"  event={eid}: id={sid} not promoted and low conf — skipping")
            if not dry:
                cur.execute("UPDATE hermes_advisory_events SET event_status='skipped', processed_at=NOW(), latency_ms=%s WHERE id=%s", (lat, eid))
                conn.commit()
            continue

        # Check section cap
        if current_sections >= MAX_SECTIONS and section not in []:
            cur.execute("SELECT 1 FROM llm_intelligence_cache WHERE section=%s", (section,))
            if not cur.fetchone():
                print(f"  event={eid}: section cap {MAX_SECTIONS} reached, new section {section} — skipping")
                if not dry:
                    cur.execute("UPDATE hermes_advisory_events SET event_status='skipped', processed_at=NOW(), latency_ms=%s WHERE id=%s", (lat, eid))
                    conn.commit()
                continue

        content = f"HERMES ADVISORY — {sym or 'SYSTEM'} ({rtype.replace('_',' ')})\n\n{summary}\n\n{thesis or ''}\n\nConfidence: {conf} | Advisory Only"
        metadata = json.dumps({"source":"hermes","hermes_row_id":sid,"research_type":rtype,"confidence_score":conf,"advisory_only":True,"refreshed_by":"cache_worker"})

        print(f"  {'[DRY]' if dry else '[APPLY]'} event={eid} → {section} latency={lat}ms")

        if not dry:
            cur.execute("""
                INSERT INTO llm_intelligence_cache (section, content, metadata, generated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (section) DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata, generated_at=NOW()
            """, (section, content[:2000], metadata))
            cur.execute("UPDATE hermes_advisory_events SET event_status='completed', processed_at=NOW(), latency_ms=%s WHERE id=%s", (lat, eid))
            conn.commit()
            processed += 1

    cur.close(); conn.close()
    print(f"\n{'DRY-RUN' if dry else 'APPLY'}: {len(events)} events, {processed} cache sections refreshed")

if __name__ == "__main__":
    main()
