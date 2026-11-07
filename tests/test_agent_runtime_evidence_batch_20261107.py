"""The fleet-level evidence batch that replaces the Runtime desk's per-run fan-out.

Defect (2026-11-07, LQ-20261107-90): /v3/agents/classic issued 173 API calls per load.
`agentRuntimeDetailAdapter.resolveAgentRuntimeDetail` read `/runs?limit=200`, then walked
the newest fifty runs issuing `runs/{id}/artifacts`, `runs/{id}/reviews` and
`runs/{id}/scores` for each — 150 requests at 4-5 s apiece, repeated on every agent
selection, against a server already at its memory ceiling.

`GET /api/v3/agent-runtime/evidence?limit=N` answers the same question once: the newest N
runs plus their artifacts, reviews and scores, grouped by run. A reader that implements
`list_run_evidence_batch` answers with three set-based statements; a reader that does not
still answers in one request.

These tests prove the batch exists, is bounded, is GET-only, keeps its zero authority,
fails closed on secret material, and returns exactly the evidence the per-run fan-out
returned — nothing missing, nothing invented.
"""
from __future__ import annotations

import re

import pytest

from scripts.agent_runtime import read_http
from scripts.agent_runtime.read_api import READ_ROUTES, ReadOnlyAgentRuntimeAPI
from scripts.agent_runtime.read_postgres import PostgresAgentRuntimeReader

RUNS = [f"ta:run:{i:032d}" for i in range(50)]
BATCH_PATH = "/api/v3/agent-runtime/evidence"


def _run_row(run_id: str) -> dict:
    return {"run_id": run_id, "agent_id": "tradeai.agent.sentinel", "status": "COMPLETED"}


