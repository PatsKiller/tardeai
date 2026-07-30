"""Read-only PostgreSQL reader adapter tests (fake DB-API backend).

Proves the reader is strictly read-only (never commits), verifies role identity,
projects the append-only journal into retrieval evidence and monitoring events,
joins reviews/scores through artifacts, and drives the read-only API end to end.
"""
from __future__ import annotations

import json
import re

import pytest

from scripts.agent_runtime.persistence import RUN_EVENT_TYPE, RuntimeIdentityError
from scripts.agent_runtime.read_api import READ_ROUTES, ReadOnlyAgentRuntimeAPI
from scripts.agent_runtime.read_postgres import PostgresAgentRuntimeReader

RUN = "ta:run:0123456789abcdef0123456789abcdef"


class FakeCluster:
    def __init__(self, current_user="agentic_runtime_lab_ro", role_flags=(False, False, False, False, False)):
        self.current_user = current_user
        self.role_flags = role_flags
        self.agent_runs = []
        self.agent_artifacts = []
        self.agent_tool_calls = []
        self.agent_reviews = []
        self.agent_scores = []


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = []

    def execute(self, sql, params=()):
        c = self.conn.cluster
        s = " ".join(sql.split())
        self._result = []
        if s.startswith("SET TRANSACTION READ ONLY"):
            self.conn.read_only = True
            return
        if s.startswith("SET LOCAL statement_timeout"):
            assert self.conn.read_only, "statement_timeout set before READ ONLY"
            return
        if s.startswith("SELECT current_user, rolsuper"):
            self._result = [(c.current_user, *c.role_flags)]
            return
        assert self.conn.read_only, f"query issued outside a READ ONLY transaction: {s[:60]}"
        cols = _select_cols(s)
        if "FROM agentic_runtime.agent_runs" in s:
            rows = list(c.agent_runs)
            if "WHERE run_id=%s" in s:
                rows = [r for r in rows if r["run_id"] == params[0]]
            else:  # list_runs: (agent_id, agent_id, status, status, limit, offset)
                agent_id, status, limit, offset = params[0], params[2], params[4], params[5]
                if agent_id is not None:
                    rows = [r for r in rows if r.get("agent_id") == agent_id]
                if status is not None:
                    rows = [r for r in rows if r.get("status") == status]
                rows = sorted(rows, key=lambda r: (r.get("started_at", ""), r["run_id"]), reverse=True)
                rows = rows[offset:offset + limit]
            self._result = _project(rows, cols)
            return
        if "FROM agentic_runtime.agent_artifacts" in s and "artifact_type=%s" in s:  # run-event rows
            run_id, atype = params[0], params[1]
            rows = [r for r in c.agent_artifacts if r["run_id"] == run_id and r["artifact_type"] == atype]
            self._result = [(_jsonb(r["payload"]), r["payload_hash"], r["created_at"]) for r in rows]
            return
        if "FROM agentic_runtime.agent_artifacts" in s and "artifact_type <> %s" in s:  # material artifacts
            run_id, atype = params[0], params[1]
            rows = [r for r in c.agent_artifacts if r["run_id"] == run_id and r["artifact_type"] != atype]
            self._result = _project(rows, cols)
            return
        if "FROM agentic_runtime.agent_tool_calls" in s:
            rows = [r for r in c.agent_tool_calls if r["run_id"] == params[0]]
            self._result = _project(rows, cols)
            return
        if "FROM agentic_runtime.agent_reviews" in s:
            art_ids = {a["artifact_id"] for a in c.agent_artifacts if a["run_id"] == params[0]}
            rows = [r for r in c.agent_reviews if r["artifact_id"] in art_ids]
            self._result = _project(rows, [col.split(".")[-1] for col in cols])
            return
        if "FROM agentic_runtime.agent_scores" in s:
            art_ids = {a["artifact_id"] for a in c.agent_artifacts if a["run_id"] == params[0]}
            rows = [r for r in c.agent_scores if r["artifact_id"] in art_ids]
            self._result = _project(rows, [col.split(".")[-1] for col in cols])
            return
        if "FROM agentic_runtime.kb_lessons" in s or "FROM agentic_runtime.kb_cases" in s:
            self._result = _project(list(getattr(c, "kb_lessons", []) if "kb_lessons" in s else getattr(c, "kb_cases", [])), cols)
            return
        raise AssertionError(f"unhandled SQL: {s}")

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cluster):
        self.cluster = cluster
        self.read_only = False
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _select_cols(sql):
    m = re.search(r"SELECT (.+?) FROM ", sql)
    return [c.strip() for c in m.group(1).split(",")]


def _project(rows, cols):
    return [tuple(r.get(col) for col in cols) for r in rows]


def _jsonb(value):
    return value if isinstance(value, (dict, list)) else json.loads(value)


def _factory(cluster):
    conns = []

    def make():
        conn = FakeConnection(cluster)
        conns.append(conn)
        return conn

    make.conns = conns
    return make


