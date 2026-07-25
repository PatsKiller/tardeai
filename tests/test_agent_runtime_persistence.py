"""Behavioral + Postgres-contract tests for the agent-runtime persistence slice.

The behavioral suite runs against BOTH backends: InMemoryPersistence and
PostgresPersistence driven by a transactional in-process FakeConnection (connection
factory + per-op snapshot with real commit/rollback), so the two backends are proven
to agree, including fail-closed rollback.
"""

from __future__ import annotations

import copy
import itertools
import json
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
)
from scripts.agent_runtime.persistence import (
    _APPEND_COLUMNS,
    _RUN_COLS,
    GENESIS_HASH,
    IdempotencyConflictError,
    InMemoryPersistence,
    PersistenceError,
    PostgresPersistence,
    RuntimeIdentityError,
    TerminalRunError,
    derive_id,
)

H = "a" * 64
_RUN_INSERT_COLS = ("run_id", "agent_id", "agent_version", "job_type", "environment", "objective", "status",
                    "input_hash", "validation_hash", "retrieval_count", "model_calls", "tool_calls", "cost_usd",
                    "checkpoint_seq", "checkpoint", "budget", "started_at", "updated_at")


def _maybe_json(value):
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


class FakeCluster:
    def __init__(self, current_user="agentic_runtime_lab_rw", role_flags=(False, False, False, False, False)):
        self.runs = {}
        self.tables = {t: {} for t in _APPEND_COLUMNS}
        self.current_user = current_user
        self.role_flags = role_flags
        self.commits = 0
        self.rollbacks = 0
        self.for_update = 0
        self.sql_log = []
        self.explode_on = None


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = []
        self.rowcount = -1

    def execute(self, sql, params=()):
        self.conn.cluster.sql_log.append((sql, params))
        s = " ".join(sql.split())
        self._result = []
        self.rowcount = -1
        assert isinstance(params, tuple)
        if s.startswith("SET LOCAL statement_timeout"):
            return
        if s.startswith("SELECT current_user, rolsuper"):
            self._result = [(self.conn.cluster.current_user, *self.conn.cluster.role_flags)]
            return
        if "FROM agentic_runtime.agent_runs WHERE run_id" in s:
            if "FOR UPDATE" in s:
                self.conn.cluster.for_update += 1
            row = self.conn.runs.get(params[0])
            self._result = [tuple(row.get(c) for c in _RUN_COLS)] if row else []
            return
        if s.startswith("INSERT INTO agentic_runtime.agent_runs"):
            vals = {c: _maybe_json(v) for c, v in zip(_RUN_INSERT_COLS, params)}
            if vals["run_id"] in self.conn.runs:
                self.rowcount = 0
                return
            vals.setdefault("cancellation_reason", None)
            vals.setdefault("completed_at", None)
            self.conn.runs[vals["run_id"]] = vals
            self.rowcount = 1
            return
        if s.startswith("UPDATE agentic_runtime.agent_runs SET"):
            keys = ("status", "retrieval_count", "model_calls", "tool_calls", "cost_usd", "checkpoint_seq",
                    "checkpoint", "updated_at", "completed_at", "cancellation_reason", "run_id")
            v = dict(zip(keys, params))
            row = self.conn.runs[v["run_id"]]
            for k in keys[:-1]:
                row[k] = _maybe_json(v[k])
            self.rowcount = 1
            return
        m = re.search(r"INSERT INTO agentic_runtime\.(\w+)", s)
        if m:
            table = m.group(1)
            cols = _APPEND_COLUMNS[table]
            row = {c: _maybe_json(v) for c, v in zip(cols, params)}
            store = self.conn.tables[table]
            if table == "agent_artifacts":
                if any(r["run_id"] == row["run_id"] and r["payload_hash"] == row["payload_hash"] for r in store.values()):
                    self.rowcount = 0
                    return
                store[row["artifact_id"]] = row
            elif table == "kb_lessons":
                key = (row["lesson_id"], row["lesson_version"])
                if key in store:
                    self.rowcount = 0
                    return
                store[key] = row
            else:
                pk = cols[0]
                if row[pk] in store:
                    self.rowcount = 0
                    return
                store[row[pk]] = row
            self.rowcount = 1
            return
        m = re.search(r"SELECT (.+?) FROM agentic_runtime\.(\w+) c JOIN", s)
        if m:  # reviews/scores rows_for_run via join to the artifact's run
            table = m.group(2)
            cols = _APPEND_COLUMNS[table]
            run_id = params[0]
            arts = {aid for aid, r in self.conn.tables["agent_artifacts"].items() if r.get("run_id") == run_id}
            rows = [r for r in self.conn.tables[table].values() if r.get("artifact_id") in arts]
            self._result = [tuple(r.get(c) for c in cols) for r in rows]
            return
        m = re.search(r"SELECT (.+?) FROM agentic_runtime\.(\w+) WHERE (.+)", s)
        if m:
            table = m.group(2)
            cols = _APPEND_COLUMNS[table]
            where = m.group(3)
            values = list(self.conn.tables[table].values())
            keys = re.findall(r"(\w+)=%s", where)  # match ALL key columns (run_id, or run_id+payload_hash, or pk)
            rows = [r for r in values if all(r.get(k) == p for k, p in zip(keys, params))]
            self._result = [tuple(r.get(c) for c in cols) for r in rows]
            return
        raise AssertionError(f"unhandled SQL: {s}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


class FakeConnection:
    """One transaction: snapshot on construct, apply on commit, discard on rollback."""

    def __init__(self, cluster):
        self.cluster = cluster
        self.runs = copy.deepcopy(cluster.runs)
        self.tables = copy.deepcopy(cluster.tables)
        self._explode = cluster.explode_on

    def cursor(self):
        conn = self

        class C(FakeCursor):
            def execute(self, sql, params=()):
                if conn._explode and conn._explode in " ".join(sql.split()):
                    raise RuntimeError("simulated driver failure")
                return super().execute(sql, params)
        return C(self)

    def commit(self):
        self.cluster.runs = self.runs
        self.cluster.tables = self.tables
        self.cluster.commits += 1

    def rollback(self):
        self.cluster.rollbacks += 1

    def close(self):
        pass


def pg_factory(cluster):
    return lambda: FakeConnection(cluster)


_counter = itertools.count()


def _clock():
    return f"2026-07-25T00:00:{next(_counter):02d}.000000+00:00"


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return InMemoryPersistence(clock=_clock)
    return PostgresPersistence(pg_factory(FakeCluster()), clock=_clock)


def envelope(run_id="run_a", agent_id="alpha_agent", **kw):
    base = dict(run_id=run_id, agent_id=agent_id, agent_version="1.0.0", job_type="research",
                environment=Environment.LAB, objective="assess", input_hash=H, validation_hash=H)
    base.update(kw)
    return RunEnvelope(**base)


def artifact(run_id="run_a", producer="alpha_agent", payload=None, artifact_id="art_1"):
    payload = {"finding": "x"} if payload is None else payload
    return Artifact(artifact_id=artifact_id, run_id=run_id, producer_agent_id=producer, artifact_type="analysis",
                    payload=payload, input_hash=H, validation_hash=H, retrieval_refs=("kb:1",),
                    prompt_version="p1", provider_family="local", model="m1")


def _review(store, artifact_id="art_1", reviewer="beta_agent", payload=None, rid="rev_1"):
    ph = canonical_hash({"finding": "x"} if payload is None else payload)
    return Review(review_id=derive_id(rid), artifact_id=artifact_id, producer_agent_id="ignored",
                  reviewer_agent_id=reviewer, verdict=ReviewVerdict.PASS, findings=(), artifact_hash=ph)


def seed_reviewed(store):
    store.create_run(envelope(), BudgetPolicy())
    store.record_artifact(artifact())
    store.record_review(_review(store))


# --------------------------- A: persisted-truth ---------------------------- #
def test_review_producer_taken_from_persisted_artifact_not_caller(store):
    store.create_run(envelope(), BudgetPolicy())
    store.record_artifact(artifact(producer="alpha_agent"))
    bad = Review(review_id=derive_id("r2"), artifact_id="art_1", producer_agent_id="beta_agent",
                 reviewer_agent_id="alpha_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash=canonical_hash({"finding": "x"}))
    with pytest.raises(PersistenceError):
        store.record_review(bad)


def test_missing_artifact_and_wrong_hash_rejected_both_backends(store):
    store.create_run(envelope(), BudgetPolicy())
    store.record_artifact(artifact())
    with pytest.raises(PersistenceError):
        store.record_review(Review(review_id=derive_id("rx"), artifact_id="nope", producer_agent_id="p",
                                   reviewer_agent_id="beta_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash=H))
    with pytest.raises(PersistenceError):
        store.record_review(Review(review_id=derive_id("rh"), artifact_id="art_1", producer_agent_id="p",
                                   reviewer_agent_id="beta_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash="b" * 64))


def test_artifact_must_match_persisted_run_hashes(store):
    store.create_run(envelope(), BudgetPolicy())
    bad = Artifact(artifact_id="art_bad", run_id="run_a", producer_agent_id="alpha_agent", artifact_type="analysis",
                   payload={"finding": "y"}, input_hash="b" * 64, validation_hash=H, retrieval_refs=("kb:1",),
                   prompt_version="p", provider_family="local", model="m")
    with pytest.raises(PersistenceError):
        store.record_artifact(bad)


# --------------------------- B: idempotency conflict ----------------------- #
def test_create_run_conflict_on_any_changed_immutable_field(store):
    store.create_run(envelope(), BudgetPolicy())
    store.create_run(envelope(), BudgetPolicy())
    for kw in ({"agent_version": "2.0.0"}, {"job_type": "audit"}, {"input_hash": "b" * 64}):
        with pytest.raises(IdempotencyConflictError):
            store.create_run(envelope(**kw), BudgetPolicy())
    with pytest.raises(IdempotencyConflictError):
        store.create_run(envelope(), BudgetPolicy(max_tool_calls=99))


def test_artifact_payload_conflict_returns_persisted_id(store):
    store.create_run(envelope(), BudgetPolicy())
    first = store.record_artifact(artifact(artifact_id="art_real"))
    again = store.record_artifact(artifact(artifact_id="art_other"))
    assert first == again == "art_real"
    assert store.reconstruct("run_a").artifacts == ("art_real",)


def test_review_conflict_on_changed_evidence(store):
    seed_reviewed(store)
    with pytest.raises(IdempotencyConflictError):
        store.record_review(Review(review_id=derive_id("rev_1"), artifact_id="art_1", producer_agent_id="p",
                                   reviewer_agent_id="beta_agent", verdict=ReviewVerdict.REJECT, findings=(),
                                   artifact_hash=canonical_hash({"finding": "x"})))


# --------------------------- C: append-only journal ------------------------ #
def test_journal_events_are_immutable_rows_with_valid_chain(store):
    seed_reviewed(store)
    events = store.journal("run_a")
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    prev = GENESIS_HASH
    for e in events:
        assert e.previous_hash == prev
        prev = e.event_hash


def test_durable_tool_lifecycle_events(store):
    store.create_run(envelope(), BudgetPolicy())
    args = canonical_hash({"q": 1})
    store.record_tool_lifecycle("run_a", agent_id="alpha_agent", tool_name="kb.search", decision="ALLOW",
                                decision_reason="ok", arguments_hash=args, result_hash=H,
                                started_at="2026-07-25T00:00:00+00:00", completed_at="2026-07-25T00:00:01+00:00",
                                terminal_state="completed")
    types = [e.event_type for e in store.journal("run_a")]
    for stage in ("TOOL_PROPOSED", "TOOL_DECISION", "TOOL_STARTED", "TOOL_COMPLETED"):
        assert stage in types
    assert store.reconstruct("run_a").tool_calls == 1


# --------------------------- D: state + completion ------------------------- #
def test_completion_requires_material_artifact_and_review(store):
    store.create_run(envelope(), BudgetPolicy())
    with pytest.raises(PersistenceError):
        store.complete_run("run_a")
    store.record_artifact(artifact())
    with pytest.raises(PersistenceError):
        store.complete_run("run_a")
    store.record_review(_review(store))
    assert store.complete_run("run_a").status == RunStatus.COMPLETED.value


def test_post_terminal_independent_score_allowed_but_no_exec_mutation(store):
    seed_reviewed(store)
    store.complete_run("run_a")
    store.record_score(Score(score_id=derive_id("s1"), artifact_id="art_1", producer_agent_id="x",
                             scorer_agent_id="gamma_agent", dimensions={"quality": 0.4}))
    assert len(store.reconstruct("run_a").scores) == 1
    with pytest.raises(TerminalRunError):
        store.record_artifact(artifact(artifact_id="art_late", payload={"finding": "late"}))


# --------------------------- E: rollback / fail-closed --------------------- #
def test_secret_material_never_persisted(store):
    store.create_run(envelope(), BudgetPolicy())
    with pytest.raises(PersistenceError):
        store.record_artifact(artifact(payload={"password": "hunter2"}, artifact_id="art_secret"))
    assert store.reconstruct("run_a").artifacts == ()


def test_inmemory_rollback_leaves_no_partial_state():
    store = InMemoryPersistence(clock=_clock)
    store.create_run(envelope(), BudgetPolicy())
    before = store.reconstruct("run_a")
    with pytest.raises(PersistenceError):
        store.record_artifact(artifact(payload={"token": "x"}, artifact_id="art_bad"))
    after = store.reconstruct("run_a")
    assert after.sequence == before.sequence and after.artifacts == ()


def test_postgres_driver_failure_rolls_back_and_raises():
    cluster = FakeCluster()
    cluster.explode_on = "INSERT INTO agentic_runtime.agent_runs"
    pg = PostgresPersistence(pg_factory(cluster), clock=_clock)
    with pytest.raises(PersistenceError):
        pg.create_run(envelope(), BudgetPolicy())
    assert cluster.rollbacks >= 1 and cluster.commits == 0
    assert cluster.runs == {}


def test_concurrent_appends_stay_monotonic_and_unforked():
    store = InMemoryPersistence(clock=_clock)
    store.create_run(envelope(), BudgetPolicy())
    errors = []

    def worker(i):
        try:
            store.record_artifact(artifact(payload={"finding": f"f{i}"}, artifact_id=f"art_{i}"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    seqs = [e.sequence for e in store.journal("run_a")]
    assert seqs == sorted(set(seqs)) == list(range(1, len(seqs) + 1))


# --------------------------- F: runtime identity --------------------------- #
def test_postgres_rejects_non_allowlisted_or_privileged_identity():
    with pytest.raises(RuntimeIdentityError):
        PostgresPersistence(pg_factory(FakeCluster(current_user="agentic_lab_migrator")), clock=_clock).create_run(envelope(), BudgetPolicy())
    with pytest.raises(RuntimeIdentityError):
        PostgresPersistence(pg_factory(FakeCluster(role_flags=(True, False, False, False, False))), clock=_clock).create_run(envelope(), BudgetPolicy())
    PostgresPersistence(pg_factory(FakeCluster()), clock=_clock).create_run(envelope(), BudgetPolicy())


def test_postgres_contract_parameterized_and_conflict_guarded():
    cluster = FakeCluster()
    pg = PostgresPersistence(pg_factory(cluster), clock=_clock)
    pg.create_run(envelope(), BudgetPolicy())
    pg.record_artifact(artifact())
    assert cluster.for_update >= 1
    inserts = [sql for sql, _ in cluster.sql_log if sql.startswith("INSERT")]
    assert inserts and all("ON CONFLICT" in sql for sql in inserts)
    assert cluster.commits >= 2 and cluster.rollbacks == 0


# --------------------------- G: knowledge base ----------------------------- #
def test_kb_lesson_case_chunk_persist_and_conflict(store):
    lid = store.record_lesson(lesson_id="L1", lesson_version=1, lifecycle="CANDIDATE", title="t",
                              statement="prefer confluence", provenance={"source": "run_a"}, created_by="alpha_agent")
    assert lid == "L1:1"
    store.record_lesson(lesson_id="L1", lesson_version=1, lifecycle="CANDIDATE", title="t",
                        statement="prefer confluence", provenance={"source": "run_a"}, created_by="alpha_agent")
    with pytest.raises(IdempotencyConflictError):
        store.record_lesson(lesson_id="L1", lesson_version=1, lifecycle="CANDIDATE", title="t",
                            statement="CHANGED", provenance={"source": "run_a"}, created_by="alpha_agent")
    with pytest.raises(PersistenceError):
        store.record_lesson(lesson_id="L2", lesson_version=1, lifecycle="RATIFIED", title="t", statement="s",
                            provenance={}, created_by="alpha_agent", reviewed_by="alpha_agent")
    assert store.record_case(case_id="C1", case_type="decision", source_refs=["run_a"], facts={"symbol": "V"}) == "C1"
    assert store.record_chunk(chunk_id="K1", source_type="doc", source_ref="d1", source_hash=H, content="text") == "K1"


def test_kb_rejects_secret_material(store):
    with pytest.raises(PersistenceError):
        store.record_case(case_id="C9", case_type="decision", source_refs=[], facts={"password": "x"})


# --------------------------- optional real LAB ----------------------------- #
def test_real_lab_postgres_roundtrip_if_available():
    psycopg2 = pytest.importorskip("psycopg2")
    import os
    if not os.path.exists("/home/johnclaw/tradeai-lab/sock"):
        pytest.skip("isolated LAB cluster not present")

    def factory():
        try:
            return psycopg2.connect(host="/home/johnclaw/tradeai-lab/sock", port=5433,
                                    dbname="trade_ai_agentic_lab", user="agentic_runtime_lab_rw",
                                    options="-c search_path=agentic_runtime")
        except Exception:
            pytest.skip("LAB runtime role/db not provisioned")

    pg = PostgresPersistence(factory, clock=_clock)
    env = envelope(run_id=f"run_it_{next(_counter)}")
    pg.create_run(env, BudgetPolicy())
    assert pg.reconstruct(env.run_id).status == RunStatus.CREATED.value
