"""Drive-sync health from the RAW last-result file.

Do not infer health from "0 uploaded, N unchanged" alone — that hid a
run that 404'd stale folder IDs. Read the result JSON the sync script
writes, including failed count.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "DriveSyncHealth@v1"
DEFAULT_RESULT = Path.home() / ".local" / "state" / "drive-sync-last-result.json"
DEFAULT_MAX_AGE_HOURS = 24

# Canonical Trade_AI_Docs_v2 docs/ folder. The duplicate
# 1Rb6qcu_D45ehZ0EKwEqwbzkEg9zKlBcA is deprecated (README in that folder).
CANONICAL_DOCS_ID = "1BMxbxU9c9rF3NBvXVQtVEewdvkifVkwP"
CANONICAL_OPS_ID = "1a7vr2gnNipfaFejjgHxKNhSFmnh_XVZ_"
DEPRECATED_DOCS_ID = "1Rb6qcu_D45ehZ0EKwEqwbzkEg9zKlBcA"


def parse_iso(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_drive_sync(
    raw: Optional[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    """Pure evaluator. `raw` is the unfiltered last-result JSON (or None)."""
    now = now or datetime.now(timezone.utc)
    firing: list[str] = []
    uploaded = skipped = failed = 0
    finished = None
    status = None
    exit_code = None
    if raw is None:
        firing.append("missing_result_file")
    else:
        status = raw.get("status")
        exit_code = raw.get("exit_code")
        try:
            uploaded = int(raw.get("uploaded") or 0)
        except (TypeError, ValueError):
            uploaded = 0
        try:
            skipped = int(raw.get("skipped") or 0)
        except (TypeError, ValueError):
            skipped = 0
        try:
            failed = int(raw.get("failed") or 0)
        except (TypeError, ValueError):
            failed = 0
        finished = parse_iso(raw.get("finished_utc") or raw.get("finished_at"))
        if status == "running":
            started = parse_iso(raw.get("started_utc"))
            if started is None or (now - started).total_seconds() > max_age_hours * 3600:
                firing.append("stale_running")
        if finished is None and status != "running":
            firing.append("missing_finished_utc")
        elif finished is not None:
            age_h = (now - finished).total_seconds() / 3600.0
            if age_h > max_age_hours:
                firing.append(f"stale:{age_h:.1f}h>{max_age_hours}h")
        if exit_code not in (0, "0", None) and status != "running":
            firing.append(f"exit_code:{exit_code}")
        # The silent-failure shape: cron "completed" with 0 uploads and N 404s.
        if failed > 0 and uploaded == 0 and status == "done":
            firing.append(f"zero_uploaded_with_failures:{failed}")
    return {
        "lane": "drive-sync",
        "ok": not firing,
        "firing": firing,
        "status": status,
        "exit_code": exit_code,
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "finished_utc": finished.replace(microsecond=0).isoformat() if finished else None,
        "canonical_docs_id": CANONICAL_DOCS_ID,
        "authority": AUTHORITY,
        "schema": SCHEMA,
        "reads_raw_result": True,
        "as_of": now.replace(microsecond=0).isoformat(),
    }


def load_raw(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    p = path or Path(os.getenv("DRIVE_SYNC_RESULT", str(DEFAULT_RESULT)))
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def collect_drive_report(
    *, now: Optional[datetime] = None, path: Optional[Path] = None
) -> dict[str, Any]:
    raw = load_raw(path)
    row = evaluate_drive_sync(raw, now=now)
    row["result_path"] = str(path or Path(os.getenv("DRIVE_SYNC_RESULT", str(DEFAULT_RESULT))))
    row["raw_present"] = raw is not None
    return row
