#!/usr/bin/env python3
"""backup_verify.py — Verify backup integrity.

Checks:
  1. pg_dump backup exists and is recent
  2. Backup file is non-trivial size
  3. Key state files exist and are fresh
  4. Reports findings via Telegram

Schedule: Monthly (1st of month) or on-demand.

Usage:
    .venv/bin/python scripts/backup_verify.py
    .venv/bin/python scripts/backup_verify.py --dry-run
"""
import argparse
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def verify_db_backup():
    """Check that a recent pg_dump backup exists."""
    backup_dir = PROJECT_ROOT / "backups" / "db"
    if not backup_dir.exists():
        # Try alternate locations
        for alt in [Path("/backups/db"), PROJECT_ROOT / "backups"]:
            if alt.exists():
                backup_dir = alt
                break

    findings = []

    if not backup_dir.exists():
        findings.append({"check": "backup_dir", "status": "FAIL", "detail": f"Backup directory not found: {backup_dir}"})
        return findings

    # Find most recent .sql.gz or .sql backup
    backups = sorted(
        [f for f in backup_dir.glob("*.sql*") if f.stat().st_size > 1000],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if not backups:
        findings.append({"check": "backup_exists", "status": "FAIL", "detail": "No .sql backup files found"})
        return findings

    latest = backups[0]
    age_days = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).days
    size_mb = latest.stat().st_size / (1024 * 1024)

    findings.append({
        "check": "backup_exists",
        "status": "OK" if age_days <= 7 else "WARN",
        "detail": f"Latest: {latest.name}, {size_mb:.1f} MB, {age_days} days old"
    })

    if age_days > 7:
        findings.append({"check": "backup_age", "status": "WARN", "detail": f"Backup is {age_days} days old (>7 day threshold)"})

    if size_mb < 1:
        findings.append({"check": "backup_size", "status": "WARN", "detail": f"Backup is only {size_mb:.1f} MB — may be truncated"})

    return findings


def verify_state_files():
    """Check that key state files exist and are fresh."""
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    critical_files = [
        "holdings.json",
        "risk_management.json",
        "technical_snapshot.json",
        "dividend_calendar.json",
        "_freshness.json",
    ]

    findings = []
    for fname in critical_files:
        fpath = state_dir / fname
        if not fpath.exists():
            findings.append({"check": f"state_{fname}", "status": "FAIL", "detail": f"Missing: {fname}"})
            continue
        age_hours = (datetime.now() - datetime.fromtimestamp(fpath.stat().st_mtime)).total_seconds() / 3600
        size_kb = fpath.stat().st_size / 1024
        status = "OK" if age_hours < 24 else ("WARN" if age_hours < 72 else "FAIL")
        findings.append({
            "check": f"state_{fname}",
            "status": status,
            "detail": f"{fname}: {size_kb:.0f} KB, {age_hours:.0f}h old"
        })

    return findings


def verify_db_connectivity():
    """Check database is accessible and has expected tables."""
    findings = []
    try:
        import psycopg2
        pw = os.getenv("DB_PASSWORD", "")
        conn = psycopg2.connect(host="127.0.0.1", port=5432, dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
        table_count = cur.fetchone()[0]
        findings.append({"check": "db_tables", "status": "OK", "detail": f"{table_count} tables"})

        # Check key tables have data
        for table, min_rows in [("trade_ai_scans", 10), ("paper_trade_proposals", 1), ("notification_log", 1)]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            rows = cur.fetchone()[0]
            status = "OK" if rows >= min_rows else "WARN"
            findings.append({"check": f"db_{table}", "status": status, "detail": f"{rows} rows"})

        conn.close()
    except Exception as e:
        findings.append({"check": "db_connect", "status": "FAIL", "detail": str(e)})

    return findings


def main():
    parser = argparse.ArgumentParser(description="Backup Verification")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[backup_verify] Starting — {datetime.now().isoformat()}")

    all_findings = []
    all_findings.extend(verify_db_backup())
    all_findings.extend(verify_state_files())
    all_findings.extend(verify_db_connectivity())

    ok = sum(1 for f in all_findings if f["status"] == "OK")
    warn = sum(1 for f in all_findings if f["status"] == "WARN")
    fail = sum(1 for f in all_findings if f["status"] == "FAIL")

    print(f"  Results: {ok} OK, {warn} WARN, {fail} FAIL")
    for f in all_findings:
        icon = {"OK": "+", "WARN": "!", "FAIL": "X"}[f["status"]]
        print(f"  [{icon}] {f['check']}: {f['detail']}")

    # Send Telegram summary
    if not args.dry_run:
        try:
            from alert_dispatcher import dispatch_alert
            severity = "URGENT" if fail > 0 else ("ALERT" if warn > 0 else "INFO")
            body_lines = [f"*Backup Verification Report*", f"OK: {ok} | WARN: {warn} | FAIL: {fail}", ""]
            for f in all_findings:
                icon = {"OK": "OK", "WARN": "!!", "FAIL": "XX"}[f["status"]]
                body_lines.append(f"[{icon}] {f['check']}: {f['detail']}")
            dispatch_alert(
                alert_type="backup_verification",
                title=f"Backup Verify: {ok} OK, {warn} WARN, {fail} FAIL",
                body="\n".join(body_lines),
                tier=severity,
                source="backup_verify",
                dedupe_scope="global",
            )
        except Exception as e:
            print(f"  Alert dispatch failed: {e}")

    print(f"[backup_verify] Complete — {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
