#!/usr/bin/env python3
"""watch_decision_refresh.py — V5 canonical Watch decision refresh orchestrator.

ONE path for every strategy refresh (operator button, bulk action, scheduler).
Fixes the V4 defect where the card's "Refresh Strategy" CTA hit the generic
enrichment endpoint and never rebuilt the decision packet (baseline audit
docs/audits/WATCH_DECISION_DESK_V5_BASELINE_2026-07-22.md).

    Refresh inputs updates evidence. Rebuild strategy updates the decision.
    The operator must always know which one happened, and when.

Scopes:
    INPUTS_ONLY          refresh evidence only — packet untouched (honest label)
    AFFECTED_DIMENSIONS  refresh only the input groups the invalidation reasons
                         implicate, then rebuild the packet deterministically
    FULL_STRATEGY        refresh all input groups, then rebuild the packet

Analysis tiers:
    LOCAL_QUANT      deterministic — shadow_decision_service run_models=False;
                     ZERO model-lane calls
    STANDARD_BLIND   existing free-OAuth blind lanes (grok + chatgpt)
    PREMIUM_REVIEW   governed paid tier — refuses to run unless a registry
                     provider is enabled AND the run carries explicit operator
                     confirmation; never scheduled automatically

Server-owned: runs/jobs persist in watch_decision_refresh_runs/_jobs; the HTTP
enqueue returns in <250ms and spawns detached workers (shadow_strategy_job
pattern). Per-symbol serialization via pg advisory locks; duplicate live jobs
for the same (symbol, scope, tier, input-hash) are refused by a partial unique
index and surfaced as SKIPPED_CURRENT/SKIPPED_LOCKED, never as silent drops.

SHADOW/ADVISORY ONLY — no proposal, approval, order, or 2FA surface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))  # env_bootstrap

_VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable  # worktrees share the main venv

SCOPES = ("INPUTS_ONLY", "AFFECTED_DIMENSIONS", "FULL_STRATEGY")
TIERS = ("LOCAL_QUANT", "STANDARD_BLIND", "PREMIUM_REVIEW")
JOB_STAGES = ("lock", "assess", "inputs", "rebuild", "policy", "readback")
MAX_SYMBOLS_PER_RUN = int(os.getenv("WDR_MAX_SYMBOLS_PER_RUN", "200"))
WORKERS_PER_RUN = int(os.getenv("WDR_WORKERS", "2"))
JOB_SLA_SECONDS = int(os.getenv("WDR_JOB_SLA_SECONDS", "240"))
ADVISORY_LOCK_NS = 774401  # namespace for per-symbol advisory locks

_POLICY_PATH = PROJECT_ROOT / "config" / "watch_decision_refresh_policy.yaml"
_POLICY_CACHE = {"mtime": None, "policy": None}


def _now():
    return datetime.now(timezone.utc)


def _conn():
    """PRIVATE connection — NOT db_adapter's thread-local shared one. The inputs
    stage runs foreign enrichment modules in-process, and at least one of them
    closes the shared connection when it finishes (proven: 'connection already
    closed' at the rebuild stage). Job bookkeeping must survive that."""
    import psycopg2
    try:  # ensure DB_* env is loaded the same way db_adapter does
        from env_bootstrap import load_env
        load_env()
    except Exception:
        pass
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=10,
        application_name="watch_decision_refresh")


def _fresh_conn(conn):
    """Return conn if alive, else a new private connection (foreign modules can
    kill sockets server-side too)."""
    try:
        if conn is not None and not conn.closed:
            conn.cursor().execute("SELECT 1")
            return conn
    except Exception:
        pass
    return _conn()


def _commit_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "unknown"


# ── policy (mtime hot-reload, stop_policy.yaml pattern) ──────────────────────
def load_policy() -> dict:
    try:
        mtime = _POLICY_PATH.stat().st_mtime
        if _POLICY_CACHE["mtime"] != mtime:
            import yaml
            _POLICY_CACHE["policy"] = yaml.safe_load(_POLICY_PATH.read_text()) or {}
            _POLICY_CACHE["mtime"] = mtime
    except Exception:
        _POLICY_CACHE.setdefault("policy", {})
    return _POLICY_CACHE["policy"] or {}


