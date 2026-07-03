"""Health probes for Scope Governor + event feeder cron reliability."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .heartbeat import (
    FEEDER_HEARTBEAT,
    GOVERNOR_HEARTBEAT,
    heartbeat_age_minutes,
    read_heartbeat,
)
from .universe import UNIVERSE_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SAFE_FLOCK_LOG = PROJECT_ROOT / "logs" / "safe_flock_events.jsonl"

# Governor cron :07/:37 → max gap 30m; allow slack for slow runs
GOVERNOR_STALE_WARN_MIN = 38
GOVERNOR_STALE_CRIT_MIN = 50
# Event feeder */5
FEEDER_STALE_WARN_MIN = 8
FEEDER_STALE_CRIT_MIN = 15


def _file_age_min(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        return max(0.0, (datetime.now(timezone.utc).timestamp() - mtime) / 60.0)
    except Exception:
        return None


def _crontab_text() -> str:
    try:
        return subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout or ""
    except Exception:
        return ""


def _safe_flock_skips(component: str, hours: float = 6.0) -> int:
    if not SAFE_FLOCK_LOG.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    n = 0
    try:
        for line in SAFE_FLOCK_LOG.read_text(errors="ignore").splitlines()[-2000:]:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("component") != component or ev.get("event_type") != "lock_skip":
                continue
            ts = ev.get("ts", "")
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.timestamp() >= cutoff:
                    n += 1
            except Exception:
                pass
    except Exception:
        return 0
    return n


def _db_audit_age_min(cur) -> float | None:
    try:
        cur.execute("""SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at)))/60
                       FROM scope_governor_audit""")
        row = cur.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _db_audit_runs_24h(cur) -> int | None:
    try:
        cur.execute("""SELECT count(DISTINCT run_id) FROM scope_governor_audit
                       WHERE created_at > NOW() - interval '24 hours'""")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None


def check_scope_governor_health(conn=None) -> list[dict[str, Any]]:
    """Return raw finding dicts: {type, severity, message, **extra}."""
    findings: list[dict[str, Any]] = []
    cr = _crontab_text()
    has_gov_cron = "hermes_scope_governor.py" in cr and "--apply" in cr
    has_feeder_cron = "hermes_score_event_feeder.py" in cr and "--apply" in cr
    uses_safe_flock_gov = "safe_flock.sh" in cr and "hermes_scope_governor" in cr

    if not has_gov_cron:
        findings.append({
            "type": "hermes_scope_governor_cron_missing",
            "severity": "critical",
            "message": "hermes_scope_governor.py --apply is NOT in crontab — scope tiers will not update",
            "kind": "code",
        })
    elif not uses_safe_flock_gov:
        findings.append({
            "type": "hermes_scope_governor_cron_unobservable",
            "severity": "warning",
            "message": "Scope governor cron uses flock -n (silent skip) — switch to safe_flock.sh for observable runs",
            "kind": "code",
        })

    if not has_feeder_cron:
        findings.append({
            "type": "hermes_event_feeder_cron_missing",
            "severity": "critical",
            "message": "hermes_score_event_feeder.py --apply is NOT in crontab — S3 reactivation/event lane idle",
            "kind": "code",
        })

    gov_age = heartbeat_age_minutes(GOVERNOR_HEARTBEAT)
    hb = read_heartbeat(GOVERNOR_HEARTBEAT) or {}
    if gov_age is None:
        findings.append({
            "type": "hermes_scope_governor_heartbeat_missing",
            "severity": "warning",
            "message": "Scope governor heartbeat file missing — no successful run recorded yet",
        })
    elif gov_age > GOVERNOR_STALE_CRIT_MIN:
        findings.append({
            "type": "hermes_scope_governor_stale",
            "severity": "critical",
            "message": f"Scope governor last heartbeat {gov_age:.0f}m ago (cron :07/:37) — tier ledger stale",
            "age_min": round(gov_age, 1),
            "kind": "code",
        })
    elif gov_age > GOVERNOR_STALE_WARN_MIN:
        findings.append({
            "type": "hermes_scope_governor_stale",
            "severity": "warning",
            "message": f"Scope governor last heartbeat {gov_age:.0f}m ago (expected <{GOVERNOR_STALE_WARN_MIN}m)",
            "age_min": round(gov_age, 1),
        })

    if hb.get("ok") is False:
        findings.append({
            "type": "hermes_scope_governor_last_run_failed",
            "severity": "warning",
            "message": f"Scope governor last run failed: {hb.get('reason', 'unknown')[:120]}",
            "kind": "code",
        })

    skips = _safe_flock_skips("hermes_scope_governor")
    if skips >= 6:
        findings.append({
            "type": "hermes_scope_governor_lock_skips",
            "severity": "warning",
            "message": f"Scope governor skipped {skips} times in 6h (prior run still holding lock) — runs may be wedged",
            "skip_count": skips,
            "kind": "code",
        })

    feed_age = _file_age_min(UNIVERSE_PATH)
    if feed_age is not None and feed_age > GOVERNOR_STALE_CRIT_MIN:
        findings.append({
            "type": "hermes_governed_universe_stale",
            "severity": "warning",
            "message": f"Governed universe feed {feed_age:.0f}m old — Hermes may read stale scope",
            "age_min": round(feed_age, 1),
        })

    feeder_age = heartbeat_age_minutes(FEEDER_HEARTBEAT)
    if feeder_age is None:
        findings.append({
            "type": "hermes_event_feeder_heartbeat_missing",
            "severity": "warning",
            "message": "Event feeder heartbeat missing — event lane may not be running",
        })
    elif feeder_age > FEEDER_STALE_CRIT_MIN:
        findings.append({
            "type": "hermes_event_feeder_stale",
            "severity": "critical",
            "message": f"Event feeder last heartbeat {feeder_age:.0f}m ago (cron */5) — S3 reactivation stalled",
            "age_min": round(feeder_age, 1),
            "kind": "code",
        })
    elif feeder_age > FEEDER_STALE_WARN_MIN:
        findings.append({
            "type": "hermes_event_feeder_stale",
            "severity": "warning",
            "message": f"Event feeder last heartbeat {feeder_age:.0f}m ago (expected <{FEEDER_STALE_WARN_MIN}m)",
            "age_min": round(feeder_age, 1),
        })

    if conn is not None:
        try:
            cur = conn.cursor()
            audit_age = _db_audit_age_min(cur)
            runs_24h = _db_audit_runs_24h(cur)
            if audit_age is not None and audit_age > GOVERNOR_STALE_CRIT_MIN:
                findings.append({
                    "type": "hermes_scope_governor_audit_stale",
                    "severity": "critical",
                    "message": f"No scope_governor_audit row in {audit_age:.0f}m — DB tier changes stalled",
                    "age_min": round(audit_age, 1),
                    "kind": "code",
                })
            if runs_24h is not None and runs_24h < 20 and has_gov_cron:
                findings.append({
                    "type": "hermes_scope_governor_underrunning",
                    "severity": "warning",
                    "message": f"Only {runs_24h} governor runs in 24h (expect ~48) — cron skips or failures",
                    "runs_24h": runs_24h,
                    "kind": "code",
                })
        except Exception:
            pass

    return findings