from __future__ import annotations
import argparse, os, shutil
from pathlib import Path
from datetime import datetime

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    return path

def is_new_week(date_str: str) -> bool:
    return datetime.fromisoformat(date_str).weekday() == 0

def _rmtree_safe(path) -> None:
    """shutil.rmtree with Windows Access Denied protection."""
    import stat
    def _on_error(func, path, exc_info):
        # If Access Denied, try to clear read-only flag and retry once
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass  # skip locked files silently
    shutil.rmtree(path, onerror=_on_error)


def _move_safe(src, dst) -> bool:
    """shutil.move with Windows lock protection. Returns True if moved."""
    try:
        shutil.move(str(src), str(dst))
        return True
    except (PermissionError, OSError):
        return False  # file locked by another process — skip


def clean_weekly(project_root: Path, date_str: str, keep_logs: bool = True) -> dict:
    reports = project_root / "reports"
    raw = project_root / "data" / "raw"
    merged = project_root / "data" / "merged"
    archive = ensure_dir(project_root / "archive" / "weekly" / date_str)
    summary = {"date": date_str, "archived": [], "removed": [], "skipped": []}
    for path in [raw, merged]:
        if path.exists():
            target = archive / path.name
            if target.exists():
                _rmtree_safe(target)
            if _move_safe(path, target):
                summary["archived"].append(str(target))
            else:
                summary["skipped"].append(str(path))
            ensure_dir(path)
    if reports.exists():
        old_reports = [p for p in reports.iterdir() if p.is_dir() and p.name != date_str]
        for p in old_reports:
            target = archive / f"reports_{p.name}"
            if target.exists():
                _rmtree_safe(target)
            if _move_safe(p, target):
                summary["archived"].append(str(target))
            else:
                summary["skipped"].append(str(p))
    if not keep_logs:
        logs = project_root / "logs"
        if logs.exists():
            _rmtree_safe(logs)
            summary["removed"].append(str(logs))
            ensure_dir(logs)
    return summary

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--keep-logs", action="store_true")
    args = ap.parse_args()
    rootp = Path(args.project_root).resolve()
    if is_new_week(args.date):
        print(clean_weekly(rootp, args.date, keep_logs=args.keep_logs))
    else:
        print({"date": args.date, "message": "No weekly hygiene needed today."})
