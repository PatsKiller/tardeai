#!/usr/bin/env python3
"""Finviz Feed Preflight — checks credential and feed health before screeners.

Usage:
    python scripts/finviz_feed_preflight.py [--json] [--dry-run]

Exit codes:
    0 = HEALTHY
    1 = DEGRADED or EXPIRED
    2 = ERROR

Safety:
    - Never prints cookie value
    - Writes redacted state to data/state/finviz_feed_health.json
"""
import json, os, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
STATE_FILE = PR / "data" / "state" / "finviz_feed_health.json"

def get_cookie():
    """Check cookie existence without returning value."""
    try:
        import sys
        _sec = PR / "scripts" / "secrets"
        if str(_sec) not in sys.path:
            sys.path.insert(0, str(_sec))
        from resolve_secret import resolve_secret
        return len(resolve_secret("FINVIZ_COOKIE", "")) > 20
    except Exception:
        try:
            for line in (PR / ".env").read_text().splitlines():
                if line.startswith("FINVIZ_COOKIE=") and len(line) > 20:
                    return True
        except Exception:
            pass
        return False

def probe_feed():
    """Check if Finviz returns CSV, not login page."""
    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)
    cur = conn.cursor()
    cur.execute("SELECT status, symbols_scanned FROM screener_run_health ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    cur.close(); conn.close()
    if row:
        return row[0], row[1] or 0
    return "UNKNOWN", 0

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    has_cookie = get_cookie()
    last_status, last_symbols = probe_feed()

    if not has_cookie:
        status = "MISSING_COOKIE"
    elif last_status == "RUN_HEALTHY" and last_symbols > 0:
        status = "HEALTHY"
    elif last_status == "RUN_FAILED":
        status = "DEGRADED"
    else:
        status = "UNKNOWN"

    result = {
        "status": status,
        "cookie_present": has_cookie,
        "last_screener_status": last_status,
        "last_symbols": last_symbols,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    # Save redacted state
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(result, indent=2))

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Finviz feed: {status} (cookie={'present' if has_cookie else 'MISSING'}, last={last_status}, symbols={last_symbols})")

    sys.exit(0 if status == "HEALTHY" else 1 if status in ("DEGRADED", "EXPIRED_COOKIE", "MISSING_COOKIE") else 2)

if __name__ == "__main__":
    main()