def policy_version() -> str:
    return str(load_policy().get("version") or "unversioned")


# ── dimension mapping: invalidation reason → input group to refresh ──────────
REASON_TO_DIMENSION = {
    "TECHNICALS_CHANGED": "technicals", "TECHNICALS_STALE": "technicals",
    "PRICE_DRIFT": "price",
    "FUNDAMENTALS_CHANGED": "fundamentals", "FUNDAMENTALS_STALE": "fundamentals",
    "NEW_CATALYST": "events", "EARNINGS_CHANGED": "events",
    "OWNERSHIP_CHANGED": "ownership",
    "OPTIONS_CHAIN_STALE": "options",
    "PROPOSAL_STATE_CHANGED": "ownership",
}
ALL_DIMENSIONS = ("price", "technicals", "fundamentals", "events", "ownership", "options")


def _refresh_dimension(symbol: str, dim: str, source_calls: dict) -> None:
    """Refresh ONE input group. Deterministic, bounded; failures recorded not fatal
    (the rebuild stage re-reads whatever truth exists)."""
    t0 = time.time()
    ok, note = True, ""
    try:
        if dim == "price":
            import price_db_sync
            price_db_sync.sync_watchlist_prices(symbols=[symbol])
        elif dim == "technicals":
            import watchlist_enrichment_sweep as swp
            swp.enrich_symbols([symbol])
            try:
                import watchlist_volatility
                watchlist_volatility.refresh_atr20_symbol(symbol)
            except Exception:
                note = "atr20 skipped"
        elif dim == "fundamentals":
            subprocess.run([PY, str(PROJECT_ROOT / "scripts" / "hermes_analyst_coverage.py"),
                            "--symbol", symbol], capture_output=True, timeout=90)
        elif dim == "events":
            subprocess.run([PY, str(PROJECT_ROOT / "scripts" / "news_ingestion.py"),
                            "--symbol", symbol], capture_output=True, timeout=120)
            subprocess.run([PY, str(PROJECT_ROOT / "scripts" / "news_to_catalyst.py"),
                            "--symbol", symbol], capture_output=True, timeout=90)
        elif dim == "ownership":
            pass  # ownership truth is read live from holdings.json by the snapshot builder
        elif dim == "options":
            pass  # chain is fetched inside build_options during the rebuild (governed single attempt)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        # BaseException on purpose: legacy enrichers call sys.exit() on their own
        # error paths (SystemExit is NOT an Exception) — that must fail THIS
        # dimension, never kill the worker mid-job (job 5 died exactly this way).
        ok, note = False, f"{type(e).__name__}: {str(e)[:110]}"
    source_calls[dim] = {"ok": ok, "seconds": round(time.time() - t0, 1),
                         **({"note": note} if note else {})}


