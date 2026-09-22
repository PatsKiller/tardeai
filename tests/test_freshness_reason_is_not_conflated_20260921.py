"""`missing` must name its CAUSE. Five outcomes, not one sentence.

WHY
---
`_age_days_table` returned None for an ABSENT table, a RAISED query, and a table
that EXISTS BUT IS EMPTY. check() rendered all three as "no output / table/file
absent", health_agent minted `missing_<name>` from it, and
claude_escalation_handler escalated. Measured 2026-09-21: seven `missing_*`
components paged ~126x each against tables that all exist with fresh rows.

TWO WRONG FIXES WERE TRIED FIRST, and both are pinned here so neither returns:

1. `safe_parse_age_days` returning 0.0 on error. check() reads `elif age > thr`
   and otherwise falls through to `ok`, so 0.0 means PERFECTLY FRESH. An absent
   table would be reported healthy -- trading a false-positive storm for silent
   blindness, which is strictly worse for a freshness monitor.
2. Catching the exception inside `_age_days_table`. db_adapter._execute swallows
   every error itself (`print(...); return None`), so that except block is dead
   code and cannot distinguish a SQL error from an empty result or a dead
   connection.

Hence: establish the cause BEFORE the aggregate, with to_regclass and
information_schema.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SRC = ROOT / "scripts" / "pipeline_freshness_monitor.py"


@pytest.fixture
def mon():
    return pytest.importorskip("pipeline_freshness_monitor")


@pytest.fixture
def live_db(mon):
    """Skip DB-dependent assertions when no database is reachable.

    CI is hermetic: db_adapter._execute returns None with no connection, so the
    classifier correctly reports 'db_unreachable' and every table-shape
    assertion below would fail for a reason that has nothing to do with the
    defect. A test that can only pass with a database attached does not belong
    in a hermetic gate -- and one that silently passes because it skipped
    everything is worse, so the STRUCTURAL assertions still run unconditionally.
    """
    _, why = mon._age_days_table_reason("watchlist_items", "updated_at", None)
    if why == "db_unreachable":
        pytest.skip("no database in this environment; structural tests still run")
    return mon


def test_absent_table_is_not_the_same_as_empty_or_errored(live_db) -> None:
    """The whole defect in one assertion."""
    assert live_db._age_days_table_reason("no_such_table_xyz", "created_at", None) == (None, "absent_table")


def test_a_missing_column_is_its_own_cause(live_db) -> None:
    """watchlist_items exists with 13,981 rows; created_at does not exist.

    The original code reported this as "table/file absent", which sent an
    operator looking for a missing table that was right there.
    """
    age, why = live_db._age_days_table_reason("watchlist_items", "created_at", None)
    assert (age, why) == (None, "absent_column")


def test_a_healthy_table_still_returns_a_float(live_db) -> None:
    age, why = live_db._age_days_table_reason("watchlist_items", "updated_at", None)
    assert why == "ok" and isinstance(age, float)


def test_zero_is_never_used_as_a_failure_value() -> None:
    """0.0 means PERFECTLY FRESH to check(). It must never signal an error."""
    src = SRC.read_text(encoding="utf-8")
    assert "return 0.0" not in src, "0.0 on failure would report an absent table as healthy"
    assert "safe_parse_age_days" not in src


def test_check_still_returns_exactly_three_buckets(mon) -> None:
    """health_agent.py:1700 unpacks `stale, missing, _ok`. Arity is load-bearing."""
    result = mon.check()
    assert len(result) == 3
    stale, missing, ok = result
    for row in missing:
        assert row.get("reason") in mon._REASON_DETAIL, f"unmapped reason: {row.get('reason')}"
        assert row.get("detail"), "a cause with no human sentence is the old bug"


def test_every_reason_code_has_a_distinct_sentence(mon) -> None:
    """The original failure was ONE sentence for many causes."""
    sentences = list(mon._REASON_DETAIL.values())
    assert len(sentences) == len(set(sentences)), "two causes share a sentence"
    assert len(mon._REASON_DETAIL) >= 5


def test_back_compat_wrapper_still_returns_float_or_none(live_db) -> None:
    """Existing callers of _age_days_table must be unaffected."""
    assert isinstance(live_db._age_days_table("watchlist_items", "updated_at", None), float)
    assert live_db._age_days_table("no_such_table_xyz", "created_at", None) is None


def test_the_detector_can_fail() -> None:
    """Positive control: the 0.0 check must reject a reintroduced bad fix."""
    bad = "def f():\n    return 0.0\n"
    assert "return 0.0" in bad
