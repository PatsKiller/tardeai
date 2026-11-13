"""Synthetic fixtures for the validation-gates tests: a sqlite stand-in built FROM the real migration files."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def sqlite_ddl(name: str) -> str:
    s = (ROOT / "migrations" / name).read_text(encoding="utf-8")
    s = re.sub(r"--[^\n]*", "", s)
    s = re.sub(r"\b(BEGIN|COMMIT);", "", s)
    s = s.replace("JSONB", "TEXT").replace("TIMESTAMPTZ", "TEXT").replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")
    return s.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")


class Cur:
    def __init__(self, c):
        self.c = c

    def execute(self, sql, params=()):
        self.c.execute(sql.replace("%s", "?"), tuple(params))

    def fetchone(self):
        return self.c.fetchone()

    def fetchall(self):
        return self.c.fetchall()

    @property
    def rowcount(self):
        return self.c.rowcount


class Conn:
    """Explicit transaction so SAVEPOINT / commit / rollback behave like Postgres."""

    def __init__(self):
        self.raw = sqlite3.connect(":memory:", isolation_level=None)
        for f in ("2026_11_12_validation_gates.sql", "2026_11_12_validation_events.sql"):
            self.raw.executescript(sqlite_ddl(f))
        self.raw.execute("BEGIN")

    def cursor(self):
        return Cur(self.raw.cursor())

    def commit(self):
        self.raw.execute("COMMIT")
        self.raw.execute("BEGIN")

    def rollback(self):
        self.raw.execute("ROLLBACK")
        self.raw.execute("BEGIN")

    def q(self, sql, params=()):
        return self.raw.execute(sql, params).fetchall()


def decl(gate_id="VG-T-1", **kw):
    d = {"schema": "ValidationGateDecl@v1", "gate_id": gate_id, "title": f"Gate {gate_id}", "category": "Order protection",
         "blocks": "Trading on acct-A", "blocks_trading": True, "due_at": "2026-11-12T12:00:00+00:00",
         "opened_at": "2026-11-12T08:00:00+00:00", "owner": "risk", "declared_by": "lead",
         "check_kind": "manual_evidence", "check_spec": {}}
    d.update(kw)
    return d
