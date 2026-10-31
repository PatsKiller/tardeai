"""Pure, fail-closed predicates for the optional standing disk-hygiene rules.

No deletion, host census, provider calls or approval writer lives here. The sole
removal implementation remains scripts/disk_hygiene.py. Evidence is captured by
an operator-authorized collector and supplied as a digest-bound snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

SCHEMA = "DiskHygieneEvidence@v1"
SOURCES = ("cron", "units", "processes", "coordination", "prs", "pointers")
RULE_KINDS = {"A": "archived_dump", "S": "rtc_scratch", "T": "agent_scratch", "W": "git_worktree",
              "C": "abandoned_worktree", "R": "release_dir"}
#: Rule X (archive retention) is reported only; it is never listable in standing_apply.rules and never removes.
PLAN_ONLY_KINDS = {"X": "archive_ref"}
MAX_BYTES = 40 * 1024**3
MAX_AGE_SECONDS = 2 * 3600


def digest(value: Any) -> str:
    raw = value.encode() if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def aware(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def evidence_context(doc: Mapping[str, Any], now: datetime, *, applying: bool = False) -> dict:
    """Absence is proven only by a complete, fresh, individually hashed source.

    Offline captures support quoted previews only. They cannot authorize apply.
    Future/naive dates, missing source categories and malformed data fail closed.
    """
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError("evidence_schema")
    if applying and doc.get("offline") is not False:
        raise ValueError("offline_evidence_cannot_apply")
    if not isinstance(doc.get("sources"), dict):
        raise ValueError("evidence_sources_shape")
    data = {}
    for key in SOURCES:
        row = (doc.get("sources") or {}).get(key)
        if not isinstance(row, dict) or row.get("complete") is not True:
            raise ValueError(f"evidence_incomplete:{key}")
        ts = aware(row.get("captured_at"))
        if ts is None or not 0 <= (now - ts).total_seconds() <= MAX_AGE_SECONDS:
            raise ValueError(f"evidence_stale:{key}")
        val = row.get("data")
        expected_type = str if key == "cron" else (dict if key == "coordination" else list)
        if not isinstance(val, expected_type) or row.get("sha256") != digest(val):
            raise ValueError(f"evidence_digest_or_shape:{key}")
        data[key] = val
    co = data["coordination"]
    if any(not isinstance(co.get(k), list) for k in ("references", "live_claims", "live_worklogs")):
        raise ValueError("evidence_coordination_shape")
    if any(not isinstance(p, dict) for p in data["processes"] + data["prs"]):
        raise ValueError("evidence_records_shape")
    opaque = [p for p in data["processes"] if p.get("opaque") is True]
    if applying and opaque:
        # A process whose cwd/fds the kernel hides from this user may reference a candidate.
        # Its absence is unproven, so it can support a quoted preview, never a removal.
        raise ValueError("evidence_opaque_processes")
    refs = [(key, json.dumps(data[key])) for key in ("units", "pointers")]
    refs.append(("cron", data["cron"]))
    return {"now": now, "cwds": {p.get("cwd") for p in data["processes"] if p.get("cwd")},
            "refs": refs, "snapshot": data, "evidence_sha256": digest(doc), "offline": doc.get("offline") is not False,
            "opaque_processes": opaque}


#: An mtime this far past ``now`` is a fixture or clock artefact, not activity (tests stamp files weeks ahead).
FUTURE_MTIME_SKEW_SECONDS = 300


def activity(path: Path, *, max_entries: int = 250000, protected: Callable[[Path], bool] | None = None,
             now: float | None = None) -> tuple[float | None, str | None]:
    """Bounded recursive lstat, no symlink following; incomplete scans are held.

    With ``now``, an entry whose mtime lies in the future counts at its ctime instead: the kernel sets ctime on
    every change (``utime`` included), so it is the real time the entry was last written.
    """
    newest, count = 0.0, 0
    pending = [path]
    try:
        while pending:
            p = pending.pop()
            if protected and protected(p):
                return None, "activity_contains_protected_entry"
            st = p.lstat()
            stamp = st.st_mtime
            if now is not None and stamp > now + FUTURE_MTIME_SKEW_SECONDS:
                stamp = st.st_ctime
            newest = max(newest, stamp)
            count += 1
            if count > max_entries:
                return None, "activity_scan_limit"
            if p.is_dir() and not p.is_symlink():
                with os.scandir(p) as entries:
                    pending.extend(Path(e.path) for e in entries)
    except OSError:
        return None, "activity_scan_unreadable"
    return newest, None


def retention_days(files: list[dict], *, daily: int = 7, weekly: int = 4) -> set[str]:
    """Newest dump of each ET day; union latest seven days and four Sundays.

    The date basis is original file mtime, never manifest/cache generation time.
    Extra same-day dumps are not required recovery points. Sunday points can
    overlap daily points, so the retained union can contain fewer than 11 files.
    """
    by_day: dict = {}
    for row in sorted(files, key=lambda x: (-x["mtime"], x["path"])):
        day = datetime.fromtimestamp(row["mtime"], timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
        by_day.setdefault(day, row["path"])
    days = sorted(by_day, reverse=True)
    kept_days = set(days[:daily]) | set([d for d in days if d.weekday() == 6][:weekly])
    return {by_day[d] for d in kept_days}


def record_refs(ctx: Mapping, kind: str) -> list[tuple[str, str]]:
    data = ctx["snapshot"]
    co = data["coordination"]
    refs = list(ctx["refs"])
    refs += [("processes", json.dumps(data["processes"])), ("open_pr", json.dumps(data["prs"]))]
    fields = ("references", "live_claims", "live_worklogs") if kind in ("rtc_scratch", "agent_scratch") else ("live_claims", "live_worklogs")
    refs += [("coordination:" + k, json.dumps(co[k])) for k in fields]
    return refs


def per_rule(items: list[dict], removed: list[dict] | None = None) -> dict:
    out = {rule: {"planned_bytes": 0, "applied_bytes": 0, "planned_gb": 0.0, "applied_gb": 0.0, "unmeasured_planned_items": 0} for rule in RULE_KINDS}
    for key, rows in (("planned_bytes", items), ("applied_bytes", removed or [])):
        for item in rows:
            if item.get("rule") in out:
                n = item.get("size_bytes") if key == "planned_bytes" else item.get("bytes")
                if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
                    out[item["rule"]][key] += n
                elif key == "planned_bytes":
                    out[item["rule"]]["unmeasured_planned_items"] += 1
    for row in out.values():
        row["planned_gb"] = round(row["planned_bytes"] / 1024**3, 3)
        row["applied_gb"] = round(row["applied_bytes"] / 1024**3, 3)
        row["held_bytes"] = max(0, row["planned_bytes"] - row["applied_bytes"])
    return out


def operator_digest(report: Mapping) -> str:
    rules = report.get("per_rule") or {}
    detail = " ".join(f"{key}:{val['planned_gb']:.3f}/{val['applied_gb']:.3f}GiB" for key, val in sorted(rules.items()))
    held = report.get("held_bytes")
    held_label = f"{held / 1024**3:.3f}GiB" if isinstance(held, int) else "NOT_MEASURED"
    return f"Disk hygiene planned/applied {detail or 'NOT_MEASURED'}; held {held_label}; removed {len(report.get('removed') or [])}; skipped {len(report.get('skipped') or [])}; refusal {report.get('refused') or 'none'}"


def monitor_decision(current: Mapping, previous: Mapping, used_pct: float | None) -> dict:
    """Consecutive DISTINCT hygiene runs, not repeated monitor polls of one run."""
    run = current.get("run_id")
    prev_run = previous.get("run_id")
    held = current.get("held_bytes")
    old = previous.get("held_bytes")
    consecutive = bool(run and prev_run and run != prev_run and isinstance(held, (float, int))
                       and isinstance(old, (float, int)) and held > 10 * 1024**3 and old > 10 * 1024**3)
    return {"run_id": run, "manifest_sha256": current.get("manifest_sha256"), "held_bytes": held,
            "alert": "disk_above_85" if used_pct is not None and used_pct > 85 else ("held_above_10gb_two_runs" if consecutive else None)}
