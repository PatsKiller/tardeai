#!/usr/bin/env python3
"""A lock taken to assert what is already true is still a lock.

`ALTER TABLE t ADD COLUMN IF NOT EXISTS c` takes an AccessExclusiveLock on `t`
even when `c` already exists. `IF NOT EXISTS` suppresses the error, not the lock.

On 2026-09-11T15:30Z that deadlocked the material-change notifier AFTER it had
already delivered an advisory to the operator, leaving the row unconsumed and
queued to be re-sent every fifteen minutes. Three scripts ran that DDL against
`material_changes` on overlapping schedules, each holding its own flock, which
protects nothing against a different script.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.ddl_guard import (  # noqa: E402
    apply_ddl,
    assert_simple_ddl,
    column_exists,
)

COVERS = ["scripts/lib/ddl_guard.py"]


class FakeCur:
    """Records every statement, and answers information_schema from a set."""

    def __init__(self, existing: set[tuple[str, str]]):
        self.existing = existing
        self.executed: list[str] = []
        self._result = None

    def execute(self, sql, params=None):
        if "information_schema.columns" in sql:
            self._result = (1,) if (params[0], params[1]) in self.existing else None
            return
        self.executed.append(" ".join(sql.split()))
        self._result = None

    def fetchone(self):
        return self._result


DDL = """
CREATE TABLE IF NOT EXISTS material_changes (id BIGSERIAL PRIMARY KEY);
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS notify_outcome TEXT;
"""


def test_the_alter_is_skipped_when_the_column_already_exists():
    """THE POINT. Steady state must take no exclusive lock."""
    cur = FakeCur({("material_changes", "notified_at"),
                   ("material_changes", "notify_outcome")})
    report = apply_ddl(cur, DDL)

    assert report["exclusive_locks_avoided"] == 2
    assert sorted(report["skipped_already_present"]) == [
        "material_changes.notified_at", "material_changes.notify_outcome"]
    assert not any("ALTER TABLE" in s.upper() for s in cur.executed), (
        "no ALTER may be issued when every column already exists"
    )
    # The CREATE TABLE IF NOT EXISTS still runs; it is not the lock offender.
    assert any("CREATE TABLE" in s.upper() for s in cur.executed)


def test_a_genuinely_missing_column_is_still_added():
    """Skipping must never mean the schema silently fails to converge."""
    cur = FakeCur({("material_changes", "notified_at")})
    report = apply_ddl(cur, DDL)

    assert report["skipped_already_present"] == ["material_changes.notified_at"]
    altered = [s for s in cur.executed if "ALTER TABLE" in s.upper()]
    assert len(altered) == 1 and "notify_outcome" in altered[0]


def test_a_clean_install_runs_everything():
    cur = FakeCur(set())
    report = apply_ddl(cur, DDL)
    assert report["exclusive_locks_avoided"] == 0
    assert len([s for s in cur.executed if "ALTER TABLE" in s.upper()]) == 2


def test_unrecognised_ddl_passes_through_untouched():
    """This can only ever REMOVE locks, never add or skip unknown work.

    A pattern that matched too much would silently skip DDL that genuinely needed
    to run — a far worse failure than a stray lock.
    """
    other = """
    ALTER TABLE material_changes DROP COLUMN legacy_col;
    CREATE INDEX IF NOT EXISTS ix_mc_symbol ON material_changes (symbol);
    ALTER TABLE material_changes ALTER COLUMN magnitude TYPE NUMERIC;
    """
    cur = FakeCur({("material_changes", "legacy_col")})
    report = apply_ddl(cur, other)
    assert report["skipped_already_present"] == []
    assert len(cur.executed) == 3, "every unrecognised statement must still execute"


def test_executed_and_skipped_are_separate_counters():
    """One counter carrying two meanings is this campaign's recurring defect.

    'already true, no lock taken' and 'the database changed' are different
    outcomes and must never be summed into a single number.
    """
    cur = FakeCur({("material_changes", "notified_at")})
    report = apply_ddl(cur, DDL)
    assert set(report) == {"executed", "skipped_already_present",
                           "exclusive_locks_avoided"}
    assert report["executed"] and report["skipped_already_present"]


def test_dollar_quoted_ddl_is_refused_rather_than_mis_split():
    """The splitter is naive by design; it must say so instead of guessing."""
    with pytest.raises(ValueError, match="dollar-quoted"):
        assert_simple_ddl("CREATE FUNCTION f() RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql;")


def test_column_exists_reads_the_catalog_not_the_table():
    """The check itself must not be the thing that takes a lock."""
    cur = FakeCur({("material_changes", "notified_at")})
    assert column_exists(cur, "material_changes", "notified_at") is True
    assert column_exists(cur, "material_changes", "nope") is False
    assert cur.executed == [], "a catalog read must not execute table DDL/DML"


COMMENTED_DDL = """
CREATE TABLE IF NOT EXISTS material_changes (id BIGSERIAL PRIMARY KEY);
-- CREATE TABLE IF NOT EXISTS does NOT add columns to a table that already exists, so
-- every column added after the first deploy needs its own ALTER. Without this the
-- INSERT fails with UndefinedColumn on exactly the installs that already work.
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS precedence INTEGER;
"""


def test_an_alter_behind_sql_comments_is_still_recognised():
    """THE BUG THIS GUARD ALMOST SHIPPED WITH.

    The real DDL in material_change_detector.py puts three `--` comment lines
    immediately before the ALTER. A matcher anchored at `^\\s*ALTER` does not match
    that, so the statement fell through to the passthrough branch and took the
    AccessExclusiveLock anyway.

    That is the worst possible failure for this guard: it would have reported
    success, the lock would still have been taken, and the job it failed to help
    is the `*/30` detector whose :30 collision caused the deadlock in the first
    place. Verified against the live catalog before and after.
    """
    cur = FakeCur({("material_changes", "precedence")})
    report = apply_ddl(cur, COMMENTED_DDL)

    assert report["skipped_already_present"] == ["material_changes.precedence"]
    assert report["exclusive_locks_avoided"] == 1
    assert not any("ALTER TABLE" in s.upper() for s in cur.executed), (
        "a commented-out preamble must not hide the ALTER from the guard"
    )


def test_comment_stripping_does_not_swallow_real_statements():
    """Stripping leading comments must not drop the statement itself."""
    cur = FakeCur(set())
    report = apply_ddl(cur, COMMENTED_DDL)
    altered = [s for s in cur.executed if "ALTER TABLE" in s.upper()]
    assert len(altered) == 1 and "precedence" in altered[0]
    assert report["exclusive_locks_avoided"] == 0
