"""A retention policy that errors is a policy that is NOT being enforced.

db_retention.py caught each table's exception, printed ERROR, and still exited 0.
aegis_steph_escalations and watchlist_agent_jobs had been failing their
foreign-key deletes on EVERY run -- unpruned, unreported -- while systemd logged
a clean success. "Exit code 0 is not evidence of work" (AGENTS.md rule 8).

These tests read the source rather than executing it: run() opens a real
database connection on the first line, so exercising it in CI would either need
a database or a mock deep enough to prove nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "scripts" / "db_retention.py").read_text()
TREE = ast.parse(SRC)


def _func(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found")


def test_failures_are_collected_not_just_printed():
    body = ast.unparse(_func("run"))
    assert "failures" in body, "per-table errors must be recorded, not only printed"
    assert "failures.append" in body


def test_run_returns_non_zero_when_a_policy_failed():
    body = ast.unparse(_func("run"))
    assert "return 1 if failures else 0" in body, (
        "a table whose delete errored means that policy did not run; the process "
        "must exit non-zero so the scheduler surfaces it"
    )


def test_the_exit_code_is_propagated_to_the_caller():
    assert "raise SystemExit(run(" in SRC, (
        "run()'s return value must become the process exit code, or the "
        "non-zero is discarded and the failure stays invisible"
    )


def test_the_unenforced_tables_are_named_in_the_output():
    body = ast.unparse(_func("run"))
    assert "RETENTION NOT ENFORCED" in body
    assert "join(sorted(failures))" in body, "name which tables, not just a count"


def test_an_empty_password_is_refused_rather_than_falling_back_to_pgpass():
    """libpq silently reads ~/.pgpass, then blames 'password authentication failed'."""
    body = ast.unparse(_func("_connect"))
    assert "DB_PASSWORD" in body
    assert "pgpass" in body.lower()
    assert "SystemExit" in body


def test_the_quarantine_archive_is_keyed_on_quarantined_at_not_created_at():
    """Archived rows keep their ORIGINAL created_at (2026-04-20 onward).

    A created_at window would have deleted the reversal path ~34 days out
    instead of 180.
    """
    assert '("analyst_consensus_history_quarantine_20260913", "quarantined_at", 180)' in SRC
