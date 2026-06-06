#!/usr/bin/env python3
"""Phase 206 — Journal field completeness validator (read-only).

Reports field completeness over closed paper trades for the fields the v3 Journal crawler
flagged (post_analyzed, close_reason, broker_id, catalyst, MFE/MAE). Use before and after
backfill_journal_trade_fields.py to show before/after. READ-ONLY — no writes.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIELDS = {
    "post_analyzed": "count(*) FILTER (WHERE post_trade_analyzed)",
    "close_reason": "count(close_reason)",
    "broker_id": "count(coalesce(broker, execution_broker, broker_order_id::text))",
    "catalyst": "count(catalyst_at_entry)",
    "mfe": "count(max_favorable_excursion)",
    "mae": "count(max_adverse_excursion)",
}


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def run(json_path):
    load_env()
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT count(*) FROM paper_trades WHERE status='closed'")
    n = cur.fetchone()[0]
    cur.execute(f"SELECT {', '.join(FIELDS.values())} FROM paper_trades WHERE status='closed'")
    vals = cur.fetchone()
    conn.close()
    out = {}
    for (name, _), v in zip(FIELDS.items(), vals):
        out[name] = {"filled": v, "total": n, "pct": round(100 * v / n, 1) if n else 0.0}
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "closed_trades": n, "completeness": out}
    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    run(a.json)
