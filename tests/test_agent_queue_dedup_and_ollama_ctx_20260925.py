"""Refresh of PR #165: agent-job producers dedup against PENDING work; one Ollama num_ctx rule.

- The bug class: producers inserted watchlist_agent_jobs with a fresh uuid/timestamped id plus
  ``ON CONFLICT DO NOTHING``, which can never fire, so identical pending work stacked
  (2026-07-23: 93 identical NVDA rows; 434 remediation rows across 2 symbols).
- num_ctx: 12b must stay 4096 on the B50; a request whose ctx differs from the resident runner's
  forces a reload that wedges every other Ollama caller.

psycopg2-free: the guarded INSERT is exercised end to end on sqlite (paramstyle swapped).
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.agent_job_queue import PENDING_STATUSES, build_guarded_insert  # noqa: E402
from lib.ollama_ctx import canonical_num_ctx, resident_num_ctx  # noqa: E402


@pytest.fixture()
def db():
    if sqlite3.sqlite_version_info < (3, 35, 0):
        pytest.skip("sqlite RETURNING needs 3.35+")
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE watchlist_agent_jobs (id TEXT PRIMARY KEY, symbol TEXT, requested_agent TEXT,"
        " request_type TEXT, status TEXT, priority INT, note TEXT, created_at TEXT)"
    )
    return conn


def _insert(conn, cols, **kw):
    sql, params = build_guarded_insert(cols, **kw)
    return conn.execute(sql.replace("%s", "?"), params).fetchone()


def _job(i, **over):
    base = {
        "id": f"j{i}",
        "symbol": "nvda",
        "requested_agent": "maria",
        "request_type": "research",
        "status": "queued",
        "priority": 5,
    }
    base.update(over)
    return base


def test_second_identical_pending_job_is_skipped(db):
    assert _insert(db, _job(1)) == ("j1",)
    assert _insert(db, _job(2, symbol="NVDA")) is None  # case-insensitive symbol
    assert db.execute("SELECT COUNT(*) FROM watchlist_agent_jobs").fetchone()[0] == 1


def test_different_agent_or_request_type_is_new_work(db):
    _insert(db, _job(1))
    assert _insert(db, _job(2, requested_agent="steph")) == ("j2",)
    assert _insert(db, _job(3, request_type="full_analysis")) == ("j3",)


def test_completed_work_does_not_block_a_new_job(db):
    _insert(db, _job(1, status="completed"))
    assert _insert(db, _job(2)) == ("j2",)


@pytest.mark.parametrize("status", PENDING_STATUSES)
def test_every_pending_status_blocks(db, status):
    _insert(db, _job(1, status=status))
    assert _insert(db, _job(2)) is None


def test_match_agent_false_dedups_across_agents(db):
    _insert(db, _job(1, request_type="social_discovery"), match_agent=False)
    assert _insert(db, _job(2, request_type="social_discovery", requested_agent="steph"), match_agent=False) is None


def test_raw_columns_are_sql_expressions(db):
    row = _insert(db, _job(1), raw_columns={"created_at": "'2026-09-25'"})
    assert row == ("j1",)
    assert db.execute("SELECT created_at FROM watchlist_agent_jobs").fetchone()[0] == "2026-09-25"


def test_missing_key_columns_refused():
    with pytest.raises(ValueError):
        build_guarded_insert({"id": "x", "symbol": "A"})
    with pytest.raises(ValueError):
        build_guarded_insert({"id": "x", "symbol": "A", "request_type": "r"})  # agent required by default


PRODUCERS = ["scripts/agent_event_router.py", "scripts/overnight_batch.py", "scripts/social_scalp_scanner.py"]


@pytest.mark.parametrize("path", PRODUCERS)
def test_no_producer_relies_on_a_dead_on_conflict(path):
    """INSERT INTO watchlist_agent_jobs … ON CONFLICT DO NOTHING can never fire on a fresh id."""
    text = (ROOT / path).read_text(encoding="utf-8")
    for m in re.finditer(r"INSERT INTO watchlist_agent_jobs(.{0,600}?)(?:\"\"\"|''')", text, re.S):
        assert "ON CONFLICT" not in m.group(1), f"{path}: dead ON CONFLICT guard on watchlist_agent_jobs"


def test_canonical_num_ctx(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    assert canonical_num_ctx("gemma3:12b") == 4096
    assert canonical_num_ctx("gemma3:27b") == 4096
    assert canonical_num_ctx("gemma3:4b") == 8192
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    assert canonical_num_ctx("gemma3:4b") == 6144
    assert canonical_num_ctx("gemma3:12b") == 4096  # never overridden upward for 12b
    monkeypatch.setenv("OLLAMA_NUM_CTX", "junk")
    assert canonical_num_ctx("gemma3:4b") == 8192


def test_resident_num_ctx():
    ps = [{"name": "gemma3:4b", "context_length": 8192}, {"name": "nomic-embed-text"}]
    assert resident_num_ctx("gemma3:4b", ps_models=ps) == 8192
    assert resident_num_ctx("gemma3:12b", ps_models=ps) is None
    assert resident_num_ctx("nomic-embed-text", ps_models=ps) is None


@pytest.mark.parametrize(
    "path,forbidden",
    [
        ("scripts/monthly_advisory.py", '"num_ctx": 16384'),
        ("scripts/high_llm_execution_worker.py", '"num_ctx": 512'),
        ("scripts/hermes_backlog_drain.py", '"num_ctx": 8192'),
        ("scripts/claude_escalation_handler.py", '"num_ctx": 4096}'),
    ],
)
def test_callers_no_longer_hardcode_a_mismatched_ctx(path, forbidden):
    assert forbidden not in (ROOT / path).read_text(encoding="utf-8")
