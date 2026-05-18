#!/usr/bin/env python3
"""report_existing_offsite_backup_target.py — Detect GOG/Drive offsite path.

Read-only. No secrets exposed. No backup files written.

Usage:
    .venv/bin/python scripts/report_existing_offsite_backup_target.py --verbose
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="Offsite backup target discovery (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "candidates": [], "selected": None,
              "safe_to_use": False, "blockers": [], "warnings": []}

    # Check GOG
    try:
        gog_path = subprocess.check_output("which gog", shell=True, stderr=subprocess.DEVNULL).decode().strip()
        report["candidates"].append({"type": "gog_drive", "path": gog_path, "status": "installed"})
    except Exception:
        report["blockers"].append("gog not found")

    # Check GPG
    try:
        gpg_path = subprocess.check_output("which gpg", shell=True, stderr=subprocess.DEVNULL).decode().strip()
        gpg_ver = subprocess.check_output("gpg --version", shell=True, stderr=subprocess.DEVNULL).decode().splitlines()[0]
        report["encryption"] = {"tool": "gpg", "path": gpg_path, "version": gpg_ver}
    except Exception:
        report["blockers"].append("gpg not found")

    # Check GOG Drive access
    try:
        kp = Path("/home/johnclaw/.openclaw/credentials/gog_keyring_password")
        if kp.exists():
            import os
            os.environ["GOG_KEYRING_PASSWORD"] = kp.read_text().strip()
            result = subprocess.check_output(
                'gog drive ls --account john@jwwhiting.com --plain --no-input 2>/dev/null | head -3',
                shell=True, timeout=15).decode()
            if "Trade_AI" in result:
                report["candidates"].append({"type": "gog_drive_account", "account": "john@jwwhiting.com",
                                            "status": "authenticated", "trade_ai_folder": True})
                report["selected"] = {"type": "gog_drive", "account": "john@jwwhiting.com",
                                     "method": "gog drive upload + gpg encrypt",
                                     "recommended_folder": "Trade_AI_Backups"}
                report["safe_to_use"] = True
    except Exception as e:
        report["warnings"].append(f"GOG Drive access check failed: {e}")

    if not report["safe_to_use"] and not report["blockers"]:
        report["blockers"].append("Could not verify Drive access")

    if args.verbose:
        print(f"Offsite Target: {'READY' if report['safe_to_use'] else 'NOT READY'}")
        print(f"  Method: {report.get('selected', {}).get('method', 'none')}")
        print(f"  Encryption: {report.get('encryption', {}).get('version', 'none')}")
        if report["blockers"]:
            for b in report["blockers"]:
                print(f"  BLOCKER: {b}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Offsite Backup Target — {'READY' if report['safe_to_use'] else 'NOT READY'}",
              f"\nMethod: {report.get('selected', {}).get('method', 'none')}",
              f"Encryption: {report.get('encryption', {}).get('version', 'none')}"]
        if report["blockers"]:
            md.extend(["", "## Blockers"] + [f"- {b}" for b in report["blockers"]])
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
