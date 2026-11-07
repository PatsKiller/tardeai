"""PHASE_A_SCHEMA_NO_LOCK_20261107 (LQ-20261107-265): applied Phase A schema => no DDL, so no table lock."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import redeploy_phase_a_db as pa  # noqa: E402


class FakeCur:
    def __init__(self, tables=True, columns=len(pa.REQUIRED_DEPLOY_EVENT_COLUMNS), constraints=len(pa.REQUIRED_CONSTRAINTS)):
        self.answers = [(tables,), (columns,), (constraints,)]
        self.executed: list[str] = []
        self._last = None

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if "pg_constraint" in sql or "information_schema" in sql or "to_regclass" in sql:
            self._last = self.answers.pop(0)

    def fetchone(self):
        return self._last


def _ddl(cur):
    return [s for s in cur.executed if "ALTER TABLE" in s.upper() or "CREATE TABLE" in s.upper()]


def test_applied_schema_runs_no_ddl():
    cur = FakeCur()
    pa.ensure_phase_a_tables(cur)
    assert _ddl(cur) == []


def test_missing_table_runs_the_migration():
    cur = FakeCur(tables=False)
    pa.ensure_phase_a_tables(cur)
    assert _ddl(cur), "a missing table must still apply the migration"


def test_missing_column_runs_the_migration():
    cur = FakeCur(columns=3)
    pa.ensure_phase_a_tables(cur)
    assert _ddl(cur)


def test_missing_constraint_runs_the_migration():
    cur = FakeCur(constraints=1)
    pa.ensure_phase_a_tables(cur)
    assert _ddl(cur)


def test_dict_rows_are_understood():
    cur = FakeCur()
    cur.answers = [{"b": True}, {"c": 6}, {"c": 2}]
    pa.ensure_phase_a_tables(cur)
    assert _ddl(cur) == []
