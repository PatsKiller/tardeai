"""LQ-20261107-1686 — an up-to-date accounting schema costs no DDL and no table lock.

``scripts/lib/llm_consumption.py::ensure_schema()`` used to run on every process start and issue 23
statements whose effect was already achieved. ``IF NOT EXISTS`` suppresses the error, not the lock:
each ``ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS`` asked for an ACCESS EXCLUSIVE lock
on the table every LLM call appends to, and every reader holds a 3 s ``lock_timeout``. Between 14:18
and 15:19 ET on 2026-11-09 that produced 124 lock timeouts and 5 deadlocks.

These tests drive the real ``ensure_schema`` against a fake cursor that answers catalog reads the way
PostgreSQL would (``information_schema.columns`` for a column, ``to_regclass`` for a relation) and
records every statement. Nothing here touches a database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib import llm_consumption as lc  # noqa: E402

#: The columns the module is responsible for adding after the tables exist. The base columns are part
#: of each CREATE TABLE, so no probe asks about them individually.
_LOG_COLUMNS = (
    "relative_units", "cost_basis", "pricing_effective_at", "reasoning_tokens", "cache_hit_tokens",
    "cache_miss_tokens", "requested_policy", "executed_policy", "requested_model_id", "returned_model",
    "thinking", "reasoning_effort", "provider_request_id",
)

_RELATIONS = (
    "llm_consumption_log", "llm_process_config", "llm_cost_reservations",
    "idx_llm_consumption_log_created", "idx_llm_consumption_log_process",
    "idx_llm_cost_reservations_process",
)


class _Catalog:
    """What the database already holds, and every statement sent to it."""

    def __init__(self, relations=(), columns=()):
        self.relations = set(relations)
        self.columns = set(columns)          # {(table, column)}
        self.statements: list[str] = []
        self.ddl: list[str] = []
        self.fail_on: str | None = None      # substring: this statement raises

    def up_to_date(self) -> "_Catalog":
        self.relations |= set(_RELATIONS)
        self.columns |= {("llm_consumption_log", c) for c in _LOG_COLUMNS}
        self.columns |= {("llm_process_config", "daily_cost_cap_usd")}
        return self


class _FakeCursor:
    def __init__(self, catalog: _Catalog):
        self.catalog = catalog
        self._row = None

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.catalog.statements.append(text)
        if "information_schema.columns" in text:
            table, column = params
            self._row = (1,) if (table, column) in self.catalog.columns else None
            return
        if "to_regclass" in text:
            self._row = (params[0] in self.catalog.relations,)
            return
        self._row = None
        if text.split(" ", 1)[0].upper() in ("CREATE", "ALTER"):
            self.catalog.ddl.append(text)
        if self.catalog.fail_on and self.catalog.fail_on in text:
            raise RuntimeError(f"synthetic failure: {self.catalog.fail_on}")

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, catalog: _Catalog):
        self.cursor_obj = _FakeCursor(catalog)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _run(monkeypatch, catalog: _Catalog) -> _FakeConn:
    conn = _FakeConn(catalog)
    monkeypatch.setattr(lc, "_conn", lambda: conn)
    monkeypatch.setattr(lc, "_SCHEMA_OK", False)
    # The registry seed is DML (INSERT ... ON CONFLICT) against llm_process_config; it is not what this
    # ticket changes, and calling it would need a much larger fake.
    monkeypatch.setattr(lc, "_seed_registry", lambda: None)
    lc.ensure_schema()
    return conn


def test_an_up_to_date_schema_issues_no_ddl_at_all(monkeypatch):
    """The incident, pinned: 23 statements reduced to catalog reads, on every process start."""
    catalog = _Catalog().up_to_date()
    conn = _run(monkeypatch, catalog)

    assert catalog.ddl == [], f"DDL issued against an up-to-date schema: {catalog.ddl}"
    # One catalog read per statement the function used to issue — 6 relations (4 tables/indexes plus the
    # two llm_cost_reservations ones) and 14 columns — all of them lock-free. The commit still closes
    # the transaction the reads opened.
    assert len(catalog.statements) == 6 + 14
    assert conn.commits == 1


def test_a_missing_column_runs_exactly_that_one_alter(monkeypatch):
    """The guard must still add what is genuinely absent — a guard that skips everything is worse."""
    catalog = _Catalog().up_to_date()
    catalog.columns.discard(("llm_consumption_log", "provider_request_id"))
    _run(monkeypatch, catalog)

    assert len(catalog.ddl) == 1, catalog.ddl
    assert "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS provider_request_id" in catalog.ddl[0]


def test_a_missing_table_is_created_with_its_index_and_additive_columns(monkeypatch):
    """Fresh database: the CREATEs run, and so do the additive ALTERs the CREATE body does not carry."""
    catalog = _Catalog().up_to_date()
    catalog.relations.discard("llm_cost_reservations")
    catalog.relations.discard("idx_llm_cost_reservations_process")
    _run(monkeypatch, catalog)

    joined = "\n".join(catalog.ddl)
    assert "CREATE TABLE IF NOT EXISTS llm_cost_reservations" in joined
    assert "CREATE INDEX IF NOT EXISTS idx_llm_cost_reservations_process" in joined
    assert "ALTER TABLE llm_consumption_log" not in joined, "an up-to-date column was re-ALTERed"


def test_one_failing_column_does_not_abort_the_rest(monkeypatch):
    """The per-statement rollback the original loop had is kept: the guard removes locks, not isolation."""
    catalog = _Catalog().up_to_date()
    for column in ("reasoning_tokens", "cache_hit_tokens"):
        catalog.columns.discard(("llm_consumption_log", column))
    catalog.fail_on = "ADD COLUMN IF NOT EXISTS reasoning_tokens"
    conn = _run(monkeypatch, catalog)

    assert conn.rollbacks == 1
    # reasoning_tokens raised, and cache_hit_tokens was still added afterwards.
    assert any("cache_hit_tokens" in stmt for stmt in catalog.ddl), catalog.ddl
    assert conn.commits == 1


def test_the_guard_uses_the_shared_catalog_helper():
    """Pinned by name so a local re-implementation cannot drift from lib.ddl_guard's own tests."""
    assert lc.relation_exists.__module__.removeprefix("scripts.") == "lib.ddl_guard"
    assert lc.column_exists.__module__.removeprefix("scripts.") == "lib.ddl_guard"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
