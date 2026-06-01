#!/usr/bin/env python3
"""Alert False-Fixed Verification Gate — prevents premature "fixed" status.

Usage:
    python scripts/alert_false_fixed_gate.py --alert-type credential_expired --component finviz [--apply]
"""
import argparse, json, os, sys
from pathlib import Path

PR = Path(__file__).resolve().parent.parent

def check_finviz_recovery():
    """Check if Finviz is actually recovered (CSV success)."""
    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)
    cur = conn.cursor()
    cur.execute("SELECT status, symbols_scanned FROM screener_run_health ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    cur.close(); conn.close()
    if row and row[0] == 'RUN_HEALTHY' and (row[1] or 0) > 0:
        return True, f"Last run HEALTHY, {row[1]} symbols"
    return False, f"Last run {row[0] if row else 'UNKNOWN'}, {row[1] if row else 0} symbols"

def check_agent_freshness(agent_name):
    """Check if agent output is actually fresh."""
    # Would check agent_runs or output file timestamps
    return False, "Agent freshness check not yet implemented for this agent"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert-type", required=True)
    parser.add_argument("--component", required=True)
    args = parser.parse_args()

    if args.alert_type == "credential_expired" and args.component == "finviz":
        recovered, detail = check_finviz_recovery()
    elif args.alert_type == "agent_stale":
        recovered, detail = check_agent_freshness(args.component)
    else:
        recovered, detail = False, "Unknown alert type"

    if recovered:
        print(f"VERIFIED_FIXED: {args.alert_type}:{args.component} — {detail}")
    else:
        print(f"NOT_FIXED: {args.alert_type}:{args.component} — {detail}")
        print("  → 'analyzed' is NOT 'fixed'. Do not suppress alert.")

if __name__ == "__main__":
    main()
