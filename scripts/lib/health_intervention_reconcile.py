"""Close escalation interventions that a later verified remediation superseded.

The escalation handler writes one ``claude_interventions`` row per remediation
attempt.  A retry that exits 0 but fails its post-retry verify is recorded as
``status='failed'`` — correct at the instant it is written — and nothing ever
revisits that row afterwards.  The Health Hub's Recent Changes feed
(``/api/v2/health/activity``) shows interventions for seven days, so an old
"retry exit 0 but verify failed: pipeline_still unrecovered=1 sla=0" keeps
reading as a live failure long after the pipeline recovered.

MEASURED 2026-11-07 (LQ-20261107-377).  Row 24557 was written at 14:01:30 ET
because the scorer's recovery run had not finished yet; row 24558 at 14:06:46 ET
verified the same component clear.  Both appeared on /v3.  Every one of the 484
``failed`` health rows in the preceding seven days had a later ``fixed`` row for
the same component — the stale row is the whole class, not one record.

The sweep is deliberately NOT item-driven.  ``process_queue`` returns before it
opens a connection when the escalation queue is empty, and an empty queue is
exactly the state the handler is in once a finding clears — so a sweep reachable
only through queued items can never see the rows this defect leaves behind.  It
runs at the top of every handler pass instead.

A row is superseded only when a LATER row for the SAME component is ``fixed``:
positive evidence that the condition it recorded did not persist.  ``resolved_at``
keeps the moment that later fix landed, so the feed stays in chronological order
and the superseded row does not jump to the top.
"""

from __future__ import annotations

import contextlib

# Candidate predicate. ``health:%`` matches the components the handler writes and
# the ones the activity feed lists. Rows already closed are excluded by status.
_CANDIDATES_SQL = """
    SELECT f.id, f.component,
           (SELECT MIN(s.created_at)
              FROM claude_interventions s
             WHERE s.component = f.component
               AND s.status = 'fixed'
               AND s.created_at > f.created_at) AS fixed_at
      FROM claude_interventions f
     WHERE f.status IN ('failed', 'investigating')
       AND f.component LIKE 'health:%%'
       AND COALESCE(f.resolved_at, f.created_at) > now() - make_interval(hours => %s)
       AND EXISTS (
             SELECT 1
               FROM claude_interventions s
              WHERE s.component = f.component
                AND s.status = 'fixed'
                AND s.created_at > f.created_at
       )
     ORDER BY f.created_at
     LIMIT %s
"""

# The two SET expressions whose types depend on the live columns. Shared with
# _SELECT_SHAPE_SQL so a test can prove them against the real schema without
# UPDATE privilege (EXPLAIN of an UPDATE needs it; this does not).
_SUPERSEDE_SOLUTION = (
    "left(COALESCE(solution, '') || ' — superseded by a later verified remediation', 2000)"
)

_SUPERSEDE_SQL = f"""
    UPDATE claude_interventions
       SET status = 'superseded',
           resolved_at = %s,
           solution = {_SUPERSEDE_SOLUTION}
     WHERE id = %s
       AND status IN ('failed', 'investigating')
"""

# Read-only mirror of the UPDATE's expressions: same columns, same assignments,
# narrowed to one id. Proves the statement type-checks against the live schema.
_SELECT_SHAPE_SQL = f"""
    SELECT resolved_at, {_SUPERSEDE_SOLUTION} AS solution
      FROM claude_interventions
     WHERE id = %s
       AND status IN ('failed', 'investigating')
"""

SUPERSEDED_STATUS = "superseded"
DEFAULT_WINDOW_HOURS = 168  # the activity feed's 7-day window
DEFAULT_LIMIT = 500


def reconcile_superseded(conn, *, window_hours: int = DEFAULT_WINDOW_HOURS, limit: int = DEFAULT_LIMIT,
                         dry_run: bool = False) -> dict:
    """Mark failed/investigating interventions superseded by a later verified fix.

    Returns ``{"candidates", "closed", "ids", "dry_run", "error"}``.  ``ids`` are the
    rows the sweep tried to close; ``closed`` is what the UPDATE actually touched (a
    row another pass closed in between is left alone by the WHERE guard).  Never
    raises: a reconciliation problem must not stop the escalation pass that hosts it.
    """
    result = {"candidates": 0, "closed": 0, "ids": [], "dry_run": bool(dry_run), "error": None}
    if conn is None:
        result["error"] = "no_db"
        return result
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(_CANDIDATES_SQL, (int(window_hours), int(limit)))
        rows = cur.fetchall() or []
        result["candidates"] = len(rows)
        result["ids"] = [r[0] for r in rows]  # attempted (== would-close on a dry run)
        if dry_run or not rows:
            conn.commit()
            return result
        # Per-row statements: the only exotic type left is the timestamp, and a single
        # bad row cannot take the whole batch down with it.
        cur.executemany(_SUPERSEDE_SQL, [(r[2], r[0]) for r in rows])
        touched = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else -1
        conn.commit()
        result["closed"] = len(rows) if touched < 0 else touched
        return result
    except Exception as exc:  # noqa: BLE001 — reconciliation must not break the pass
        result["error"] = f"{type(exc).__name__}: {exc}"
        try:
            conn.rollback()
        except Exception as rb_exc:
            # Report it: an un-rolled-back connection is the difference between "nothing
            # was written" and "an unknown amount was written".
            result["error"] += f" (rollback also failed: {type(rb_exc).__name__}: {rb_exc})"
        return result
    finally:
        if cur is not None:
            # Closing a cursor has no caller-visible failure mode: the outcome is already
            # in `result`, and a close error cannot undo or change what was committed.
            with contextlib.suppress(Exception):
                cur.close()
