"""pipeline_failures.py — GET /api/v2/system/pipeline-failures (audit 2026-10-21).

/api/v2/pipeline-health returns the latest 100 pipeline_runs rows, and on a busy day those are all
finviz_screener_runner successes: a failure further back is on no page. This is one server-side aggregate over the
window, grouped by pipeline: failure count, last failure time and the last error text.

LQ-20261107-1566 (page defect 175): the System panel was counting every failed row in the window, including
``zombie run cleared`` bookkeeping and failures that already have a later success for the same
``pipeline_key``. That made a healthy Research indexer read as "failed 4×" after remediate settled stuck
rows. The aggregate is now the same unrecovered set ``health_agent`` uses for execution_health: substantive
errors only, no zombie-cleared note, and no later success.

``db_query(sql, params) -> list[row] | None`` is injected; ``None`` (db_adapter's "could not read") is
``UNAVAILABLE`` with null counts — never an empty, green list.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from lib.pipeline_failure_counts import SUBSTANTIVE_FAILURE_FILTER

SCHEMA = "PipelineFailures@v1"
FAILED_STATUSES = ("failed", "error", "timeout", "crashed")

SQL = (
    "SELECT f.pipeline_key, COUNT(*) AS failed, MAX(f.started_at) AS last_failed_at, "
    "(ARRAY_AGG(COALESCE(NULLIF(NULLIF(f.summary->>'errors', '[]'), ''), f.summary->>'error', "
    "f.summary->>'note', '') ORDER BY f.started_at DESC))[1] AS last_error, "
    # Zombie-cleared rows are excluded below; the column stays for schema stability (always 0 here).
    "COUNT(*) FILTER (WHERE f.summary->>'note' ILIKE 'zombie%%') AS zombie_cleared "
    "FROM pipeline_runs f WHERE f.started_at > NOW() - make_interval(hours => %s) "
    "AND LOWER(f.status) IN ('failed', 'error', 'timeout', 'crashed') "
    "AND (f.summary IS NULL OR f.summary::text NOT LIKE '%%zombie run cleared%%') "
    f"AND {SUBSTANTIVE_FAILURE_FILTER} "
    "AND NOT EXISTS ("
    "SELECT 1 FROM pipeline_runs s WHERE s.pipeline_key = f.pipeline_key "
    "AND s.status = 'success' AND s.started_at > f.started_at"
    ") "
    "GROUP BY f.pipeline_key ORDER BY COUNT(*) DESC, MAX(f.started_at) DESC"
)


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def project(db_query: Callable[[str, tuple], Optional[list]], *, hours: int = 24,
            now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    hours = max(1, min(int(hours or 24), 24 * 7))
    out: dict[str, Any] = {"schema": SCHEMA, "authority": "READ_ONLY_ADVISORY", "as_of": now.isoformat(),
                           "window_hours": hours, "failed_statuses": list(FAILED_STATUSES),
                           "status": "UNAVAILABLE", "pipelines": None, "pipelines_failing": None,
                           "failed_runs": None, "note": None}
    try:
        rows = db_query(SQL, (hours,))
    except Exception as exc:  # noqa: BLE001 — the reason is the payload
        out["note"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out
    if rows is None:
        out["note"] = "pipeline_runs could not be read"
        return out
    items = []
    for r in rows:
        if isinstance(r, dict):
            key, n, last, err = r.get("pipeline_key"), r.get("failed"), r.get("last_failed_at"), r.get("last_error")
            zombie = r.get("zombie_cleared")
        else:
            key, n, last, err = r[0], r[1], r[2], r[3]
            zombie = r[4] if len(r) > 4 else None
        items.append({"pipeline": str(key or "(unknown)"), "failed": int(n or 0), "last_failed_at": _iso(last),
                      "last_error": (str(err)[:300] if err else None),
                      "zombie_cleared": int(zombie) if zombie is not None else None})
    out.update(status="OK", pipelines=items, pipelines_failing=len(items),
               failed_runs=sum(i["failed"] for i in items))
    return out


def load(hours: int = 24) -> dict[str, Any]:
    """Live read through db_adapter (returns None on any error)."""
    try:
        import sys
        from pathlib import Path

        scripts = str(Path(__file__).resolve().parents[1])
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from db_adapter import USE_DB, _execute  # type: ignore
    except Exception as exc:  # noqa: BLE001
        # `exc` is cleared when the except block ends, so a lambda that reads it later raised
        # "NameError: cannot access free variable 'exc'" and the operator saw that instead of the real
        # import error. Bind the exception before building the deferred callable (2026-11-03).
        failure = exc
        return project(lambda s, p: (_ for _ in ()).throw(failure), hours=hours)
    if not USE_DB:
        return project(lambda s, p: None, hours=hours)
    return project(lambda s, p: _execute(s, p, fetch="all"), hours=hours)
