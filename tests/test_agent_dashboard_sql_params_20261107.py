"""LQ-20261107-141: /api/v2/agent-dashboard must never put the agent parameter into SQL text.

The `agent` query parameter is operator- or attacker-supplied. Every query the handler
issues must carry it as a bound parameter, with LIKE wildcards escaped, and the
performance-history read must use the real column (`agent`, written by
scripts/update_agent_performance.py), not `agent_name`.

AUTHORITY: READ_ONLY_ADVISORY. Synthetic inputs only; the DB is replaced by a recorder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "zz' OR 1=1; DROP TABLE agent_performance_history; --"


@pytest.fixture()
def recorded(monkeypatch):
    import api_v2

    calls: list[tuple[str, object]] = []

    def _fake(sql, params=None, fetch="all"):
        calls.append((sql, params))
        return {} if fetch == "one" else []

    monkeypatch.setattr(api_v2, "_db_query", _fake)
    return api_v2, calls


def _run(api_v2, agent):
    return api_v2.handle("/api/v2/agent-dashboard", method="GET", body=None, query={"agent": [agent]})


def test_hostile_agent_never_reaches_sql_text(recorded):
    api_v2, calls = recorded
    _run(api_v2, HOSTILE)
    assert calls, "handler issued no queries; the recorder is not wired"
    for sql, _params in calls:
        assert "DROP TABLE" not in sql, sql
        assert "zz'" not in sql, sql


def test_agent_value_is_bound_as_a_parameter(recorded):
    api_v2, calls = recorded
    _run(api_v2, HOSTILE)
    bound = [p for sql, p in calls if "ILIKE" in sql]
    assert bound, "no ILIKE query recorded"
    for params in bound:
        flat = list(params.values()) if isinstance(params, dict) else list(params or [])
        assert any(isinstance(v, str) and "DROP TABLE" in v for v in flat), params


def test_like_wildcards_in_agent_are_escaped(recorded):
    api_v2, calls = recorded
    _run(api_v2, "a%b_c")
    for sql, params in calls:
        if "ILIKE" not in sql:
            continue
        assert "ESCAPE" in sql, sql
        flat = list(params.values()) if isinstance(params, dict) else list(params or [])
        values = [v for v in flat if isinstance(v, str) and "a" in v and "b" in v]
        assert values, params
        for v in values:
            assert "a\\%b\\_c" in v, v


def test_performance_history_reads_the_agent_column(recorded):
    api_v2, calls = recorded
    _run(api_v2, "steph")
    perf = [sql for sql, _ in calls if "agent_performance_history" in sql]
    assert perf, "performance history was not queried"
    for sql in perf:
        assert "agent_name" not in sql, sql
        assert "agent ILIKE" in sql, sql