# ── enqueue ──────────────────────────────────────────────────────────────────
def enqueue_run(symbols: list[str], *, scope: str = "FULL_STRATEGY",
                analysis_tier: str = "LOCAL_QUANT", include_options: bool = False,
                force: bool = False, requested_by: str = "operator",
                reason: str = "", priority: int = 100,
                spawn_workers: bool = True) -> dict:
    """INSERT run + per-symbol jobs, spawn detached workers, return immediately."""
    syms = sorted({str(s or "").upper().strip() for s in symbols if str(s or "").strip()})
    if not syms:
        return {"ok": False, "error": "symbols required"}
    if len(syms) > MAX_SYMBOLS_PER_RUN:
        return {"ok": False, "error": f"max {MAX_SYMBOLS_PER_RUN} symbols per run (got {len(syms)})"}
    if scope not in SCOPES:
        return {"ok": False, "error": f"scope must be one of {SCOPES}"}
    if analysis_tier not in TIERS:
        return {"ok": False, "error": f"analysis_tier must be one of {TIERS}"}
    if analysis_tier == "PREMIUM_REVIEW":
        gate = premium_gate(len(syms), confirmed=False)
        if not gate["allowed"]:
            return {"ok": False, "error": gate["reason"], "premium_estimate": gate}

    est_lanes = 2 * len(syms) if analysis_tier == "STANDARD_BLIND" else 0
    conn = _conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO watch_decision_refresh_runs
                     (requested_by, reason, scope, analysis_tier, include_options, force,
                      symbols_requested, policy_version, source_commit_sha, estimated_lane_calls)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING run_id""",
                (requested_by, reason[:400], scope, analysis_tier, include_options, force,
                 len(syms), policy_version(), _commit_sha(), est_lanes))
    run_id = cur.fetchone()[0]
    queued = skipped = 0
    for sym in syms:
        idem = _idempotency_key(sym, scope, analysis_tier, conn)
        try:
            cur.execute("SAVEPOINT job_ins")
            cur.execute("""INSERT INTO watch_decision_refresh_jobs
                             (run_id, symbol, scope, analysis_tier, priority, idempotency_key)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (run_id, sym, scope, analysis_tier, priority, idem))
            queued += 1
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT job_ins")  # live duplicate (unique idx) → record skip
            cur.execute("""INSERT INTO watch_decision_refresh_jobs
                             (run_id, symbol, scope, analysis_tier, priority, idempotency_key,
                              state, error, completed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,'SKIPPED_LOCKED',
                                   'identical live job already queued/running', now())""",
                        (run_id, sym, scope, analysis_tier, priority, f"{idem}:skip:{run_id}"))
            skipped += 1
    conn.commit()
    if spawn_workers and queued:
        for _ in range(min(WORKERS_PER_RUN, queued)):
            subprocess.Popen([PY, str(PROJECT_ROOT / "scripts" / "watch_decision_refresh.py"),
                              "--worker"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, cwd=PROJECT_ROOT)
    return {"ok": True, "run_id": run_id, "symbols": syms, "estimated_symbols": len(syms),
            "queued": queued, "skipped_locked": skipped,
            "estimated_lane_calls": est_lanes, "estimated_paid_cost_usd": 0,
            "state": "QUEUED"}


def _idempotency_key(sym: str, scope: str, tier: str, conn) -> str:
    """symbol+scope+tier+current-input-hash: identical refresh requests against
    unchanged inputs collapse into one live job."""
    try:
        import packet_invalidation as pi
        snap = pi.build_current_input_snapshot(sym, conn)
        ih = pi.compute_input_hash(snap)[:16]
    except Exception:
        ih = "nohash"
    return hashlib.sha256(f"{sym}|{scope}|{tier}|{ih}".encode()).hexdigest()[:32]


# ── premium gate (Section 5C: registry-driven, never auto) ───────────────────
def premium_gate(n_symbols: int, *, confirmed: bool) -> dict:
    reg = (load_policy().get("premium_providers") or [])
    enabled = [p for p in reg if p.get("enabled")]
    if not enabled:
        return {"allowed": False, "reason": "PREMIUM_NOT_CONFIGURED — no enabled provider in "
                "watch_decision_refresh_policy.yaml premium_providers", "providers": []}
    p = enabled[0]
    est = round(n_symbols * float(p.get("est_cost_per_symbol_usd", 0)), 4)
    if not confirmed:
        return {"allowed": False, "reason": "PREMIUM_CONFIRMATION_REQUIRED",
                "provider": p.get("provider"), "model": p.get("model"),
                "estimated_calls": n_symbols, "estimated_cost_usd": est,
                "daily_budget_usd": p.get("daily_budget_usd"),
                "confirm_with": {"confirmed": True}}
    return {"allowed": True, "provider": p, "estimated_cost_usd": est}


# ── worker ───────────────────────────────────────────────────────────────────
def _claim_job(cur):
    cur.execute("""UPDATE watch_decision_refresh_jobs
                   SET state='RUNNING', started_at=now(), heartbeat_at=now()
                   WHERE job_id = (SELECT job_id FROM watch_decision_refresh_jobs
                                   WHERE state='QUEUED'
                                   ORDER BY priority, created_at LIMIT 1
                                   FOR UPDATE SKIP LOCKED)
                   RETURNING job_id, run_id, symbol, scope, analysis_tier""")
    return cur.fetchone()


def _stage(conn, job_id: int, name: str, extra: dict | None = None):
    conn.cursor().execute(
        """UPDATE watch_decision_refresh_jobs
           SET stage=%s, heartbeat_at=now(),
               stages = stages || %s::jsonb
           WHERE job_id=%s""",
        (name, json.dumps([{"stage": name, "at": _now().isoformat(), **(extra or {})}]), job_id))
    conn.commit()


def _finish(conn, job_id: int, state: str, **fields):
    sets, vals = ["state=%s", "completed_at=now()"], [state]
    for k, v in fields.items():
        sets.append(f"{k}=%s")
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    vals.append(job_id)
    conn.cursor().execute(
        f"UPDATE watch_decision_refresh_jobs SET {', '.join(sets)} WHERE job_id=%s", vals)
    conn.commit()


def _symbol_lock(cur, symbol: str) -> bool:
    cur.execute("SELECT pg_try_advisory_lock(%s, hashtext(%s))", (ADVISORY_LOCK_NS, symbol))
    return bool(cur.fetchone()[0])


def _symbol_unlock(cur, symbol: str):
    cur.execute("SELECT pg_advisory_unlock(%s, hashtext(%s))", (ADVISORY_LOCK_NS, symbol))


def process_one_job(conn) -> bool:
    """Claim and execute one job. Returns False when the queue is empty."""
    import packet_invalidation as pi
    cur = conn.cursor()
    row = _claim_job(cur)
    conn.commit()
    if not row:
        return False
    job_id, run_id, sym, scope, tier = row
    deadline = time.time() + JOB_SLA_SECONDS
    source_calls: dict = {}
    locked = False
    try:
        _stage(conn, job_id, "lock")
        locked = _symbol_lock(cur, sym)
        conn.commit()
        if not locked:
            _finish(conn, job_id, "SKIPPED_LOCKED", error="another run holds the symbol lock")
            return True

        # assess: current packet vs current inputs
        _stage(conn, job_id, "assess")
        cur.execute("""SELECT packet_id, packet FROM decision_packets
                       WHERE upper(symbol)=%s AND superseded_by IS NULL
                       ORDER BY generated_at DESC LIMIT 1""", (sym,))
        prow = cur.fetchone()
        packet_before, packet_id_before = (prow[1], prow[0]) if prow else (None, None)
        snap = pi.build_current_input_snapshot(sym, conn)
        hash_before = pi.compute_input_hash(snap)
        cmp = pi.compare_packet_inputs(packet_before, snap) if packet_before else \
            {"inputs_match": False, "invalidation_reasons": ["PACKET_ABSENT"]}
        reasons = cmp.get("invalidation_reasons") or []
        cur.execute("""SELECT force FROM watch_decision_refresh_runs WHERE run_id=%s""", (run_id,))
        force = bool(cur.fetchone()[0])
        if scope != "INPUTS_ONLY" and cmp.get("inputs_match") and packet_before and not force:
            _finish(conn, job_id, "SKIPPED_CURRENT",
                    input_hash_before=hash_before, packet_id_before=packet_id_before,
                    invalidation_reasons=[])
            return True

        # inputs: refresh evidence (scoped)
        _stage(conn, job_id, "inputs")
        if scope == "AFFECTED_DIMENSIONS":
            dims = sorted({REASON_TO_DIMENSION[r] for r in reasons if r in REASON_TO_DIMENSION})
            dims = dims or ["price", "technicals"]
        else:  # INPUTS_ONLY and FULL_STRATEGY refresh the full evidence set
            dims = list(ALL_DIMENSIONS)
        for d in dims:
            if time.time() > deadline:
                raise TimeoutError(f"SLA {JOB_SLA_SECONDS}s exceeded during inputs:{d}")
            _refresh_dimension(sym, d, source_calls)
        # Foreign enrichers may have killed connections (including db_adapter's
        # shared one) — job bookkeeping continues on a verified-alive private conn.
        conn = _fresh_conn(conn); cur = conn.cursor()

        if scope == "INPUTS_ONLY":
            snap2 = pi.build_current_input_snapshot(sym, conn)
            _finish(conn, job_id, "COMPLETE",
                    input_hash_before=hash_before,
                    input_hash_after=pi.compute_input_hash(snap2),
                    packet_id_before=packet_id_before, packet_id_after=packet_id_before,
                    invalidation_reasons=reasons, refreshed_dimensions=dims,
                    source_calls=source_calls)
            return True

        # rebuild: the decision (LOCAL_QUANT = zero model lanes)
        _stage(conn, job_id, "rebuild", {"tier": tier})
        import shadow_decision_service as svc
        run_models = tier != "LOCAL_QUANT"
        stage_cb = lambda s: _stage(conn, job_id, f"rebuild:{s}")
        packet = svc.evaluate(sym, conn, origin="v5_refresh",
                              requested_by=f"wdr_run_{run_id}",
                              run_models=run_models, on_stage=stage_cb)
        packet_id_after = svc.persist(packet, origin="v5_refresh", run_id=None)  # returns packet_id int
        lane_calls = 0
        if run_models:
            mr = packet.get("model_review") or {}
            lc = mr.get("lanes_completed") or 0
            lane_calls = len(lc) if isinstance(lc, (list, tuple)) else int(lc)

        # policy: recompute advisory action from persisted truth (parity evidence)
        _stage(conn, job_id, "policy")
        import decision_action_policy as dap
        action = dap.evaluate_action(packet, packet_id=packet_id_after)

        # readback: DB parity
        _stage(conn, job_id, "readback")
        cur.execute("""SELECT packet_id, packet->>'input_hash' FROM decision_packets
                       WHERE upper(symbol)=%s AND superseded_by IS NULL""", (sym,))
        live = cur.fetchone()
        if not live or live[0] != packet_id_after:
            raise RuntimeError(f"readback parity failed: live={live and live[0]} persisted={packet_id_after}")
        _finish(conn, job_id, "COMPLETE",
                input_hash_before=hash_before, input_hash_after=live[1],
                packet_id_before=packet_id_before, packet_id_after=packet_id_after,
                invalidation_reasons=reasons, refreshed_dimensions=dims,
                source_calls=source_calls, lane_calls=lane_calls)
        return True
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        # SystemExit from an imported legacy module must mark the JOB failed and
        # keep the worker alive for the rest of the queue.
        conn = _fresh_conn(conn)
        try:
            conn.rollback()
        except Exception:
            pass
        _finish(conn, job_id, "FAILED",
                failure_class=type(e).__name__, error=str(e)[:400],
                source_calls=source_calls)
        return True
    finally:
        conn = _fresh_conn(conn)
        if locked:
            try:
                # Advisory locks are session-scoped: if the original session died,
                # the lock is already gone and this unlock is a harmless no-op.
                _symbol_unlock(conn.cursor()); conn.commit()
            except Exception:
                pass
        _reconcile_run(conn, run_id)


def _reconcile_run(conn, run_id: int):
    cur = conn.cursor()
    cur.execute("""SELECT count(*) FILTER (WHERE state IN ('QUEUED','RUNNING')),
                          count(*) FILTER (WHERE state IN ('COMPLETE','SKIPPED_CURRENT')),
                          count(*) FILTER (WHERE state IN ('FAILED','CANCELLED','SKIPPED_LOCKED')),
                          coalesce(sum(lane_calls),0)
                   FROM watch_decision_refresh_jobs WHERE run_id=%s""", (run_id,))
    live, done, bad, lanes = cur.fetchone()
    if live:
        cur.execute("""UPDATE watch_decision_refresh_runs
                       SET state='RUNNING', started_at=coalesce(started_at, now())
                       WHERE run_id=%s AND state='QUEUED'""", (run_id,))
    else:
        state = "COMPLETE" if bad == 0 else ("FAILED" if done == 0 else "PARTIAL")
        cur.execute("""UPDATE watch_decision_refresh_runs
                       SET state=%s, completed_at=now(), actual_lane_calls=%s
                       WHERE run_id=%s""", (state, lanes, run_id))
    conn.commit()


def run_worker_loop():
    conn = _conn()
    while True:
        conn = _fresh_conn(conn)
        if not process_one_job(conn):
            break


def sweep_stale(grace_seconds: int = 300) -> dict:
    """Fail RUNNING jobs whose worker died without reaching a terminal state
    (heartbeat older than the grace window), then reconcile their runs. Cron-run
    alongside the scheduler so no job can sit RUNNING forever."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""UPDATE watch_decision_refresh_jobs
                   SET state='FAILED', failure_class='WorkerDied',
                       error='worker heartbeat expired (stale-job sweep)', completed_at=now()
                   WHERE state='RUNNING' AND heartbeat_at < now() - make_interval(secs => %s)
                   RETURNING job_id, run_id, symbol""", (grace_seconds,))
    swept = cur.fetchall()
    conn.commit()
    for _, rid, _ in swept:
        _reconcile_run(conn, rid)
    # also release any QUEUED jobs older than 30m with no worker (spawn died pre-claim)
    cur.execute("""SELECT count(*) FROM watch_decision_refresh_jobs
                   WHERE state='QUEUED' AND created_at < now() - interval '30 minutes'""")
    orphaned_queued = cur.fetchone()[0]
    return {"swept": [{"job_id": j, "run_id": r, "symbol": s} for j, r, s in swept],
            "stale_queued": orphaned_queued}


