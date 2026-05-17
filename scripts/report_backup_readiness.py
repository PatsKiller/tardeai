#!/usr/bin/env python3
"""report_backup_readiness.py — Backup and restore maturity scoring.

Read-only. No secrets exposed. No mutations.

Usage:
    .venv/bin/python scripts/report_backup_readiness.py --verbose
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DB_BACKUP_DIR = Path("/home/johnclaw/db_backups")


def _exists(p):
    return Path(p).exists()


def _latest_file(directory, pattern="*.sql.gz"):
    import glob
    files = sorted(glob.glob(str(Path(directory) / pattern)))
    return Path(files[-1]) if files else None


def _file_age_hours(path):
    if not path or not Path(path).exists():
        return None
    mtime = Path(path).stat().st_mtime
    return round((datetime.now().timestamp() - mtime) / 3600, 1)


def main():
    p = argparse.ArgumentParser(description="Backup readiness report (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    scores = {}

    # 1. Local DB backup
    latest_db = _latest_file(DB_BACKUP_DIR)
    db_age = _file_age_hours(latest_db)
    scores["local_db_backup"] = 10 if (db_age and db_age < 30) else 7 if (db_age and db_age < 72) else 3 if latest_db else 0

    # 2. Full system backup script
    scores["full_backup_script"] = 10 if _exists(PROJ / "scripts/full_system_backup.py") else 0

    # 3. Backup verification script
    scores["backup_verification"] = 10 if _exists(PROJ / "scripts/backup_verify.py") else 0

    # 4. Backup cron
    try:
        crontab = subprocess.check_output("crontab -l", shell=True, stderr=subprocess.DEVNULL).decode()
        has_backup_cron = "backup_verify" in crontab or "full_system_backup" in crontab
    except Exception:
        has_backup_cron = False
    scores["backup_cron"] = 8 if has_backup_cron else 0

    # 5. Offsite target
    try:
        remotes = subprocess.check_output("rclone listremotes", shell=True, stderr=subprocess.DEVNULL).decode().strip()
        has_offsite = len(remotes) > 0
    except Exception:
        has_offsite = False
    scores["offsite_target"] = 10 if has_offsite else 0

    # 6. Encryption
    has_gpg = _exists("/usr/bin/gpg") or _exists("/usr/local/bin/gpg")
    scores["encryption_available"] = 7 if has_gpg else 0

    # 7. Restore guide
    has_restore_guide = _exists(PROJ / "docs/RESTORE_GUIDE.md")
    scores["restore_guide"] = 8 if has_restore_guide else 0

    # 8. RPO/RTO policy
    has_rpo = _exists(PROJ / "docs/recovery/phase_br1_offsite_backup_restore/br1_rpo_rto_policy.md")
    scores["rpo_rto_policy"] = 8 if has_rpo else 0

    # 9. Manifest/checksum
    scores["manifest_checksum"] = 0  # Not yet implemented

    # 10. Restore drill
    scores["restore_drill"] = 0  # Not yet implemented

    overall = round(sum(scores.values()) / len(scores), 1)

    gaps = []
    if scores["offsite_target"] == 0:
        gaps.append({"priority": "P0", "item": "No offsite backup configured (rclone has no remotes)"})
    if scores["manifest_checksum"] == 0:
        gaps.append({"priority": "P1", "item": "No backup manifest/checksum system"})
    if scores["restore_drill"] == 0:
        gaps.append({"priority": "P1", "item": "No restore drill executed"})
    if not has_rpo:
        gaps.append({"priority": "P2", "item": "RPO/RTO policy not documented"})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_db_dump": str(latest_db) if latest_db else None,
        "db_dump_age_hours": db_age,
        "db_dump_size_mb": round(latest_db.stat().st_size / 1e6, 1) if latest_db and latest_db.exists() else None,
        "scores": scores,
        "overall_score": overall,
        "gaps": gaps,
        "offsite_configured": has_offsite,
        "encryption_available": has_gpg,
        "rclone_installed": _exists("/home/johnclaw/.local/bin/rclone") or _exists("/usr/bin/rclone"),
    }

    if args.verbose:
        print(f"Backup Readiness Score: {overall}/10")
        print(f"  Latest DB dump: {latest_db} ({db_age}h old, {report['db_dump_size_mb']}MB)")
        for k, v in scores.items():
            print(f"  {k}: {v}/10")
        if gaps:
            print(f"\nGaps ({len(gaps)}):")
            for g in gaps:
                print(f"  [{g['priority']}] {g['item']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Backup Readiness — Score {overall}/10", "",
              f"Latest DB: {latest_db} ({db_age}h old)", "",
              "| Area | Score |", "|------|-------|"]
        for k, v in scores.items():
            md.append(f"| {k} | {v}/10 |")
        if gaps:
            md.extend(["", "## Gaps", ""])
            for g in gaps:
                md.append(f"- **[{g['priority']}]** {g['item']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
