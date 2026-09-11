#!/usr/bin/env python3
"""Apply startup DDL without taking a lock to assert what is already true.

WHY THIS EXISTS
---------------
`ALTER TABLE t ADD COLUMN IF NOT EXISTS c` takes an **AccessExclusiveLock** on `t`
even when `c` already exists. The `IF NOT EXISTS` suppresses the error, not the
lock. Three scripts ran that against `material_changes` on every scheduled run:

    notify_material_change.py     */15
    material_change_detector.py   */30
    due_diligence_questions.py    */20

which collide at :00 and :30. Each holds its own flock, and a flock protects
nothing against a *different* script.

On 2026-09-11 at 15:30Z that produced a real deadlock, and it produced it at the
worst possible moment: the notifier had already delivered an advisory to the
operator and died on the UPDATE that marks it consumed. The row stayed pending, so
the advisory was queued to be re-sent every fifteen minutes. Postgres reported

    process A waits for RowExclusiveLock, blocked by process B
    process B waits for AccessExclusiveLock, blocked by process A

The defect had been latent for as long as those schedules existed. It only became
reachable when the gateway started delivering, because before that `if accepted:`
was never true and the UPDATE was never attempted.

WHAT THIS DOES
--------------
Checks `information_schema` first — a catalog read, no table lock — and issues the
ALTER only when the column is genuinely absent. Steady state becomes zero
exclusive locks, so the collision has nothing to collide over.

WHAT THIS DOES NOT DO
---------------------
It is not a migration framework and does not pretend to parse SQL in general. It
recognises exactly one shape, `ALTER TABLE <t> ADD COLUMN IF NOT EXISTS <c> ...`,
and passes everything else through untouched. Anything it does not recognise
executes exactly as before, so this can only ever remove locks, never add one.
"""
from __future__ import annotations

import re
from typing import Any

#: Precisely the statement shape that takes a lock to assert a no-op.
#: Deliberately narrow: a pattern that matched too much would silently skip DDL
#: that actually needed to run, which is a far worse failure than a stray lock.
_ADD_COLUMN_RE = re.compile(
    r"""^\s*ALTER\s+TABLE\s+
         (?:IF\s+EXISTS\s+)?
         (?P<table>[A-Za-z_][A-Za-z0-9_]*)\s+
         ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+
         (?P<column>[A-Za-z_][A-Za-z0-9_]*)\b""",
    re.IGNORECASE | re.VERBOSE,
)


def _strip_leading_comments(stmt: str) -> str:
    """Drop leading `--` lines and blank lines from a statement.

    Without this the matcher anchors on the wrong token. The real DDL that caused
    the 15:30Z deadlock is preceded by three explanatory comment lines:

        -- CREATE TABLE IF NOT EXISTS does NOT add columns to a table that ...
        -- every column added after the first deploy needs its own ALTER. ...
        ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS precedence INTEGER;

    A pattern anchored at `^\\s*ALTER` does not match that, so the statement falls
    through to the passthrough branch and takes the AccessExclusiveLock anyway —
    the guard would have reported success while changing nothing for the very job
    whose schedule collided at :30.
    """
    lines = stmt.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("--")):
        i += 1
    return "\n".join(lines[i:])


def _statements(ddl: str) -> list[str]:
    """Split on `;` at statement level.

    These DDL blocks are plain CREATE/ALTER with no function bodies or dollar
    quoting, so a naive split is correct here. `assert_simple_ddl` enforces that
    assumption rather than leaving it as a comment nobody rechecks.
    """
    return [s.strip() for s in ddl.split(";") if s.strip()]


def assert_simple_ddl(ddl: str) -> None:
    """Refuse to touch DDL this splitter cannot safely reason about."""
    if "$$" in ddl or "$BODY$" in ddl.upper():
        raise ValueError(
            "ddl_guard cannot split dollar-quoted DDL; apply it directly instead"
        )


def column_exists(cur: Any, table: str, column: str) -> bool:
    """Catalog read. Takes no lock on `table`."""
    cur.execute(
        """SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            LIMIT 1""",
        (table, column),
    )
    return cur.fetchone() is not None


def apply_ddl(cur: Any, ddl: str) -> dict[str, Any]:
    """Execute `ddl`, skipping ADD COLUMN statements that are already satisfied.

    Returns a report naming what ran and what was skipped. The counts are
    deliberately separate: `skipped` means "already true, no lock taken" and
    `executed` means "the database changed". Collapsing them into one number
    would be the exact defect this campaign kept finding — one counter carrying
    two meanings.
    """
    assert_simple_ddl(ddl)
    executed: list[str] = []
    skipped: list[str] = []

    for stmt in _statements(ddl):
        m = _ADD_COLUMN_RE.match(_strip_leading_comments(stmt))
        if m and column_exists(cur, m.group("table"), m.group("column")):
            skipped.append(f"{m.group('table')}.{m.group('column')}")
            continue
        cur.execute(stmt)
        executed.append(stmt.split("\n", 1)[0][:60])

    return {
        "executed": executed,
        "skipped_already_present": skipped,
        "exclusive_locks_avoided": len(skipped),
    }
