"""Behavioral + Postgres-contract tests for the agent-runtime persistence slice.

The behavioral suite runs against BOTH backends (InMemoryPersistence and
PostgresPersistence driven by a faithful in-process FakeConnection) so the two
backends are proven to agree. Additional tests assert the Postgres SQL/transaction
contract (parameterization, statement_timeout, ON CONFLICT idempotency, fail-closed
rollback, runtime-identity guard).
"""

from __future__ import annotations

import itertools
import re
import threading

import pytest

from scripts.agent_runtime.contracts import (
    Artifact,
    BudgetPolicy,
    Environment,
    Review,
    ReviewVerdict,
    RunEnvelope,
    RunStatus,
    Score,
    canonical_hash,
    canonical_json,
)
from scripts.agent_runtime.persistence import (
    _APPEND_COLUMNS,
    GENESIS_HASH,
    InMemoryPersistence,
    PersistenceError,
    PostgresPersistence,
    TerminalRunError,
    derive_id,
)

H = "a" * 64  # a valid-looking sha256 hex


# --------------------------------------------------------------------------- #
# Faithful in-process DB-API fake: enough of PostgreSQL for the adapter to run
# end-to-end. It records SQL for contract assertions and enforces ON CONFLICT.
# --------------------------------------------------------------------------- #
_RUN_COLS = (
    "run_id", "agent_id", "agent_version", "job_type", "environment", "objective",
    "status", "input_hash", "validation_hash", "checkpoint_seq", "checkpoint", "budget",
    "cancellation_reason", "started_at", "updated_at", "completed_at",
)
_RUN_INSERT_COLS = (
    "run_id", "agent_id", "agent_version", "job_type", "environment", "objective", "status",
    "input_hash", "validation_hash", "checkpoint_seq", "checkpoint", "budget", "started_at", "updated_at",
)


