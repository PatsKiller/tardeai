#!/usr/bin/env python3
"""Stage C — the on-demand 'Build Full Strategy' job runner.

The contract (spec §14): the HTTP path returns a run_id fast and NEVER blocks on
a model lane; the worker moves the run QUEUED -> RUNNING -> per-stage ->
COMPLETE/FAILED; an SLA breach fails EXPLICITLY rather than hanging; a dead
worker is swept; the provider actually used is recorded, never a fallback
mislabelled as the request.

The DB-backed tests plant and delete their own rows under a ZZ* symbol and mock
subprocess.Popen so no real worker spawns. The SLA-propagation test is pure.

No order queued, submitted, or 2FA requested anywhere in this module.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ── the SLA bug, pinned: TimeoutError must abort; other errors must not ────────

class _DummyConn:
    def cursor(self):
        raise AssertionError("evaluate must abort before touching the DB")


def test_sla_timeout_aborts_evaluation_at_first_stage():
    """A first version swallowed EVERY exception in _stage 'so progress reporting
    never fails the eval' — which also swallowed the SLA TimeoutError, so a run
    with a 1s SLA ran to COMPLETE. The timeout must propagate."""
    import shadow_decision_service as svc
    seen = []

    def on_stage(name):
        seen.append(name)
        raise TimeoutError("SLA exceeded")

    with pytest.raises(TimeoutError):
        svc.evaluate("BETA", conn=_DummyConn(), run_models=False, on_stage=on_stage)
    assert seen == ["facts"], "must abort at the first stage boundary"


def test_progress_report_failure_does_not_abort_evaluation(monkeypatch):
    """The other half of the same contract: a failed progress WRITE (not a
    timeout) must be swallowed so a reporting hiccup cannot fail a good run."""
    import shadow_decision_service as svc
    # a non-timeout error from on_stage is swallowed; evaluate proceeds to the DB
    # (which our dummy conn refuses) — so we assert it gets PAST the first stage
    # by observing the DB access attempt rather than a propagated ValueError.
    calls = {"n": 0}

    def on_stage(name):
        calls["n"] += 1
        raise ValueError("simulated progress-write failure")

    with pytest.raises(AssertionError):   # _DummyConn.cursor() fires, not ValueError
        svc.evaluate("BETA", conn=_DummyConn(), run_models=False, on_stage=on_stage)
    assert calls["n"] >= 1


def test_service_stage_wrapper_reraises_only_timeout():
    import shadow_decision_service as svc
    src = Path(svc.__file__).read_text()
    blk = src[src.index("def _stage(name):"):src.index("def _stage(name):") + 700]
    assert "except TimeoutError:" in blk and "raise" in blk
    assert "except Exception:" in blk and "pass" in blk


# ── stages and SLA are configuration, not literals ────────────────────────────

def test_all_eight_stages_declared():
    import shadow_strategy_job as job
    assert job.STAGES == ("facts", "events", "blind_review", "long_term",
                          "swing", "bearish", "options", "persistence")


def test_sla_thresholds_are_env_configurable():
    import shadow_strategy_job as job
    src = Path(job.__file__).read_text()
    assert 'os.getenv("SHADOW_JOB_SLA_SECONDS"' in src
    assert 'os.getenv("SHADOW_JOB_STALE_GRACE_SECONDS"' in src


def test_enqueue_never_evaluates_inline():
    """The HTTP path must not call evaluate — that is what would block on a lane.
    enqueue only INSERTs and Popens."""
    import shadow_strategy_job as job
    src = Path(job.__file__).read_text()
    enq = src[src.index("def enqueue("):src.index("def run_worker(")]
    assert "evaluate(" not in enq, "enqueue must not evaluate inline — it would block"
    assert "subprocess.Popen" in enq and "start_new_session=True" in enq


def test_worker_is_spawned_detached_with_devnull():
    import shadow_strategy_job as job
    src = Path(job.__file__).read_text()
    enq = src[src.index("def enqueue("):src.index("def run_worker(")]
    assert "stdout=subprocess.DEVNULL" in enq and "stderr=subprocess.DEVNULL" in enq


# ── DB-backed: enqueue, idempotency, status, sweep (mocked Popen) ─────────────

@pytest.fixture
def no_spawn(monkeypatch):
    """Stop enqueue from launching a real worker."""
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)


@pytest.fixture
def clean_zz():
    yield
    try:
        from db_adapter import _get_conn
        c = _get_conn(); cur = c.cursor()
        cur.execute("DELETE FROM decision_runs WHERE symbol LIKE 'ZZ%'")
        c.commit()
    except Exception:
        pass


def test_enqueue_returns_run_id_immediately(no_spawn, clean_zz):
    import shadow_strategy_job as job
    out = job.enqueue("ZZJOBA")
    assert out["ok"] and out["state"] == "QUEUED" and isinstance(out["run_id"], int)
    assert out["symbol"] == "ZZJOBA"


def test_enqueue_is_idempotent_while_running(no_spawn, clean_zz):
    """A double-click must not spawn two workers."""
    import shadow_strategy_job as job
    a = job.enqueue("ZZJOBB")
    b = job.enqueue("ZZJOBB")
    assert b["run_id"] == a["run_id"]
    assert b.get("already_running") is True


def test_enqueue_requires_a_symbol(no_spawn):
    import shadow_strategy_job as job
    assert job.enqueue("")["ok"] is False


def test_status_payload_shape(no_spawn, clean_zz):
    import shadow_strategy_job as job
    rid = job.enqueue("ZZJOBC")["run_id"]
    st = job.status(rid)
    for k in ("run_id", "symbol", "state", "stages", "provider_requested",
              "provider_used", "fallback_reason", "failure_reason", "sla_seconds"):
        assert k in st, f"status missing {k}"
    assert len(st["stages"]) == 8
    assert all(s["state"] == "pending" for s in st["stages"])


def test_status_of_unknown_run_is_an_error():
    import shadow_strategy_job as job
    assert job.status(999999999)["ok"] is False


def test_sweep_fails_a_dead_running_worker(clean_zz):
    """A worker that dies without a terminal state leaves a run RUNNING forever;
    the watchdog must fail it so the card stops spinning."""
    import shadow_strategy_job as job
    from db_adapter import _get_conn
    c = _get_conn(); cur = c.cursor()
    cur.execute("""INSERT INTO decision_runs (origin, symbol, state, heartbeat_at,
                     requested_at, stages)
                   VALUES ('on_demand','ZZDEAD','RUNNING', now()-interval '30 minutes',
                           now()-interval '30 minutes','[]'::jsonb) RETURNING run_id""")
    dead = cur.fetchone()[0]; c.commit()
    swept = job.sweep_stale()
    assert dead in swept["swept"]
    assert job.status(dead)["state"] == "FAILED"


def test_a_fresh_running_worker_is_not_swept(clean_zz):
    """The watchdog must not kill a run whose worker is alive and heartbeating."""
    import shadow_strategy_job as job
    from db_adapter import _get_conn
    c = _get_conn(); cur = c.cursor()
    cur.execute("""INSERT INTO decision_runs (origin, symbol, state, heartbeat_at,
                     requested_at, stages)
                   VALUES ('on_demand','ZZALIVE','RUNNING', now(), now(),'[]'::jsonb)
                   RETURNING run_id""")
    alive = cur.fetchone()[0]; c.commit()
    job.sweep_stale()
    assert job.status(alive)["state"] == "RUNNING"


# ── provider honesty ──────────────────────────────────────────────────────────

def test_provider_used_reflects_completed_lanes_not_requested():
    """provider_used must be what actually answered. The worker derives it from
    lanes_completed, so a fallback (fewer lanes) is never dressed up as the
    request."""
    import shadow_strategy_job as job
    src = Path(job.__file__).read_text()
    wk = src[src.index("def run_worker("):]
    assert 'mr.get("lanes_completed")' in wk
    assert "provider_used=%s" in wk


# ── the API handlers ──────────────────────────────────────────────────────────

def test_api_status_handler_accepts_run_id_and_symbol(no_spawn, clean_zz):
    import importlib
    import api_v2
    importlib.reload(api_v2)
    import shadow_strategy_job as job
    rid = job.enqueue("ZZAPI")["run_id"]
    assert api_v2._shadow_strategy_status({"run_id": rid})["run_id"] == rid
    assert api_v2._shadow_strategy_status({"symbol": "ZZAPI"})["run_id"] == rid
    assert api_v2._shadow_strategy_status({})["ok"] is False


def test_api_build_requires_symbol():
    import importlib
    import api_v2
    importlib.reload(api_v2)
    assert api_v2._shadow_strategy_build({})["ok"] is False


def test_shadow_routes_are_registered():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    assert '"/api/v2/shadow/strategy/status": _shadow_strategy_status' in src
    assert '"/api/v2/shadow/strategy/build"' in src
