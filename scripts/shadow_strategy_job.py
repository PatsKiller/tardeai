#!/usr/bin/env python3
"""shadow_strategy_job.py — on-demand "Build Full Strategy" runner (Stage C).

SHADOW ONLY. Produces a shadow decision packet on demand; touches no proposal,
order, approval, or execution path.

THE CONTRACT (spec §14)
-----------------------
An operator presses BUILD FULL STRATEGY. The HTTP request must return a run_id in
under ~2s and NEVER block on a model lane. The worker then moves the run through
QUEUED -> RUNNING -> per-stage -> COMPLETE/FAILED, and the UI polls status.

    enqueue(symbol)                     insert QUEUED run, spawn detached worker,
                                        return run_id immediately
    python shadow_strategy_job.py --run-id N --symbol X     the worker
    status(run_id)                      the poll payload

WHY THE HTTP PATH CANNOT WAIT
-----------------------------
The observed BETA run waited 600s on the local-model gate before falling back.
So: the enqueue only INSERTs and spawns — it never evaluates. The worker runs
detached (start_new_session) with its own SLA. And the blind pass defaults to the
two cloud lanes, not the local Ollama lock, so a stuck local model cannot wedge a
run regardless.

SLA AND FAILURE
---------------
Every threshold is env-configurable (no hardcoded SLA). The worker enforces an
overall deadline; a run that blows it is marked FAILED with the reason, not left
RUNNING forever. A watchdog (sweep_stale) fails runs whose worker died without
reaching a terminal state — a heartbeat older than the grace window.

PROVIDER HONESTY
----------------
provider_used records what actually answered. A fallback is never labelled as the
requested provider — the same rule the planner's gpt-4o-mini fallback violated by
printing "[local-llm] ... OK" for an OpenAI call.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PY = str(PROJECT_ROOT / ".venv" / "bin" / "python")

# Env-configurable SLA (no hardcoded thresholds).
SLA_SECONDS = int(os.getenv("SHADOW_JOB_SLA_SECONDS", "180"))
# A RUNNING run whose heartbeat is older than this with a dead worker is swept.
STALE_GRACE_SECONDS = int(os.getenv("SHADOW_JOB_STALE_GRACE_SECONDS", "300"))

STAGES = ("facts", "events", "blind_review", "long_term", "swing",
          "bearish", "options", "persistence")


def _now():
    return datetime.now(timezone.utc)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


# ── enqueue: fast, detached, returns a run_id ─────────────────────────────────

def enqueue(symbol: str, *, requested_by: str = "operator",
            sla_seconds: int = SLA_SECONDS, run_models: bool = True) -> dict:
    """INSERT a QUEUED run and spawn the detached worker. Returns immediately —
    no evaluation happens on this path, so it cannot block on a model lane.

    Idempotency: a QUEUED/RUNNING run for the same symbol is returned as-is
    rather than starting a duplicate, so a double-click does not spawn two
    workers.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol required"}

    conn = _conn()
    cur = conn.cursor()
    cur.execute("""SELECT run_id, state FROM decision_runs
                   WHERE upper(symbol)=%s AND state IN ('QUEUED','RUNNING')
                   ORDER BY requested_at DESC LIMIT 1""", (sym,))
    existing = cur.fetchone()
    if existing:
        return {"ok": True, "run_id": existing[0], "state": existing[1],
                "symbol": sym, "already_running": True}

    stages = [{"name": s, "state": "pending"} for s in STAGES]
    cur.execute("""INSERT INTO decision_runs
                     (origin, requested_by, symbol, state, symbols_requested,
                      stages, sla_seconds, sla_deadline)
                   VALUES ('on_demand', %s, %s, 'QUEUED', 1, %s::jsonb, %s,
                           now() + (%s || ' seconds')::interval)
                   RETURNING run_id""",
                (requested_by, sym, json.dumps(stages), sla_seconds, sla_seconds))
    run_id = cur.fetchone()[0]
    conn.commit()

    # Detached: start_new_session so it survives the request, DEVNULL so it never
    # blocks on a pipe. The worker owns all further state transitions.
    cmd = [PY, str(PROJECT_ROOT / "scripts" / "shadow_strategy_job.py"),
           "--run-id", str(run_id), "--symbol", sym]
    if not run_models:
        cmd.append("--no-models")
    subprocess.Popen(cmd, cwd=PROJECT_ROOT, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "run_id": run_id, "state": "QUEUED", "symbol": sym,
            "sla_seconds": sla_seconds}