# ── status / freshness contract (Section 8) ──────────────────────────────────
def run_status(run_id: int) -> dict:
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT state, scope, analysis_tier, symbols_requested, created_at,
                          completed_at, estimated_lane_calls, actual_lane_calls
                   FROM watch_decision_refresh_runs WHERE run_id=%s""", (run_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "unknown run_id"}
    cur.execute("""SELECT symbol, state, stage, packet_id_after, failure_class, error,
                          invalidation_reasons, refreshed_dimensions
                   FROM watch_decision_refresh_jobs WHERE run_id=%s ORDER BY symbol""", (run_id,))
    jobs = [{"symbol": j[0], "state": j[1], "stage": j[2], "packet_id_after": j[3],
             "failure_class": j[4], "error": j[5], "invalidation_reasons": j[6],
             "refreshed_dimensions": j[7]} for j in cur.fetchall()]
    return {"ok": True, "run_id": run_id, "state": r[0], "scope": r[1], "analysis_tier": r[2],
            "symbols_requested": r[3], "created_at": r[4].isoformat(),
            "completed_at": r[5].isoformat() if r[5] else None,
            "estimated_lane_calls": r[6], "actual_lane_calls": r[7], "jobs": jobs}


def build_freshness(symbol: str, conn=None) -> dict:
    """The Section-8 freshness contract for one symbol: DB truth + policy cadence,
    with timestamps present in EVERY state (stale included)."""
    import packet_invalidation as pi
    conn = conn or _conn(); cur = conn.cursor()
    sym = symbol.upper()
    cur.execute("""SELECT packet_id, generated_at, packet, model_review_mode
                   FROM decision_packets
                   WHERE upper(symbol)=%s AND superseded_by IS NULL
                   ORDER BY generated_at DESC LIMIT 1""", (sym,))
    prow = cur.fetchone()
    cur.execute("""SELECT state, stage FROM watch_decision_refresh_jobs
                   WHERE symbol=%s AND state IN ('QUEUED','RUNNING')
                   ORDER BY created_at DESC LIMIT 1""", (sym,))
    live_job = cur.fetchone()
    cur.execute("""SELECT state, completed_at, error FROM watch_decision_refresh_jobs
                   WHERE symbol=%s AND state IN ('COMPLETE','FAILED')
                   ORDER BY completed_at DESC LIMIT 1""", (sym,))
    last_job = cur.fetchone()

    snap = pi.build_current_input_snapshot(sym, conn)
    sources = {k: v for k, v in (snap or {}).items() if isinstance(v, dict)}
    input_ts = [str(v2) for v in sources.values() if isinstance(v, dict)
                for k2, v2 in v.items()
                if v2 and (k2.endswith("_as_of") or k2 in ("as_of", "fetched_at"))]

    if not prow:
        overall, reasons, generated_at, mode = "STALE", ["PACKET_ABSENT"], None, None
        valid_until = None
    else:
        packet_id, generated_at, packet, mode = prow
        cmp = pi.compare_packet_inputs(packet, snap)
        reasons = cmp.get("invalidation_reasons") or []
        ttl_h = pi.effective_ttl_hours()
        valid_until = generated_at + timedelta(hours=ttl_h)
        if live_job:
            overall = "REFRESHING"
        elif cmp.get("inputs_match"):
            overall = "DUE_SOON" if _now() > valid_until - timedelta(minutes=30) else "CURRENT"
        elif last_job and last_job[0] == "FAILED" and (_now() - (last_job[1] or _now())) < timedelta(hours=2):
            overall = "FAILED"
        else:
            overall = "STALE"

    tier_map = {"UNAVAILABLE": "LOCAL_QUANT", "BLIND": "STANDARD_BLIND",
                "SINGLE_LANE": "STANDARD_BLIND", "PREMIUM": "PREMIUM_REVIEW"}
    pol = load_policy()
    prio = classify_priority(sym, conn)
    cadence_min = ((pol.get("tiers") or {}).get(prio) or {}).get("full_local_packet_max_minutes")
    next_due = (generated_at + timedelta(minutes=int(cadence_min))
                if (prow and cadence_min) else valid_until)
    return {
        "freshness": {
            "overall_state": overall,
            "last_input_refresh_at": max(input_ts) if input_ts else None,
            "last_strategy_build_at": generated_at.isoformat() if prow else None,
            "valid_until": valid_until.isoformat() if prow and valid_until else None,
            "next_refresh_due_at": next_due.isoformat() if next_due else None,
            "invalidation_reasons": reasons,
            "refresh_in_flight": {"state": live_job[0], "stage": live_job[1]} if live_job else None,
            "last_refresh_error": last_job[2] if last_job and last_job[0] == "FAILED" else None,
            "analysis_tier": tier_map.get(mode or "UNAVAILABLE", "LOCAL_QUANT") if prow else None,
            "policy_version": policy_version(),
            "priority_tier": prio,
        },
        "sources": sources,
    }


def classify_priority(symbol: str, conn) -> str:
    """P0 held/starred · P1 buy-rated actives · P2 top-200 watch · P3 rest."""
    cur = conn.cursor()
    sym = symbol.upper()
    try:
        hold = json.loads((PROJECT_ROOT / "data" / "state" / "holdings.json").read_text())
        if any(str(h.get("symbol", "")).upper() == sym for h in hold.get("holdings", [])):
            return "P0"
    except Exception:
        pass
    try:
        cur.execute("SELECT 1 FROM operator_starred_symbols WHERE upper(symbol)=%s", (sym,))
        if cur.fetchone():
            return "P0"
        cur.execute("""SELECT hermes_rank, status FROM watchlist_items
                       WHERE upper(symbol)=%s ORDER BY updated_at DESC LIMIT 1""", (sym,))
        r = cur.fetchone()
        if r:
            rank = r[0]
            if rank is not None and int(rank) <= 50:
                return "P1"
            return "P2"
    except Exception:
        conn.rollback()
    return "P3"


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--enqueue", nargs="+")
    ap.add_argument("--scope", default="FULL_STRATEGY", choices=SCOPES)
    ap.add_argument("--tier", default="LOCAL_QUANT", choices=TIERS)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", type=int)
    ap.add_argument("--freshness")
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    if a.worker:
        run_worker_loop()
    elif a.enqueue:
        print(json.dumps(enqueue_run(a.enqueue, scope=a.scope, analysis_tier=a.tier,
                                     force=a.force, requested_by="cli"), indent=2, default=str))
    elif a.status:
        print(json.dumps(run_status(a.status), indent=2, default=str))
    elif a.freshness:
        print(json.dumps(build_freshness(a.freshness), indent=2, default=str))
    elif a.sweep:
        print(json.dumps(sweep_stale(), indent=2, default=str))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
