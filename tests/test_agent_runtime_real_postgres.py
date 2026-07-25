"""Real isolated-LAB PostgreSQL adapter proof (port 5433 only).

Skipped everywhere except the exact-ref host-proof wrapper, which sets
``AGENTIC_REAL_LAB=1`` after evolving a fresh disposable LAB and provisioning the
runtime writer role. Never contacts production port 5432.
"""

from __future__ import annotations

import itertools
import os
import threading

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(os.getenv("AGENTIC_REAL_LAB") != "1", reason="real LAB proof runs only under the host-proof wrapper")

from scripts.agent_runtime.contracts import (  # noqa: E402
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
from scripts.agent_runtime.export_replay import export_manifest, export_run_jsonl, replay_jsonl, verify_jsonl  # noqa: E402
from scripts.agent_runtime.persistence import (  # noqa: E402
    IdempotencyConflictError,
    PersistenceError,
    PostgresPersistence,
    derive_id,
)

H = "a" * 64
_LAB_SOCK = os.getenv("AGENTIC_LAB_SOCK", "/home/johnclaw/tradeai-lab/sock")
_LAB_DB = os.getenv("AGENTIC_LAB_DB", "trade_ai_agentic_lab")
_LAB_ROLE = os.getenv("AGENTIC_LAB_ROLE", "agentic_runtime_lab_rw")
_counter = itertools.count()


def _clock():
    return f"2026-07-25T01:00:{next(_counter):02d}.000000+00:00"


def _factory():
    conn = psycopg2.connect(host=_LAB_SOCK, port=5433, dbname=_LAB_DB, user=_LAB_ROLE, options="-c search_path=agentic_runtime")
    conn.autocommit = False
    return conn


def _store():
    return PostgresPersistence(_factory, clock=_clock)


def _rid(tag):
    return f"real_{tag}_{next(_counter)}"


def _env(run_id):
    return RunEnvelope(run_id=run_id, agent_id="alpha_agent", agent_version="1.0.0", job_type="research",
                       environment=Environment.LAB, objective="assess", input_hash=H, validation_hash=H)


def _art(run_id, payload=None, aid="art_1"):
    return Artifact(artifact_id=aid, run_id=run_id, producer_agent_id="alpha_agent", artifact_type="analysis",
                    payload=payload or {"finding": "x"}, input_hash=H, validation_hash=H, retrieval_refs=("kb:1",),
                    prompt_version="p1", provider_family="local", model="m1")


def test_real_roundtrip_review_score_and_completion():
    s = _store()
    rid = _rid("rt")
    s.create_run(_env(rid), BudgetPolicy())
    s.record_artifact(_art(rid, aid=f"{rid}_a"))
    s.record_review(Review(review_id=derive_id(rid, "rev"), artifact_id=f"{rid}_a", producer_agent_id="ignored",
                           reviewer_agent_id="beta_agent", verdict=ReviewVerdict.PASS, findings=(), artifact_hash=canonical_hash({"finding": "x"})))
    assert s.complete_run(rid).status == RunStatus.COMPLETED.value
    s.record_score(Score(score_id=derive_id(rid, "sc"), artifact_id=f"{rid}_a", producer_agent_id="x",
                         scorer_agent_id="gamma_agent", dimensions={"quality": 0.5}))
    assert len(s.reconstruct(rid).scores) == 1


def test_real_append_only_trigger_blocks_update():
    s = _store()
    rid = _rid("ap")
    s.create_run(_env(rid), BudgetPolicy())
    s.record_artifact(_art(rid, aid=f"{rid}_a"))
    conn = _factory()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception):  # append-only trigger rejects UPDATE
            cur.execute("UPDATE agentic_runtime.agent_artifacts SET model='tampered' WHERE run_id=%s", (rid,))
            conn.commit()
        conn.rollback()
    finally:
        conn.close()


def test_real_idempotency_conflict_and_rollback():
    s = _store()
    rid = _rid("id")
    s.create_run(_env(rid), BudgetPolicy())
    with pytest.raises(IdempotencyConflictError):
        conflicting = RunEnvelope(run_id=rid, agent_id="alpha_agent", agent_version="9.9.9", job_type="research",
                                  environment=Environment.LAB, objective="assess", input_hash=H, validation_hash=H)
        s.create_run(conflicting, BudgetPolicy())
    with pytest.raises(PersistenceError):
        s.record_artifact(_art(rid, payload={"password": "x"}, aid=f"{rid}_secret"))
    assert s.reconstruct(rid).artifacts == ()  # rollback left nothing


def test_real_export_replay_and_tamper():
    s = _store()
    rid = _rid("ex")
    s.create_run(_env(rid), BudgetPolicy())
    s.record_artifact(_art(rid, aid=f"{rid}_a"))
    lines = export_run_jsonl(s, rid)
    manifest = export_manifest(s, rid)
    assert replay_jsonl(lines, manifest=manifest)["run_id"] == rid
    assert not verify_jsonl(lines[:-1], manifest=manifest).ok  # truncated tail


def test_real_two_connection_concurrency_no_fork():
    """Two independent connections append to the same run; FOR UPDATE serializes them."""
    s = _store()
    rid = _rid("cc")
    s.create_run(_env(rid), BudgetPolicy())
    errors: list[Exception] = []

    def worker(i):
        try:
            PostgresPersistence(_factory, clock=_clock).record_artifact(_art(rid, payload={"finding": f"f{i}"}, aid=f"{rid}_{i}"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    seqs = [e.sequence for e in s.journal(rid)]  # journal() validates the chain; monotonic + unforked
    assert seqs == sorted(set(seqs)) == list(range(1, len(seqs) + 1))


def test_real_kb_persistence():
    s = _store()
    tag = next(_counter)
    assert s.record_lesson(lesson_id=f"L{tag}", lesson_version=1, lifecycle="CANDIDATE", title="t",
                           statement="prefer confluence", provenance={"source": "lab"}, created_by="alpha_agent") == f"L{tag}:1"
    assert s.record_case(case_id=f"C{tag}", case_type="decision", source_refs=["lab"], facts={"symbol": "V"}) == f"C{tag}"
    assert s.record_chunk(chunk_id=f"K{tag}", source_type="doc", source_ref="d1", source_hash=H, content="text") == f"K{tag}"