def _seed(cluster):
    cluster.agent_runs.append({
        "run_id": RUN, "agent_id": "tradeai.agent.sentinel", "agent_version": "1.0", "job_type": "research",
        "environment": "SHADOW", "status": "COMPLETED", "input_hash": "a" * 64, "validation_hash": "a" * 64,
        "retrieval_count": 1, "model_calls": 1, "tool_calls": 1, "cost_usd": 0.2, "checkpoint_seq": 7,
        "started_at": "2026-07-25T00:00:00+00:00", "updated_at": "2026-07-25T00:05:00+00:00", "completed_at": "2026-07-25T00:05:00+00:00",
    })
    cluster.agent_artifacts.append({
        "artifact_id": "art_1", "run_id": RUN, "producer_agent_id": "tradeai.agent.sentinel", "artifact_type": "analysis",
        "payload_hash": "b" * 64, "input_hash": "a" * 64, "validation_hash": "a" * 64,
        "prompt_version": "p", "provider_family": "local", "model": "m", "created_at": "2026-07-25T00:03:00+00:00",
    })
    cluster.agent_tool_calls.append({
        "tool_call_id": "tool_1", "run_id": RUN, "agent_id": "tradeai.agent.sentinel", "tool_name": "kb.search",
        "decision": "ALLOW", "decision_reason": "ok", "arguments_hash": "c" * 64, "result_hash": "d" * 64,
        "started_at": "2026-07-25T00:01:00+00:00", "completed_at": "2026-07-25T00:01:01+00:00",
    })
    cluster.agent_reviews.append({
        "review_id": "rev_1", "artifact_id": "art_1", "reviewer_agent_id": "tradeai.agent.iris",
        "verdict": "PASS", "artifact_hash": "b" * 64, "created_at": "2026-07-25T00:04:00+00:00",
    })
    cluster.agent_scores.append({
        "score_id": "score_1", "artifact_id": "art_1", "scorer_agent_id": "tradeai.agent.darwin",
        "dimensions": {"quality": 0.5}, "outcome_ref": None, "created_at": "2026-07-25T00:04:30+00:00",
    })
    for seq, etype, inner in (
        (1, "RUN_CREATED", {"status": "CREATED"}),
        (2, "RETRIEVAL_STARTED", {"query_hash": "e" * 64, "status": "RETRIEVING"}),
        (3, "RETRIEVAL_COMPLETED", {"retrieval_count": 1, "retrieval_hash": "f" * 64, "status": "READY_TO_REASON"}),
    ):
        cluster.agent_artifacts.append({
            "artifact_id": f"evt_{seq}", "run_id": RUN, "producer_agent_id": "tradeai.runtime",
            "artifact_type": RUN_EVENT_TYPE, "payload_hash": f"{seq:064d}",
            "payload": {"sequence": seq, "event_type": etype, "payload": inner, "previous_hash": "0" * 64, "created_at": f"2026-07-25T00:0{seq}:00+00:00"},
            "input_hash": "a" * 64, "validation_hash": "a" * 64, "created_at": f"2026-07-25T00:0{seq}:00+00:00",
        })


# --------------------------------------------------------------------------- #
def test_reader_implements_full_protocol_and_is_read_only():
    cluster = FakeCluster()
    _seed(cluster)
    factory = _factory(cluster)
    reader = PostgresAgentRuntimeReader(factory)

    runs = reader.list_runs(limit=10, offset=0)
    assert runs[0]["run_id"] == RUN and runs[0]["status"] == "COMPLETED"
    assert reader.get_run(RUN)["agent_id"] == "tradeai.agent.sentinel"
    assert reader.get_run("missing") is None
    assert [a["artifact_id"] for a in reader.list_artifacts(RUN)] == ["art_1"]  # sentinel rows excluded
    assert reader.list_tool_calls(RUN)[0]["tool_name"] == "kb.search"
    assert reader.list_reviews(RUN)[0]["verdict"] == "PASS"
    assert reader.list_scores(RUN)[0]["dimensions"] == {"quality": 0.5}

    # every data connection committed zero times and rolled back exactly once
    assert all(c.commits == 0 for c in factory.conns), "read-only reader must never commit"
    assert all(c.closed for c in factory.conns), "every connection is closed"


def test_retrieval_evidence_and_monitoring_events_projected_from_journal():
    cluster = FakeCluster()
    _seed(cluster)
    reader = PostgresAgentRuntimeReader(_factory(cluster))

    evidence = reader.list_retrieval_evidence(RUN)
    assert [e["event_type"] for e in evidence] == ["RETRIEVAL_STARTED", "RETRIEVAL_COMPLETED"]
    assert evidence[-1]["retrieval_count"] == 1 and evidence[-1]["retrieval_hash"] == "f" * 64

    events = reader.list_monitoring_events(RUN)
    assert [e["event_type"] for e in events] == ["RUN_CREATED", "RETRIEVAL_STARTED", "RETRIEVAL_COMPLETED"]
    assert [e["sequence"] for e in events] == [1, 2, 3]
    assert events[0]["event_hash"] == f"{1:064d}"


def test_reader_rejects_non_allowlisted_and_privileged_roles():
    cluster = FakeCluster(current_user="postgres")
    with pytest.raises(RuntimeIdentityError):
        PostgresAgentRuntimeReader(_factory(cluster)).get_run(RUN)

    superu = FakeCluster(current_user="agentic_runtime_lab_ro", role_flags=(True, False, False, False, False))
    with pytest.raises(RuntimeIdentityError):
        PostgresAgentRuntimeReader(_factory(superu)).get_run(RUN)


def test_read_api_over_postgres_reader_end_to_end_and_zero_authority():
    cluster = FakeCluster()
    _seed(cluster)
    api = ReadOnlyAgentRuntimeAPI(PostgresAgentRuntimeReader(_factory(cluster)))

    # every declared route resolves to a working method
    for route in READ_ROUTES:
        method = getattr(api, route.operation)
        result = method(limit=5) if route.operation in ("list_runs", "list_lessons", "list_cases") else method(RUN)
        assert result["read_only"] is True
        assert all(v is False for v in result["authority"].values())

    evidence = api.get_run_evidence(RUN)
    assert evidence["data"]["reviews"][0]["verdict"] == "PASS"
    assert {"create", "update", "delete", "cancel", "resume", "approve", "schedule", "execute"}.isdisjoint(dir(api))