def _maybe_json(value):
    if isinstance(value, str) and value[:1] in "{[":
        import json
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = []
        self.rowcount = -1

    def execute(self, sql, params=()):
        self.conn.sql_log.append((sql, params))
        s = " ".join(sql.split())
        self._result = []
        self.rowcount = -1
        if s.startswith("SET LOCAL statement_timeout"):
            self.conn.statement_timeout = params[0]
            return
        if s.startswith("SELECT current_user"):
            self._result = [(self.conn.current_user,)]
            return
        if s.startswith("SELECT") and "FROM agentic_runtime.agent_runs WHERE run_id" in s:
            row = self.conn.runs.get(params[0])
            if "FOR UPDATE" in s:
                self.conn.for_update_count += 1
            self._result = [tuple(row[c] for c in _RUN_COLS)] if row else []
            return
        if s.startswith("INSERT INTO agentic_runtime.agent_runs"):
            values = {c: _maybe_json(v) for c, v in zip(_RUN_INSERT_COLS, params)}
            if values["run_id"] in self.conn.runs:
                self.rowcount = 0
                return
            values.setdefault("cancellation_reason", None)
            values.setdefault("completed_at", None)
            self.conn.runs[values["run_id"]] = values
            self.rowcount = 1
            return
        if s.startswith("UPDATE agentic_runtime.agent_runs SET"):
            (status, seq, checkpoint, updated_at, completed_at, reason, run_id) = params
            row = self.conn.runs[run_id]
            row.update(status=status, checkpoint_seq=seq, checkpoint=_maybe_json(checkpoint),
                       updated_at=updated_at, completed_at=completed_at, cancellation_reason=reason)
            self.rowcount = 1
            return
        m = re.search(r"INSERT INTO agentic_runtime\.(\w+)", s)
        if m:
            table = m.group(1)
            cols = _APPEND_COLUMNS[table]
            row = {c: _maybe_json(v) for c, v in zip(cols, params)}
            store = self.conn.tables.setdefault(table, {})
            if table == "agent_artifacts":
                ukey = (row["run_id"], row["payload_hash"])
                if ukey in self.conn.artifact_unique:
                    self.rowcount = 0
                    return
                self.conn.artifact_unique.add(ukey)
                store[row["artifact_id"]] = row
            else:
                pk = cols[0]
                if row[pk] in store:
                    self.rowcount = 0
                    return
                store[row[pk]] = row
            self.rowcount = 1
            return
        m = re.search(r"SELECT (\w+) FROM agentic_runtime\.(\w+) WHERE run_id", s)
        if m:
            pk, table = m.group(1), m.group(2)
            rows = [r for r in self.conn.tables.get(table, {}).values() if r.get("run_id") == params[0]]
            order = "created_at" if "created_at" in s else "started_at"
            rows.sort(key=lambda r: (r.get(order) or "", r[pk]))
            self._result = [(r[pk],) for r in rows]
            return
        if "JOIN agentic_runtime.agent_artifacts" in s:
            m = re.search(r"SELECT c\.(\w+) FROM agentic_runtime\.(\w+) c", s)
            pk, table = m.group(1), m.group(2)
            arts = self.conn.tables.get("agent_artifacts", {})
            run_arts = {aid for aid, r in arts.items() if r.get("run_id") == params[0]}
            rows = [r for r in self.conn.tables.get(table, {}).values() if r.get("artifact_id") in run_arts]
            rows.sort(key=lambda r: (r.get("created_at") or "", r[pk]))
            self._result = [(r[pk],) for r in rows]
            return
        if "SELECT run_id FROM agentic_runtime.agent_artifacts WHERE artifact_id" in s:
            r = self.conn.tables.get("agent_artifacts", {}).get(params[0])
            self._result = [(r["run_id"],)] if r else []
            return
        raise AssertionError(f"unhandled SQL in fake: {s}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, current_user="agentic_runtime_lab_rw"):
        self.runs = {}
        self.tables = {}
        self.artifact_unique = set()
        self.sql_log = []
        self.commits = 0
        self.rollbacks = 0
        self.statement_timeout = None
        self.for_update_count = 0
        self.current_user = current_user
        self.fail_on = None  # substring: raise when executed

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ExplodingConnection(FakeConnection):
    """Raises a driver-style error on the first INSERT into a chosen table."""

    def __init__(self, explode_on):
        super().__init__()
        self._explode_on = explode_on

    def cursor(self):
        conn = self

        class C(FakeCursor):
            def execute(self, sql, params=()):
                if conn._explode_on in " ".join(sql.split()):
                    raise RuntimeError("simulated driver failure")
                return super().execute(sql, params)

        return C(self)


# --------------------------------------------------------------------------- #
# Backend fixtures — behavioral tests run against both.
# --------------------------------------------------------------------------- #
_counter = itertools.count()


def _clock():
    # Deterministic, strictly increasing timestamps for stable ordering.
    return f"2026-07-25T00:00:{next(_counter):02d}.000000+00:00"


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return InMemoryPersistence(clock=_clock)
    return PostgresPersistence(FakeConnection(), clock=_clock)


def make_envelope(run_id="run_alpha", agent_id="alpha_agent"):
    return RunEnvelope(
        run_id=run_id, agent_id=agent_id, agent_version="1.0.0", job_type="research",
        environment=Environment.LAB, objective="assess", input_hash=H, validation_hash=H,
    )


def make_artifact(run_id="run_alpha", producer="alpha_agent", payload=None, artifact_id="art_1"):
    payload = {"finding": "x"} if payload is None else payload
    return Artifact(
        artifact_id=artifact_id, run_id=run_id, producer_agent_id=producer, artifact_type="analysis",
        payload=payload, input_hash=H, validation_hash=H, retrieval_refs=("kb:1",),
        prompt_version="p1", provider_family="local", model="m1",
    )


# --------------------------------------------------------------------------- #
# Behavioral suite (both backends)
# --------------------------------------------------------------------------- #
def test_create_run_is_idempotent_and_conflict_detected(store):
    state = store.create_run(make_envelope(), BudgetPolicy())
    assert state.status == RunStatus.CREATED.value and state.sequence == 1
    again = store.create_run(make_envelope(), BudgetPolicy())  # identical -> no-op
    assert again.sequence == 1
    with pytest.raises(PersistenceError):
        bad = RunEnvelope(run_id="run_alpha", agent_id="alpha_agent", agent_version="1.0.0",
                          job_type="research", environment=Environment.LAB, objective="assess",
                          input_hash="b" * 64, validation_hash=H)
        store.create_run(bad, BudgetPolicy())


def test_journal_is_monotonic_and_hash_chained(store):
    store.create_run(make_envelope(), BudgetPolicy())
    store.record_artifact(make_artifact())
    events = store.journal("run_alpha")
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    previous = GENESIS_HASH
    for event in events:
        assert event.previous_hash == previous
        body = {"run_id": event.run_id, "sequence": event.sequence, "event_type": event.event_type,
                "payload": dict(event.payload), "created_at": event.created_at, "previous_hash": event.previous_hash}
        assert event.event_hash == canonical_hash(body)
        previous = event.event_hash


def test_artifact_idempotency_by_payload_hash(store):
    store.create_run(make_envelope(), BudgetPolicy())
    first = store.record_artifact(make_artifact())
    seq_after_first = store.reconstruct("run_alpha").sequence
    second = store.record_artifact(make_artifact())  # same payload -> idempotent
    assert first == second
    assert store.reconstruct("run_alpha").sequence == seq_after_first  # no new event
    assert store.reconstruct("run_alpha").artifacts == (first,)


def test_self_review_and_self_score_are_rejected(store):
    store.create_run(make_envelope(), BudgetPolicy())
    store.record_artifact(make_artifact())
    good_review = Review(review_id=derive_id("rev", 1), artifact_id="art_1", producer_agent_id="alpha_agent",
                         reviewer_agent_id="beta_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash=H)
    store.record_review("run_alpha", good_review)
    with pytest.raises((PersistenceError, ValueError)):
        Review(review_id=derive_id("rev", 2), artifact_id="art_1", producer_agent_id="alpha_agent",
               reviewer_agent_id="alpha_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash=H).validate()
    with pytest.raises((PersistenceError, ValueError)):
        Score(score_id=derive_id("sc", 1), artifact_id="art_1", producer_agent_id="alpha_agent",
              scorer_agent_id="alpha_agent", dimensions={"quality": 0.5}).validate()


def test_terminal_run_cannot_mutate_or_resume(store):
    store.create_run(make_envelope(), BudgetPolicy())
    store.complete_run("run_alpha")
    assert store.reconstruct("run_alpha").status == RunStatus.COMPLETED.value
    with pytest.raises(TerminalRunError):
        store.record_artifact(make_artifact(artifact_id="art_late", payload={"finding": "late"}))
    with pytest.raises(TerminalRunError):
        store.complete_run("run_alpha")
    with pytest.raises(TerminalRunError):
        store.fail_run("run_alpha", "nope")


def test_tool_call_lifecycle_events_and_idempotency(store):
    store.create_run(make_envelope(), BudgetPolicy())
    args_hash = canonical_hash({"q": 1})
    started = "2026-07-25T00:00:00.000000+00:00"
    common = dict(agent_id="alpha_agent", tool_name="kb.search", decision="ALLOW",
                  decision_reason="allowlisted", arguments_hash=args_hash, result_hash=H,
                  started_at=started, completed_at=started, terminal_state="completed")
    tc = store.record_tool_call("run_alpha", **common)
    assert tc == derive_id("tool_call", "run_alpha", "alpha_agent", "kb.search", args_hash, started)
    types = [e.event_type for e in store.journal("run_alpha")]
    assert "TOOL_PROPOSED" in types and "TOOL_STARTED" in types and "TOOL_COMPLETED" in types
    seq_before = store.reconstruct("run_alpha").sequence
    again = store.record_tool_call("run_alpha", **common)  # same identity -> idempotent no-op
    assert again == tc
    assert store.reconstruct("run_alpha").sequence == seq_before
    assert store.reconstruct("run_alpha").tool_calls == (tc,)


def test_secret_material_is_never_persisted(store):
    store.create_run(make_envelope(), BudgetPolicy())
    with pytest.raises((PersistenceError, ValueError)):
        store.record_artifact(make_artifact(payload={"password": "hunter2"}, artifact_id="art_secret"))


def test_reconstruct_from_evidence_lists_children(store):
    store.create_run(make_envelope(), BudgetPolicy())
    store.record_artifact(make_artifact())
    store.record_review("run_alpha", Review(review_id=derive_id("rev", 9), artifact_id="art_1",
                        producer_agent_id="alpha_agent", reviewer_agent_id="beta_agent",
                        verdict=ReviewVerdict.PASS, findings=(), artifact_hash=H))
    state = store.reconstruct("run_alpha")
    assert state.artifacts == ("art_1",)
    assert len(state.reviews) == 1


def test_concurrent_appends_stay_monotonic_and_unforked(store):
    store.create_run(make_envelope(), BudgetPolicy())
    errors = []

    def worker(i):
        try:
            store.record_artifact(make_artifact(payload={"finding": f"f{i}"}, artifact_id=f"art_{i}"))
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    events = store.journal("run_alpha")
    sequences = [e.sequence for e in events]
    assert sequences == sorted(set(sequences)) == list(range(1, len(events) + 1))  # monotonic, no dupes
    previous = GENESIS_HASH
    for event in events:  # single unbroken chain -> no fork
        assert event.previous_hash == previous
        previous = event.event_hash


# --------------------------------------------------------------------------- #
# Postgres SQL/transaction contract (FakeConnection)
# --------------------------------------------------------------------------- #
def test_postgres_uses_parameterized_sql_timeout_lock_and_commit():
    conn = FakeConnection()
    pg = PostgresPersistence(conn, clock=_clock, statement_timeout_ms=9999)
    pg.create_run(make_envelope(), BudgetPolicy())
    pg.record_artifact(make_artifact())
    assert conn.statement_timeout == 9999          # bounded statement_timeout set per txn
    assert conn.for_update_count >= 1              # chain serialized with SELECT ... FOR UPDATE
    assert conn.commits >= 2 and conn.rollbacks == 0
    # every executed value travels as a bound parameter, never string-formatted into SQL
    for sql, params in conn.sql_log:
        assert "hunter" not in sql
        assert isinstance(params, tuple)
    inserts = [sql for sql, _ in conn.sql_log if sql.startswith("INSERT")]
    assert all("ON CONFLICT" in sql for sql in inserts)


def test_postgres_rolls_back_and_raises_on_driver_failure():
    conn = ExplodingConnection(explode_on="INSERT INTO agentic_runtime.agent_runs")
    pg = PostgresPersistence(conn, clock=_clock)
    with pytest.raises(PersistenceError):
        pg.create_run(make_envelope(), BudgetPolicy())
    assert conn.rollbacks == 1 and conn.commits == 0  # failure never commits a checkpoint


def test_postgres_refuses_migration_identity():
    pg = PostgresPersistence(FakeConnection(current_user="agentic_lab_migrator"), clock=_clock)
    with pytest.raises(PersistenceError):
        pg.assert_runtime_only()
    ok = PostgresPersistence(FakeConnection(current_user="agentic_runtime_lab_rw"), clock=_clock)
    ok.assert_runtime_only()  # runtime identity is accepted


# --------------------------------------------------------------------------- #
# Optional: real isolated LAB Postgres (skips cleanly when unavailable)
# --------------------------------------------------------------------------- #
def test_real_lab_postgres_roundtrip_if_available():
    psycopg2 = pytest.importorskip("psycopg2")
    import os
    sock = "/home/johnclaw/tradeai-lab/sock"
    if not os.path.exists(sock):
        pytest.skip("isolated LAB cluster not present")
    try:
        conn = psycopg2.connect(host=sock, port=5433, dbname="trade_ai_agentic_lab",
                                user="agentic_runtime_lab_rw", options="-c search_path=agentic_runtime")
    except Exception:
        pytest.skip("LAB runtime role/db not provisioned for this run")
    try:
        pg = PostgresPersistence(conn, clock=_clock)
        env = make_envelope(run_id=f"run_it_{next(_counter)}")
        pg.create_run(env, BudgetPolicy())
        pg.record_artifact(make_artifact(run_id=env.run_id, artifact_id=f"art_{env.run_id}"))
        assert pg.reconstruct(env.run_id).status in {RunStatus.CREATED.value, RunStatus.REVIEW_REQUIRED.value}
    finally:
        conn.rollback()
        conn.close()