# ── worker: transitions the run and produces the packet ───────────────────────

def _set_stage(conn, run_id: int, name: str, state: str, detail: str = ""):
    cur = conn.cursor()
    cur.execute("""UPDATE decision_runs
                   SET current_stage=%s, heartbeat_at=now(),
                       stages = (
                         SELECT jsonb_agg(
                           CASE WHEN s->>'name' = %s
                                THEN s || jsonb_build_object('state', %s::text,
                                       'detail', %s::text, 'at', now()::text)
                                ELSE s END)
                         FROM jsonb_array_elements(stages) s)
                   WHERE run_id=%s""",
                (name, name, state, detail, run_id))
    conn.commit()


def run_worker(run_id: int, symbol: str, *, run_models: bool = True) -> int:
    """Execute one queued run. Returns process exit code."""
    import shadow_decision_service as svc
    sym = str(symbol).upper()
    conn = _conn()
    cur = conn.cursor()

    # Claim the run. RUNNING with our pid and a fresh heartbeat.
    cur.execute("""UPDATE decision_runs
                   SET state='RUNNING', started_at=now(), worker_pid=%s, heartbeat_at=now(),
                       provider_requested=%s
                   WHERE run_id=%s AND state='QUEUED'""",
                (os.getpid(), ",".join(_requested_lanes()), run_id))
    conn.commit()
    if cur.rowcount == 0:
        # Someone else claimed it, or it was cancelled. Do nothing.
        return 0

    deadline = _now().timestamp() + _sla_for(conn, run_id)

    def on_stage(name):
        # Deadline check FIRST and it propagates — the service's _stage wrapper
        # re-raises TimeoutError so the run fails explicitly at this boundary
        # rather than running past its SLA. The progress write is best-effort.
        if _now().timestamp() > deadline:
            over = int(_now().timestamp() - deadline)
            raise TimeoutError(f"SLA exceeded at stage {name} ({over}s past deadline)")
        try:
            _set_stage(conn, run_id, name, "running")
        except Exception:
            pass

    try:
        packet = svc.evaluate(sym, conn, origin="on_demand", run_models=run_models,
                              on_stage=on_stage)
        _set_stage(conn, run_id, "persistence", "running")
        # Pass our run_id so the packet links to THIS run rather than persist()
        # minting a stageless orphan run the packet then points at.
        packet_id = svc.persist(packet, origin="on_demand", run_id=run_id)

        # Mark every reached stage complete and record the honest provider.
        mr = packet.get("model_review") or {}
        provider_used = ",".join(mr.get("lanes_completed") or []) or "none"
        fallback = None
        if mr.get("mode") in ("SINGLE_LANE", "BLIND_PARTIAL", "UNAVAILABLE"):
            fallback = (f"requested {mr.get('lanes_requested')}, "
                        f"completed {mr.get('lanes_completed')}")
        cur.execute("""UPDATE decision_runs
                       SET state='COMPLETE', completed_at=now(), symbols_completed=1,
                           packet_id=%s, provider_used=%s, fallback_reason=%s,
                           current_stage='done', heartbeat_at=now(),
                           stages = (SELECT jsonb_agg(
                                       CASE WHEN (s->>'state') IN ('running','pending')
                                            THEN s || '{"state":"complete"}'::jsonb
                                            ELSE s END)
                                     FROM jsonb_array_elements(stages) s)
                       WHERE run_id=%s""",
                    (packet_id, provider_used, fallback, run_id))
        conn.commit()
        return 0
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:240]}"
        try:
            cur.execute("""UPDATE decision_runs
                           SET state='FAILED', completed_at=now(), failure_reason=%s,
                               heartbeat_at=now(),
                               stages = (SELECT jsonb_agg(
                                           CASE WHEN s->>'state'='running'
                                                THEN s || jsonb_build_object('state','failed')
                                                ELSE s END)
                                         FROM jsonb_array_elements(stages) s)
                           WHERE run_id=%s""", (reason, run_id))
            conn.commit()
        except Exception:
            pass
        return 1