class PerRunReader:
    """Implements only the per-run protocol — no batch method."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def list_runs(self, *, limit, offset, agent_id=None, status=None):
        return [_run_row(r) for r in RUNS[:limit]]

    def get_run(self, run_id):
        return _run_row(run_id)

    def list_artifacts(self, run_id):
        self.calls.append(("artifacts", run_id))
        return [{"artifact_id": f"art-{run_id}", "producer_agent_id": "tradeai.agent.sentinel",
                 "artifact_type": "analysis", "payload_hash": "h"}]

    def list_reviews(self, run_id):
        self.calls.append(("reviews", run_id))
        return [{"review_id": f"rev-{run_id}", "artifact_id": f"art-{run_id}", "verdict": "PASS"}]

    def list_scores(self, run_id):
        self.calls.append(("scores", run_id))
        return [{"score_id": f"score-{run_id}", "artifact_id": f"art-{run_id}"}]

    def list_retrieval_evidence(self, run_id):
        return []

    def list_tool_calls(self, run_id):
        return []

    def list_monitoring_events(self, run_id):
        return []

    def list_lessons(self, *, limit, offset=0):
        return []

    def list_cases(self, *, limit, offset=0):
        return []


class BatchReader(PerRunReader):
    """Implements the optional batch method; records how often the reader was entered."""

    def __init__(self) -> None:
        super().__init__()
        self.batch_calls: list[list[str]] = []

    def list_run_evidence_batch(self, run_ids):
        self.batch_calls.append(list(run_ids))
        return {
            rid: {
                "artifacts": [{"artifact_id": f"art-{rid}", "artifact_type": "analysis"}],
                "reviews": [{"review_id": f"rev-{rid}", "artifact_id": f"art-{rid}", "verdict": "PASS"}],
                "scores": [{"score_id": f"score-{rid}", "artifact_id": f"art-{rid}"}],
            }
            for rid in run_ids
        }


# --------------------------------------------------------------------------- #
# The batch is declared, dispatched and bounded
# --------------------------------------------------------------------------- #
def test_batch_route_is_declared_and_matched():
    operations = [route.operation for route in READ_ROUTES]
    assert "batch_run_evidence" in operations
    route, params = read_http._match(BATCH_PATH)
    assert route is not None and route.operation == "batch_run_evidence"
    assert params == {}


def test_dispatch_answers_the_batch_in_one_call():
    reader = BatchReader()
    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(reader), "GET", BATCH_PATH, {"limit": ["50"]})
    assert status == 200
    assert body["read_only"] is True
    assert all(v is False for v in body["authority"].values())
    assert body["kind"] == "run_evidence_batch"
    data = body["data"]
    assert [r["run_id"] for r in data["runs"]] == RUNS
    assert set(data["evidence"]) == set(RUNS)
    assert data["evidence"][RUNS[0]]["reviews"][0]["verdict"] == "PASS"
    # One batched read; the per-run path was never entered.
    assert len(reader.batch_calls) == 1 and len(reader.batch_calls[0]) == 50
    assert reader.calls == []


def test_dispatch_defaults_to_the_newest_fifty_runs():
    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(BatchReader()), "GET", BATCH_PATH, {})
    assert status == 200
    assert body["page"]["limit"] == 50
    assert len(body["data"]["runs"]) == 50


def test_dispatch_clamps_a_larger_limit_to_the_hard_bound():
    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(BatchReader()), "GET", BATCH_PATH, {"limit": ["1000"]})
    assert status == 200
    assert body["page"]["limit"] == read_http.MAX_LIMIT


@pytest.mark.parametrize("limit", ["0", "-1", "not-a-number"])
def test_dispatch_rejects_a_bad_limit_with_400(limit):
    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(BatchReader()), "GET", BATCH_PATH, {"limit": [limit]})
    assert status == 400
    assert body["data"] is None and body["read_only"] is True


def test_api_rejects_a_limit_outside_the_bound():
    api = ReadOnlyAgentRuntimeAPI(BatchReader())
    with pytest.raises(ValueError):
        api.batch_run_evidence(limit=0)
    with pytest.raises(ValueError):
        api.batch_run_evidence(limit=201)


# --------------------------------------------------------------------------- #
# GET-only, zero authority, fail closed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_batch_is_get_only(method):
    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(BatchReader()), method, BATCH_PATH, {})
    assert status == 405
    assert body["data"] is None and body["read_only"] is True


def test_batch_requires_a_connected_reader():
    status, body = read_http.dispatch(None, "GET", BATCH_PATH, {})
    assert status == 503
    assert body["data"] is None and body["connected"] is False


def test_a_secret_bearing_batched_row_fails_closed():
    class Leaky(BatchReader):
        def list_run_evidence_batch(self, run_ids):
            return {rid: {"artifacts": [{"artifact_id": "a", "api_token": "leaked"}],
                          "reviews": [], "scores": []} for rid in run_ids}

    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(Leaky()), "GET", BATCH_PATH, {"limit": ["1"]})
    assert status == 400
    assert body["data"] is None
    assert "leaked" not in str(body)


# --------------------------------------------------------------------------- #
# Equivalence with the per-run fan-out it replaces
# --------------------------------------------------------------------------- #
def test_fallback_reader_answers_once_with_the_same_evidence():
    """A reader with no batch method still answers in ONE response, and the desk sees the
    same three row sets it used to fetch per run."""
    reader = PerRunReader()
    status, body = read_http.dispatch(ReadOnlyAgentRuntimeAPI(reader), "GET", BATCH_PATH, {"limit": ["50"]})
    assert status == 200
    evidence = body["data"]["evidence"]
    assert set(evidence) == set(RUNS)
    for rid in RUNS:
        assert evidence[rid]["artifacts"][0]["artifact_id"] == f"art-{rid}"
        assert evidence[rid]["reviews"][0]["artifact_id"] == f"art-{rid}"
        assert evidence[rid]["scores"][0]["artifact_id"] == f"art-{rid}"
    # The per-run methods still ran server-side (once each, per run) — but the client made one call.
    assert len(reader.calls) == 3 * len(RUNS)


# --------------------------------------------------------------------------- #
# The Postgres reader does the batching in SQL, in one transaction
# --------------------------------------------------------------------------- #
class _RecordingCursor:
    def __init__(self, sink: list[str]) -> None:
        self.sink = sink
        self._rows: list[tuple] = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.sink.append(s)
        self._rows = []
        if s.startswith("SELECT current_user"):
            self._rows = [("agentic_runtime_reader", False, False, False, False, False)]
        return None

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _RecordingConn:
    def __init__(self, sink: list[str]) -> None:
        self.sink = sink
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return _RecordingCursor(self.sink)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_postgres_reader_fetches_all_three_kinds_with_set_based_queries():
    statements: list[str] = []
    conns: list[_RecordingConn] = []

    def factory():
        conn = _RecordingConn(statements)
        conns.append(conn)
        return conn

    # Identity verification opens its own connection; the batch itself must use exactly one.
    reader = PostgresAgentRuntimeReader(factory, verify_identity=False)
    grouped = reader.list_run_evidence_batch(RUNS)

    selects = [s for s in statements if s.startswith("SELECT") and "FROM agentic_runtime" in s]
    assert len(selects) == 3, statements
    assert all("run_id = ANY(%s)" in s for s in selects), selects
    assert not any(re.search(r"run_id\s*=\s*%s", s) for s in selects), "a per-run query slipped in"
    # One connection for the whole batch, never committed.
    assert len(conns) == 1 and conns[0].commits == 0 and conns[0].rollbacks >= 1
    assert set(grouped) == set(RUNS)
    assert all(set(v) == {"artifacts", "reviews", "scores"} for v in grouped.values())


def test_postgres_reader_batch_of_nothing_issues_no_query():
    statements: list[str] = []
    reader = PostgresAgentRuntimeReader(lambda: _RecordingConn(statements))
    assert reader.list_run_evidence_batch([]) == {}
    assert statements == []
