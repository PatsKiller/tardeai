#!/usr/bin/env python3
"""
check_file_integrity.py — Integrity Verification Step in the Health Inspection Pipeline.

Pipeline order:
  1. RuntimeAwareness discovers what the live server IS reading
  2. THIS SCRIPT verifies the canonical file at the expected path matches expected hash
  3. If server is reading a NON-CANONICAL path: P0 alert "Server reading stale file"
  4. If hash mismatch on canonical path: P0 alert "Canonical file corrupted"
  5. Only proceed with other health checks if integrity passes

Usage:
    python scripts/check_file_integrity.py              # Full check
    python scripts/check_file_integrity.py --json       # Machine-readable output
    python scripts/check_file_integrity.py --summary    # Human-readable summary only
    python scripts/check_file_integrity.py --stale-copies-only  # Only scan for stale copies
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.file_integrity import FileIntegrity
from lib.runtime_awareness import RuntimeAwareness


def _fmt_alert(alert: dict, idx: int | None = None) -> str:
    """Format a single alert for human-readable output."""
    sev_icon = {"P0": "🚨", "P1": "⚠️", "P2": "ℹ️"}.get(alert.get("severity", ""), "•")
    prefix = f"  {idx}." if idx is not None else "  "
    lines = [f"{prefix} {sev_icon} [{alert.get('severity', '?')}] {alert.get('message', '')}"]
    if alert.get("action"):
        lines.append(f"     Action: {alert['action']}")
    return "\n".join(lines)


def print_human_report(integrity: FileIntegrity, canonical_results: dict,
                        server_cross_check: dict, stale_copies: list[dict]) -> int:
    """Print a comprehensive human-readable report. Returns exit code (0=healthy, 1=warning, 2=critical)."""
    print("=" * 72)
    print("  TRADE AI FILE INTEGRITY REPORT")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Manifest version: {canonical_results.get('manifest_version')}")
    print("=" * 72)

    # ── Section 1: Runtime Awareness (what the server is reading) ─────────
    print(f"\n{'─' * 72}")
    print("  STEP 1: RUNTIME AWARENESS — What is the live server reading?")
    print(f"{'─' * 72}")

    ra = RuntimeAwareness()
    ra.discover()
    print(ra.report())
    print()

    # ── Section 2: Canonical file integrity ──────────────────────────────
    print(f"{'─' * 72}")
    print("  STEP 2: CANONICAL FILE INTEGRITY — Hash verification")
    print(f"{'─' * 72}")

    for file_key, fr in canonical_results.get("files", {}).items():
        status = fr["status"]
        icon = {"OK": "✅", "STALE": "🟡", "HASH_MISMATCH": "🔴", "SIZE_MISMATCH": "🔴",
                "MISSING": "❌", "UNREADABLE": "❌", "UNKNOWN_FILE": "❓"}.get(status, "❓")
        print(f"  {icon} {file_key}: {status}")
        print(f"     Canonical: {fr['canonical_path']}")
        if fr.get("actual_hash"):
            match_str = "MATCH" if fr.get("hash_match") else "MISMATCH"
            print(f"     Hash: {match_str} (expected {fr['expected_hash'][:16]}..., got {fr['actual_hash'][:16]}...)")
        if fr.get("age_minutes") is not None:
            stale_str = "STALE" if fr.get("stale") else "fresh"
            print(f"     Age: {fr['age_minutes']}m (max {fr.get('max_age_minutes')}m) — {stale_str}")
        for i, alert in enumerate(fr.get("alerts", []), 1):
            print(_fmt_alert(alert, i))

    print(f"\n  Canonical files: {canonical_results['ok']}/{canonical_results['total_files']} OK")
    if canonical_results['stale']:
        print(f"  Stale (hash OK): {canonical_results['stale']}")

    # ── Section 3: Server cross-check ────────────────────────────────────
    print(f"\n{'─' * 72}")
    print("  STEP 3: SERVER CROSS-CHECK — Is the server reading canonical files?")
    print(f"{'─' * 72}")

    if server_cross_check.get("status") == "NO_SERVER_FOUND":
        print("  ℹ️ No live server found on port 7777 — skipping cross-check.")
    else:
        print(f"  Server PID: {server_cross_check.get('server_pid')}")
        print(f"  Server dir: {server_cross_check.get('server_dir')}")

        mismatches = 0
        for file_key, fr in server_cross_check.get("files", {}).items():
            if not fr.get("server_reads_canonical"):
                mismatches += 1
                if fr.get("server_hash_matches_canonical"):
                    print(f"  🔴 {file_key}: Server reads {fr['server_path']}")
                    print(f"     Content MATCHES canonical — path differs (old release directory)")
                else:
                    print(f"  🚨 {file_key}: Server reads {fr['server_path']}")
                    print(f"     Content DIFFERS from canonical — server is STALE/CORRUPT")
            for alert in fr.get("alerts", []):
                print(_fmt_alert(alert))

        if mismatches == 0:
            print("  ✅ Server is reading canonical files for all critical state.")

    # ── Section 4: Stale copy scan ───────────────────────────────────────
    print(f"\n{'─' * 72}")
    print("  STEP 4: STALE COPY DETECTION — Extra copies on disk")
    print(f"{'─' * 72}")

    if not stale_copies:
        print("  ✅ No stale extra copies found outside canonical paths.")
    else:
        print(f"  ⚠️ Found {len(stale_copies)} stale/extra copy(ies):")
        for sc in stale_copies:
            print(f"  🟡 {sc['basename']}: {sc['stale_copy_path']}")
            print(f"     Canonical: {sc['canonical_path']}")
            print(f"     Severity: {sc['severity']}")
            print(f"     {sc['message']}")
            print()

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"{'─' * 72}")
    print("  SUMMARY")

    total_p0 = canonical_results.get("p0_alerts", 0) + sum(
        1 for a in server_cross_check.get("alerts", []) if a.get("severity") == "P0"
    )
    total_p1 = canonical_results.get("p1_alerts", 0) + len(stale_copies) + sum(
        1 for a in server_cross_check.get("alerts", []) if a.get("severity") == "P1"
    )

    print(f"  P0 alerts: {total_p0}")
    print(f"  P1 alerts: {total_p1}")
    print(f"  Stale extra copies: {len(stale_copies)}")

    if total_p0 > 0:
        print(f"\n  🚨 CRITICAL: {total_p0} P0 integrity violation(s) detected.")
        print("  → DO NOT proceed with automated patching. Investigate first.")
        print(f"{'─' * 72}")
        return 2
    elif total_p1 > 0:
        print(f"\n  ⚠️ WARNING: {total_p1} P1 anomaly(ies) detected.")
        print(f"{'─' * 72}")
        return 1
    else:
        print(f"\n  ✅ HEALTHY: All files pass integrity verification.")
        print(f"{'─' * 72}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="File Integrity Verification for Trade AI")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--summary", action="store_true", help="Human-readable summary only")
    parser.add_argument("--stale-copies-only", action="store_true",
                        help="Only scan for stale copies on disk")
    parser.add_argument("--canonical-only", action="store_true",
                        help="Only verify canonical files (skip server cross-check)")
    parser.add_argument("--cross-check-only", action="store_true",
                        help="Only cross-check server reading vs canonical")
    args = parser.parse_args()

    integrity = FileIntegrity(PROJECT_ROOT)

    # ── Step 1: Runtime awareness ────────────────────────────────────────────
    ra = RuntimeAwareness()
    ra.discover()

    # ── Step 2: Canonical file integrity ─────────────────────────────────────
    canonical_results = integrity.verify_all()

    # ── Step 3: Server cross-check ───────────────────────────────────────────
    server_cross_check: dict = {}
    if not args.canonical_only:
        server_cross_check = integrity.cross_check_server_reading()

    # ── Step 4: Stale copy scan ──────────────────────────────────────────────
    stale_copies: list[dict] = []
    if not args.cross_check_only:
        stale_copies = integrity.scan_stale_copies()

    if args.stale_copies_only:
        print(json.dumps(stale_copies, indent=2, default=str))
        return 1 if stale_copies else 0

    if args.json:
        output = {
            "runtime_awareness": ra._findings,
            "canonical_integrity": canonical_results,
            "server_cross_check": server_cross_check,
            "stale_copies": stale_copies,
        }
        print(json.dumps(output, indent=2, default=str))
        return 0

    exit_code = print_human_report(integrity, canonical_results, server_cross_check, stale_copies)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
