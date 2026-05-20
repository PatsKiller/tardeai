#!/usr/bin/env python3
"""pipeline_run_telemetry.py — Central helper for recording pipeline stage runs.

Write-only telemetry. No trades. No orders. No approvals.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _get_conn():
    try:
        from db_adapter import _get_conn as gc
        return gc()
    except Exception:
        return None


def record_stage_run(stage_name, category, status, started_at, finished_at,
                     rows_produced=None, source="cron", warnings=None, errors=None, metadata=None):
    """Record a pipeline stage run to pipeline_runs table.

    Uses pipeline_key=stage_name to match the Pipeline Operations UI query.
    """
    conn = _get_conn()
    if not conn:
        print(f"[telemetry] WARN: no DB connection, skipping telemetry for {stage_name}")
        return None

    duration = None
    if started_at and finished_at:
        duration = round((finished_at - started_at).total_seconds(), 2)

    run_id = f"{stage_name}_{started_at.strftime('%Y%m%d_%H%M%S')}" if started_at else stage_name
    run_label = source or "unknown"

    summary = {
        "category": category,
        "rows_produced": rows_produced,
        "warnings": warnings or [],
        "errors": errors or [],
        "metadata": metadata or {},
    }

    try:
        cur = conn.cursor()
        # Use pipeline_key as the stage identifier (matches UI query pattern)
        # Also write to script_name column if it exists for compatibility
        cur.execute("""
            INSERT INTO pipeline_runs
                (run_id, pipeline_key, run_label, status, trigger_source,
                 started_at, finished_at, duration_seconds, summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [run_id, stage_name, run_label, status, source,
              started_at, finished_at, duration, json.dumps(summary)])
        conn.commit()
        return run_id
    except Exception as e:
        print(f"[telemetry] WARN: failed to record {stage_name}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def start_stage_run(stage_name, category, source="cron", metadata=None):
    """Record a stage start. Returns run_id for later finish."""
    now = datetime.now(timezone.utc)
    return record_stage_run(stage_name, category, "started", now, None,
                            source=source, metadata=metadata)


def finish_stage_run(stage_name, run_id, status, rows_produced=None,
                     started_at=None, warnings=None, errors=None, metadata=None):
    """Record a stage finish by updating or inserting a completion record."""
    now = datetime.now(timezone.utc)
    return record_stage_run(stage_name, stage_name, status,
                            started_at or now, now,
                            rows_produced=rows_produced,
                            source="cron",
                            warnings=warnings, errors=errors, metadata=metadata)
