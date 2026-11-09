"""LQ-20261107-1566 — System pipeline-failures lists unrecovered failures only.

ANCHOR: PIPELINE_FAILURES_UNRECOVERED_LQ1566_20261109

Page defect 175: Command Center showed "Research indexer failed 4×" (and other
recovered lanes) because GET /api/v2/system/pipeline-failures counted every
failed pipeline_runs row in the window, including ``zombie run cleared``
bookkeeping and failures that already had a later success. health_agent's
execution_health score already ignored those; the System panel did not.

Hermetic: injects db_query rows / asserts SQL shape. No live DB write.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib import pipeline_failures as PF
from scripts.lib.pipeline_failure_counts import SUBSTANTIVE_FAILURE_FILTER

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def test_sql_requires_unrecovered_substantive_failures():
    """Fail-before on the pre-fix SQL: no NOT EXISTS, no zombie-note exclude, no substantive filter."""
    assert "NOT EXISTS" in PF.SQL
    assert "zombie run cleared" in PF.SQL
    assert "f.pipeline_key" in PF.SQL
    assert SUBSTANTIVE_FAILURE_FILTER in PF.SQL
    assert "NULLIF(NULLIF(f.summary->>'errors', '[]'), '')" in PF.SQL


def test_a_recovered_pipeline_is_not_listed():
    """Same shape the live panel had: rag_indexer zombies + later success must not appear."""

    def db_query(sql, params):
        assert "NOT EXISTS" in sql
        assert params == (24,)
        # Unrecovered query returns nothing when every failure has a later success.
        return []

    out = PF.project(db_query, hours=24, now=NOW)
    assert out["status"] == "OK"
    assert out["pipelines"] == []
    assert out["pipelines_failing"] == 0
    assert out["failed_runs"] == 0


def test_an_unrecovered_substantive_failure_still_lists():
    rows = [{
        "pipeline_key": "rag_indexer",
        "failed": 2,
        "last_failed_at": NOW - timedelta(hours=1),
        "last_error": "connection refused",
        "zombie_cleared": 0,
    }]
    out = PF.project(lambda s, p: rows, hours=24, now=NOW)
    assert out["pipelines_failing"] == 1
    assert out["failed_runs"] == 2
    assert out["pipelines"][0]["pipeline"] == "rag_indexer"
    assert out["pipelines"][0]["last_error"] == "connection refused"


def test_unreadable_db_stays_unavailable_never_empty_green():
    none = PF.project(lambda s, p: None, hours=24, now=NOW)
    assert none["status"] == "UNAVAILABLE" and none["pipelines"] is None
    boom = PF.project(lambda s, p: (_ for _ in ()).throw(RuntimeError("down")), hours=24, now=NOW)
    assert boom["status"] == "UNAVAILABLE" and "down" in boom["note"]
