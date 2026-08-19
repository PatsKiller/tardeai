"""Read live research queue for a symbol thesis card (fail-closed).

Sources: watchlist_agent_jobs (and optionally watchlist_agent_results).
If DB is unavailable or the table is missing, return empty lists — never fake jobs.
READ_ONLY_ADVISORY. No enqueue, no drain, no 5135-symbol crawl.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
ACTIVE_STATUSES = frozenset({"queued", "processing", "pending", "running", "claimed"})
COMPLETED_STATUSES = frozenset({"completed", "complete", "done"})


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return str(v)


def _row(r: dict[str, Any]) -> dict[str, Any]:
    status = str(r.get("status") or "").lower()
    return {
        "id": r.get("id"),
        "symbol": str(r.get("symbol") or "").upper() or None,
        "agent": r.get("requested_agent") or r.get("agent"),
        "request_type": r.get("request_type") or r.get("note"),
        "status": r.get("status"),
        "created_at": _iso(r.get("created_at")),
        "completed_at": _iso(r.get("completed_at")),
        "summary": (str(r.get("summary") or r.get("note") or "")[:240] or None),
        "lane": "active" if status in ACTIVE_STATUSES else (
            "completed" if status in COMPLETED_STATUSES else "other"
        ),
    }


def _split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active, completed = [], []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = _row(raw)
        if item["lane"] == "active":
            active.append(item)
        elif item["lane"] == "completed":
            completed.append(item)
    return {
        "active_research": active[:20],
        "recent_completed_research": completed[:10],
        "source": "watchlist_agent_jobs",
        "ok": True,
        "authority": AUTHORITY,
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _empty(*, reason: str) -> dict[str, Any]:
    return {
        "active_research": [],
        "recent_completed_research": [],
        "source": "unavailable" if reason != "empty" else "empty",
        "ok": reason == "empty",
        "reason": reason,
        "authority": AUTHORITY,
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def load_symbol_research_queue(
    symbol: str,
    *,
    conn=None,
    rows: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Active + recent completed research for one symbol.

    Pass ``rows`` to skip DB (tests). On connection/query failure: empty lists.
    """
    if rows is not None:
        return _split(list(rows))

    close = False
    cur = None
    try:
        if conn is None:
            from scripts.lib.symbol_thesis_supply_plane import _conn
            conn = _conn()
            close = True
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, symbol, requested_agent, request_type, status, note,
                   created_at, completed_at
            FROM watchlist_agent_jobs
            WHERE upper(symbol) = %s
            ORDER BY created_at DESC NULLS LAST
            LIMIT 40
            """,
            (str(symbol or "").upper(),),
        )
        job_rows = [dict(r) for r in (cur.fetchall() or [])]
        if not job_rows:
            try:
                cur.execute(
                    """
                    SELECT NULL::text AS id, symbol, agent AS requested_agent,
                           NULL::text AS request_type, 'completed' AS status,
                           summary AS note, created_at, created_at AS completed_at,
                           summary
                    FROM watchlist_agent_results
                    WHERE upper(symbol) = %s
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT 10
                    """,
                    (str(symbol or "").upper(),),
                )
                job_rows = [dict(r) for r in (cur.fetchall() or [])]
            except Exception:
                job_rows = []
        if not job_rows:
            return _empty(reason="empty")
        return _split(job_rows)
    except Exception as exc:
        return {**_empty(reason=f"{type(exc).__name__}:{exc}"[:160]), "ok": False}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        if close and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