def _requested_lanes():
    try:
        import blind_review_runner as brr
        return list(brr._default_lanes())
    except Exception:
        return []


def _sla_for(conn, run_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT sla_seconds FROM decision_runs WHERE run_id=%s", (run_id,))
    r = cur.fetchone()
    return int(r[0]) if r and r[0] else SLA_SECONDS


# ── status: the poll payload ──────────────────────────────────────────────────

def status(run_id: int) -> dict:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""SELECT run_id, symbol, state, current_stage, stages, packet_id,
                          provider_requested, provider_used, fallback_reason,
                          failure_reason, requested_at, started_at, completed_at,
                          sla_seconds, sla_deadline
                   FROM decision_runs WHERE run_id=%s""", (run_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": f"no run {run_id}"}
    stages = r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]")
    out = {"ok": True, "run_id": r[0], "symbol": r[1], "state": r[2],
           "current_stage": r[3], "stages": stages, "packet_id": r[5],
           "provider_requested": r[6], "provider_used": r[7],
           "fallback_reason": r[8], "failure_reason": r[9],
           "requested_at": str(r[10]), "started_at": str(r[11]),
           "completed_at": str(r[12]), "sla_seconds": r[13],
           "sla_deadline": str(r[14])}
    # Past the deadline while still non-terminal is a signal for the watchdog.
    if r[2] in ("QUEUED", "RUNNING") and r[14] and _now() > r[14]:
        out["sla_breached"] = True
    return out


def latest_for(symbol: str) -> dict:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""SELECT run_id FROM decision_runs WHERE upper(symbol)=%s
                   ORDER BY requested_at DESC LIMIT 1""", (str(symbol).upper(),))
    r = cur.fetchone()
    return status(r[0]) if r else {"ok": False, "error": f"no runs for {symbol}"}


# ── watchdog: fail runs whose worker died ─────────────────────────────────────

def sweep_stale() -> dict:
    """Mark as FAILED any QUEUED/RUNNING run whose heartbeat is older than the
    grace window — the worker died without reaching a terminal state. Without
    this a crashed worker leaves a run RUNNING forever and the card spins."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""UPDATE decision_runs
                   SET state='FAILED', completed_at=now(),
                       failure_reason='worker heartbeat stale — presumed dead'
                   WHERE state IN ('QUEUED','RUNNING')
                     AND COALESCE(heartbeat_at, requested_at) < now() - (%s || ' seconds')::interval
                   RETURNING run_id""", (STALE_GRACE_SECONDS,))
    swept = [r[0] for r in cur.fetchall()]
    conn.commit()
    return {"ok": True, "swept": swept, "n": len(swept)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Shadow on-demand strategy job runner")
    ap.add_argument("--run-id", type=int, help="worker mode: execute this run")
    ap.add_argument("--symbol")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--enqueue", action="store_true", help="enqueue and return run_id")
    ap.add_argument("--status", type=int, help="print status for a run_id")
    ap.add_argument("--sweep", action="store_true", help="run the stale-worker watchdog")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.sweep:
        out = sweep_stale()
    elif args.status is not None:
        out = status(args.status)
    elif args.enqueue:
        if not args.symbol:
            out = {"ok": False, "error": "--symbol required with --enqueue"}
        else:
            out = enqueue(args.symbol, run_models=not args.no_models)
    elif args.run_id is not None and args.symbol:
        return run_worker(args.run_id, args.symbol, run_models=not args.no_models)
    else:
        out = {"ok": False, "error": "specify --enqueue --symbol X, --status N, "
                                     "--sweep, or (worker) --run-id N --symbol X"}

    print(json.dumps(out, indent=2, default=str) if args.json else out)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
