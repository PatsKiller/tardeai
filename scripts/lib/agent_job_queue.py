"""Enqueue a watchlist_agent_jobs row only when the same work is not already pending.

The bug class this closes (2026-07-23 queue audit, re-found 2026-09-25 when refreshing PR #165):
producers insert with a fresh uuid4 / timestamped id plus ``ON CONFLICT DO NOTHING`` — the PK is
new on every call, so the conflict clause can never fire and nothing dedups against work that is
already queued. Measured then: health_agent_remediation 434 rows across 2 symbols at priority 1
(jumping the queue), social_scalp_scanner 1,250 queued across 50 symbols (93 identical NVDA rows).

The guard key is the WORK, not the row id: (symbol, request_type) plus requested_agent when the
producer names one. Pending means any status in ``PENDING_STATUSES``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

PENDING_STATUSES: tuple[str, ...] = ("queued", "pending", "processing")


def build_guarded_insert(
    columns: Mapping[str, Any],
    *,
    raw_columns: Optional[Mapping[str, str]] = None,
    match_agent: bool = True,
    returning: str = "id",
) -> tuple[str, list[Any]]:
    """Return (sql, params) for ``INSERT … SELECT … WHERE NOT EXISTS (pending same work)``.

    ``columns`` are bound as parameters; ``raw_columns`` are SQL expressions (e.g. ``NOW()``)
    inserted verbatim — never pass caller-controlled text there. ``columns`` must include
    ``symbol`` and ``request_type``; ``requested_agent`` is part of the key when ``match_agent``.
    """
    if "symbol" not in columns or "request_type" not in columns:
        raise ValueError("guarded insert needs symbol and request_type")
    if match_agent and "requested_agent" not in columns:
        raise ValueError("match_agent=True needs requested_agent")
    raw_columns = dict(raw_columns or {})
    names = list(columns) + list(raw_columns)
    select_items = ["%s"] * len(columns) + list(raw_columns.values())
    params: list[Any] = list(columns.values())

    where = ["UPPER(w.symbol) = UPPER(%s)", "w.request_type = %s"]
    params += [columns["symbol"], columns["request_type"]]
    if match_agent:
        where.append("w.requested_agent = %s")
        params.append(columns["requested_agent"])
    where.append("w.status IN (" + ", ".join(["%s"] * len(PENDING_STATUSES)) + ")")
    params += list(PENDING_STATUSES)

    sql = (
        f"INSERT INTO watchlist_agent_jobs ({', '.join(names)}) "
        f"SELECT {', '.join(select_items)} "
        f"WHERE NOT EXISTS (SELECT 1 FROM watchlist_agent_jobs w WHERE {' AND '.join(where)})"
    )
    if returning:
        sql += f" RETURNING {returning}"
    return sql, params


def insert_agent_job_unless_pending(
    cur,
    columns: Mapping[str, Any],
    *,
    raw_columns: Optional[Mapping[str, str]] = None,
    match_agent: bool = True,
) -> Optional[Any]:
    """Insert and return the new id, or None when the same work is already pending."""
    sql, params = build_guarded_insert(columns, raw_columns=raw_columns, match_agent=match_agent)
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row, Sequence) and not isinstance(row, str) else row.get("id")


__all__ = ["PENDING_STATUSES", "build_guarded_insert", "insert_agent_job_unless_pending"]
