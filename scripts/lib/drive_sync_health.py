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
        # CURRENT pin behind origin/main: sweep "green" while shipping stale docs.
        if str(raw.get("source_status") or "") == "DEGRADED_STALE_SOURCE":
            firing.append("DEGRADED_STALE_SOURCE")
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


def source_status_for(pin: Any, main_sha: Any, *, repo: Any, run: Any = None) -> str:
    """``DEGRADED_STALE_SOURCE`` only when the promoted pin does not CONTAIN ``origin/main``.

    LQ-20261107-1659. The writer used to compare for equality (``pin != main_sha``), which is
    true in the NORMAL deployment topology: the host promotes an approved integration fold, so
    the live ``SOURCE_COMMIT`` is ahead of ``origin/main`` until main catches up. The hourly
    sweep therefore reported a stale source on every promote cycle while it was in fact
    uploading the newest docs, and the alert fired long enough to become wallpaper.

    Containment is the question that matches the risk the alarm describes ("sweep green while
    shipping stale docs"): does the pin that was synced contain everything main has? If main is
    an ancestor of the pin, it does — the mirror may legitimately carry docs main has not taken
    yet. If it is not an ancestor (pin behind, or diverged), docs main published are missing
    from the mirror, and that is the degradation worth a word.

    ``run(cmd) -> int`` is injectable for tests; the default shells out to git. Any outcome other
    than git's 1 ("not an ancestor") reads as ok: an unreadable repository is not evidence that
    the mirror is stale, and a false alarm here is what made the real one invisible.
    """
    pin_s = str(pin or "").strip()
    main_s = str(main_sha or "").strip()
    if not pin_s or not main_s or pin_s == main_s:
        return "ok"
    if run is None:
        import subprocess

        def run(cmd):  # noqa: ANN001, ANN202 -- the injectable test runner has no annotation
            try:
                return subprocess.run(cmd, capture_output=True, timeout=15).returncode
            except (OSError, ValueError, subprocess.SubprocessError):
                return -1
    try:
        rc = int(run(["git", "-C", str(repo), "merge-base", "--is-ancestor", main_s, pin_s]))
    except Exception:  # noqa: BLE001 -- an unrunnable check must not invent an alarm
        rc = -1
    return "DEGRADED_STALE_SOURCE" if rc == 1 else "ok"


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
