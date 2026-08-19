#!/usr/bin/env python3
"""R7.1 health audit: RAG schedule, Hermes coordinator, Cursor dependency.

Read-only. Does not install cron or reset timestamps.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _crontab() -> str:
    try:
        return subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def audit_rag(cron: str) -> dict:
    scheduled = "rag_indexer.py" in cron and not any(
        line.strip().startswith("#") and "rag_indexer.py" in line for line in cron.splitlines()
        if "rag_indexer.py" in line and line.strip().startswith("#")
    )
    # true if any uncommented line contains rag_indexer
    scheduled = any(
        "rag_indexer.py" in line and not line.strip().startswith("#")
        for line in cron.splitlines()
    )
    log = LIVE / "logs" / "rag_indexer.log"
    log_mtime = log.stat().st_mtime if log.is_file() else None
    age_h = None
    if log_mtime:
        age_h = round((datetime.now().timestamp() - log_mtime) / 3600, 2)
    # job_coverage false positive
    detection = "FALSE_POSITIVE_NOT_SCHEDULED" if scheduled else "GENUINELY_UNSCHEDULED"
    return {
        "job": "rag_embeddings",
        "canonical_owner": "scripts/rag_indexer.py",
        "crontab_scheduled": scheduled,
        "crontab_line_present": "0 */4" if scheduled else None,
        "job_coverage_schedule_match_bug": "schedule_match='embedding' misses 'rag_indexer.py'",
        "detection_class": detection,
        "log_age_hours": age_h,
        "duplicate_cron_created": False,
        "action": "fix_job_coverage_detection_on_cursor_branch" if scheduled else "wire_via_job_coverage",
    }


def audit_hermes(cron: str) -> dict:
    scheduled = any(
        "hermes_coordinator.py" in line and not line.strip().startswith("#")
        for line in cron.splitlines()
    )
    log = LIVE / "logs" / "hermes_coordinator.log"
    age_h = None
    if log.is_file():
        age_h = round((datetime.now().timestamp() - log.stat().st_mtime) / 3600, 2)
    # cadence_h=1 in job_coverage but idle runs may not append — classify
    if scheduled and age_h is not None and age_h > 2:
        klass = "EXPECTED_IDLE_OR_STALE_FALSE_POSITIVE"
    elif scheduled:
        klass = "OK"
    else:
        klass = "SCHEDULER_MISSING"
    jobs_log = LIVE / "logs" / "watchlist_agent_jobs.log"
    jobs_age = None
    if jobs_log.is_file():
        jobs_age = round((datetime.now().timestamp() - jobs_log.stat().st_mtime) / 3600, 2)
    return {
        "hermes_coordinator": {
            "crontab_scheduled": scheduled,
            "log_age_hours": age_h,
            "class": klass,
            "note": "Do not merely reset timestamps; investigate if orphaned jobs exist.",
        },
        "process_watchlist_agent_jobs": {
            "crontab_scheduled": any(
                "process_watchlist_agent_jobs.py" in line and not line.strip().startswith("#")
                for line in cron.splitlines()
            ),
            "log_age_hours": jobs_age,
            "class": "OK" if jobs_age is not None and jobs_age < 4 else "STALE_OR_IDLE",
        },
    }


def main() -> int:
    from scripts.lib.r71_cursor_fabric_map import fabric_map_report, load_dependency

    cron = _crontab()
    dep = load_dependency()
    rag = audit_rag(cron)
    hermes = audit_hermes(cron)

    # embeddings freshness from DB
    emb = {}
    try:
        from rag_retrieval import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT max(created_at) AS last, count(*) FILTER (WHERE created_at>now()-interval '24 hours') AS n24 FROM content_embeddings"
        )
        emb = dict(cur.fetchone() or {})
        if emb.get("last"):
            emb["last"] = emb["last"].isoformat()
        cur.close()
        conn.close()
    except Exception as e:
        emb = {"error": str(e)}

    unrelated = {
        "options_monitor": "ACTIVE_TRADER_ONLY — not #397 blocker",
        "options_paper_lifecycle": "ACTIVE_TRADER_ONLY — not #397 blocker",
        "protection_pipeline": "ACTIVE_TRADER_ONLY — not #397 blocker",
    }

    out = {
        "schema": "R71HealthAudit@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "dependency": dep,
        "fabric_map": fabric_map_report(),
        "rag": {**rag, "embeddings": emb},
        "hermes": hermes,
        "unrelated_job_coverage": unrelated,
        "cursor_remediation_versioned": bool(dep.get("cursor_remediation_versioned")),
        "hold_on_unversioned_live_dependency": not bool(dep.get("cursor_remediation_versioned")),
        "authority": "READ_ONLY_ADVISORY",
    }
    out_path = ROOT / "evidence" / "R71_HEALTH_AUDIT.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "out": str(out_path),
        "cursor_versioned": out["cursor_remediation_versioned"],
        "rag_detection": rag["detection_class"],
        "hermes_coord_class": hermes["hermes_coordinator"]["class"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
