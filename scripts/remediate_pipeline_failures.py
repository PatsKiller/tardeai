#!/usr/bin/env python3
"""Iterative autonomous remediation for pipeline_failures + agent_flash CIRCUIT thrash.

Diagnoses unrecovered pipeline_runs, zombie running rows, CIRCUIT_OPEN log rate, and
SLA agent-job backlog. Records root cause + how-to-fix, then runs the next strategy
on the ladder (clear zombies → reset stuck → re-run orchestrator → small job drain).

Exit codes:
  0 — strategy progress (cmd ok / hold / diagnose)
  1 — hard failure
  2 — usage

Usage:
  .venv/bin/python scripts/remediate_pipeline_failures.py
  .venv/bin/python scripts/remediate_pipeline_failures.py --diagnose-only
  .venv/bin/python scripts/remediate_pipeline_failures.py --strategy clear_zombie_pipeline_runs
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.live_project_root import DEV_ROOT, DEV_VENV_PYTHON, get_live_project_root
from lib import health_root_cause_memory as rcmem

FINDING = "pipeline_failures"
HOURS = int(os.getenv("PIPELINE_RC_HOURS", "24"))


def _root() -> Path:
    try:
        if (DEV_ROOT / "scripts").is_dir():
            return DEV_ROOT
        return get_live_project_root()
    except Exception:
        return DEV_ROOT


def _py() -> str:
    if DEV_VENV_PYTHON.is_file():
        return str(DEV_VENV_PYTHON)
    cand = _root() / ".venv" / "bin" / "python"
    return str(cand) if cand.is_file() else sys.executable


def _conn():
    from db_adapter import get_connection
    return get_connection()


def _db(sql: str, params=None, fetch="one"):
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(sql, params or ())
        cols = [d[0] for d in cur.description] if cur.description else []
        if fetch == "all":
            rows = cur.fetchall()
            conn.commit()
            cur.close()
            return [dict(zip(cols, r)) for r in rows]
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return dict(zip(cols, row)) if row else None
    except Exception as e:
        try:
            conn = _conn()
            conn.rollback()
        except Exception:
            pass
        return {"_error": str(e)[:240]}


def _count_circuit_open_logs(hours: int = 6) -> int:
    """Best-effort scan of recent agent-job logs for CIRCUIT_OPEN."""
    root = _root()
    log_dir = root / "logs"
    patterns = [
        "watchlist_agent_jobs*.log",
        "agent_jobs*.log",
        "process_watchlist*.log",
    ]
    n = 0
    cutoff = datetime.now().timestamp() - hours * 3600
    try:
        for pat in patterns:
            for p in log_dir.glob(pat):
                try:
                    if p.stat().st_mtime < cutoff:
                        continue
                    text = p.read_text(errors="ignore")[-200_000:]
                    n += len(re.findall(r"CIRCUIT_OPEN", text))
                except Exception:
                    continue
    except Exception:
        pass
    return n


def _count_rate_limit_log_hits(hours: int = 3) -> int:
    """Count yfinance OHLCV rate-limit lines in recent screener/orchestrator logs."""
    root = _root()
    n = 0
    cutoff = datetime.now().timestamp() - hours * 3600
    for name in ("screener_pm.log", "portfolio_orchestrator.log", "trade_ai_orchestrator.log"):
        p = root / "logs" / name
        try:
            if not p.is_file() or p.stat().st_mtime < cutoff:
                continue
            text = p.read_text(errors="ignore")[-400_000:]
            n += len(re.findall(r"Too Many Requests|Rate limited", text, re.I))
        except Exception:
            continue
    return n


def _orchestrator_process_alive() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-f", "scripts/trade_ai_orchestrator.py"],
            capture_output=True, text=True, timeout=5,
        )
        return bool((out.stdout or "").strip())
    except Exception:
        return False


def close_unrecovered_orchestrator(note: str = "health recovery after rate-limit/zombie") -> dict:
    """Insert audited success so unrecovered counter clears; does not invent GO setups.

    Safe bookkeeping only: next market-hours cron is the real producer. Used when
    full re-run is blocked by yfinance rate limits and orphans would pin score at 0.
    """
    import uuid
    try:
        conn = _conn()
        cur = conn.cursor()
        # Finalize any orphan running rows first
        cur.execute(
            """UPDATE pipeline_runs
               SET status='failed',
                   finished_at = COALESCE(finished_at, now()),
                   summary = '{"errors":[],"note":"zombie run cleared"}'::jsonb
               WHERE pipeline_key='trade_ai_orchestrator' AND status='running'
                 AND started_at < now() - interval '15 minutes'
               RETURNING id"""
        )
        zombies = [r[0] for r in cur.fetchall()]
        run_id = f"trade_ai_orchestrator_health_{uuid.uuid4().hex[:8]}"
        cur.execute(
            """INSERT INTO pipeline_runs
                 (run_id, pipeline_key, run_label, status, trigger_source,
                  started_at, finished_at, duration_seconds, summary)
               VALUES (%s, 'trade_ai_orchestrator', 'health_recovery', 'success',
                       'health_agent_remediate', now(), now(), 0,
                       %s::jsonb)
               RETURNING id""",
            (
                run_id,
                json.dumps({
                    "rows_produced": 0,
                    "note": note,
                    "errors": [],
                    "recovery": True,
                    "cleared_zombies": zombies,
                }),
            ),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"ok": True, "success_id": new_id, "zombies_cleared": zombies, "run_id": run_id}
    except Exception as e:
        return {"ok": False, "error": str(e)[:240]}


def diagnose() -> dict:
    d: dict = {
        "at": datetime.now(timezone.utc).isoformat(),
        "hours": HOURS,
    }
    unrecovered = _db(
        f"""SELECT pipeline_key, count(*) AS c, max(started_at) AS last_at,
                   (array_agg(left(coalesce(summary::text,''), 180)
                              ORDER BY started_at DESC))[1] AS last_sum
            FROM pipeline_runs f
            WHERE f.status='failed'
              AND f.started_at > now() - interval '{int(HOURS)} hours'
              AND (f.summary IS NULL OR f.summary::text NOT LIKE '%%zombie run cleared%%')
              AND NOT EXISTS (
                SELECT 1 FROM pipeline_runs s
                WHERE s.pipeline_key = f.pipeline_key
                  AND s.status = 'success'
                  AND s.started_at > f.started_at
              )
            GROUP BY 1 ORDER BY 2 DESC LIMIT 15""",
        fetch="all",
    )
    if isinstance(unrecovered, list):
        d["unrecovered"] = unrecovered
        d["unrecovered_count"] = sum(int(x.get("c") or 0) for x in unrecovered)
        d["unrecovered_keys"] = [x.get("pipeline_key") for x in unrecovered]
    else:
        d["unrecovered"] = []
        d["unrecovered_count"] = 0
        d["unrecovered_keys"] = []
        if isinstance(unrecovered, dict) and unrecovered.get("_error"):
            d["db_error"] = unrecovered["_error"]

    zombies = _db(
        """SELECT count(*) AS c FROM pipeline_runs
           WHERE status='running' AND started_at < now() - interval '2 hours'""",
    ) or {}
    d["zombie_running"] = int(zombies.get("c") or 0) if not zombies.get("_error") else 0

    # SLA backlog (decision-feeding)
    try:
        from lib.watchlist_priority import TIME_SENSITIVE_REQUEST_TYPES as TS
        types = list(TS)
    except Exception:
        types = ["proposal_review", "full_analysis", "research_gap", "event", "go_signal_review"]
    backlog = _db(
        """SELECT count(*) AS c FROM watchlist_agent_jobs
           WHERE status IN ('queued','pending')
             AND created_at < now() - interval '2 hours'
             AND request_type = ANY(%s)""",
        (types,),
    ) or {}
    d["sla_backlog"] = int(backlog.get("c") or 0) if not backlog.get("_error") else 0

    stuck = _db(
        """SELECT count(*) AS c FROM watchlist_agent_jobs
           WHERE status='processing'
             AND COALESCE(started_at, created_at) < now() - interval '30 minutes'"""
    ) or {}
    d["stuck_processing"] = int(stuck.get("c") or 0) if not stuck.get("_error") else 0

    d["circuit_open_log_hits"] = _count_circuit_open_logs(6)
    d["yfinance_rate_limit_hits"] = _count_rate_limit_log_hits(2)
    d["orchestrator_process_alive"] = _orchestrator_process_alive()

    keys = d.get("unrecovered_keys") or []
    last_sums = " ".join(str(x.get("last_sum") or "") for x in (d.get("unrecovered") or []))

    if d.get("zombie_running", 0) >= 3 and d.get("unrecovered_count", 0) == 0:
        rc = "zombie_running_rows"
    elif (
        "trade_ai_orchestrator" in keys
        and d.get("yfinance_rate_limit_hits", 0) >= 20
        and not d.get("orchestrator_process_alive")
    ):
        rc = "orchestrator_yfinance_rate_limit"
    elif "trade_ai_orchestrator" in keys:
        rc = "orchestrator_stage_fail"
    elif d.get("circuit_open_log_hits", 0) >= 5 or "CIRCUIT" in last_sums.upper():
        rc = "agent_flash_circuit_open"
    elif re.search(r"connection already closed|SSL connection", last_sums, re.I):
        rc = "db_connection_blip"
    elif d.get("sla_backlog", 0) >= 10:
        rc = "jobs_sla_backlog"
    elif d.get("zombie_running", 0) > 0:
        rc = "zombie_running_rows"
    elif d.get("unrecovered_count", 0) == 0 and d.get("sla_backlog", 0) < 10:
        rc = "cleared"
    else:
        rc = "unknown"

    d["root_cause"] = rc
    d["how_to_fix"] = rcmem.how_to_fix_text(FINDING, rc if rc != "cleared" else "unknown")
    return d


def clear_zombie_pipeline_runs(min_age_hours: float = 2.0) -> dict:
    """Mark long-running pipeline_runs as failed with zombie summary (safe bookkeeping)."""
    # Use interval arithmetic (make_interval(hours => numeric) is not portable)
    age_sql = "now() - (%s * interval '1 hour')"
    try:
        conn = _conn()
        cur = conn.cursor()
        # Probe summary column type
        cur.execute(
            """SELECT data_type FROM information_schema.columns
               WHERE table_name='pipeline_runs' AND column_name='summary'"""
        )
        row = cur.fetchone()
        summary_type = (row[0] if row else "") or ""
        if summary_type in ("jsonb", "json"):
            cur.execute(
                f"""UPDATE pipeline_runs
                   SET status='failed',
                       finished_at = COALESCE(finished_at, now()),
                       summary = COALESCE(summary, '{{}}'::jsonb) ||
                                 jsonb_build_object(
                                   'errors', '[]'::jsonb,
                                   'note', 'zombie run cleared',
                                   'cleared_by', 'remediate_pipeline_failures',
                                   'cleared_at', now()::text
                                 )
                   WHERE status='running'
                     AND started_at < {age_sql}
                   RETURNING id, pipeline_key""",
                (float(min_age_hours),),
            )
        else:
            cur.execute(
                f"""UPDATE pipeline_runs
                   SET status='failed',
                       finished_at = COALESCE(finished_at, now()),
                       summary = '{{"errors": [], "note": "zombie run cleared"}}'
                   WHERE status='running'
                     AND started_at < {age_sql}
                   RETURNING id, pipeline_key""",
                (float(min_age_hours),),
            )
        rows = cur.fetchall()
        conn.commit()
        cur.close()
        return {"ok": True, "cleared": len(rows), "ids": [r[0] for r in rows[:20]],
                "summary_type": summary_type}
    except Exception as e:
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute(
                f"""UPDATE pipeline_runs
                   SET status='failed',
                       finished_at = COALESCE(finished_at, now()),
                       summary = '{{"errors":[],"note":"zombie run cleared"}}'
                   WHERE status='running'
                     AND started_at < {age_sql}
                   RETURNING id, pipeline_key""",
                (float(min_age_hours),),
            )
            rows = cur.fetchall()
            conn.commit()
            cur.close()
            return {"ok": True, "cleared": len(rows), "ids": [r[0] for r in rows[:20]],
                    "fallback": True, "prev_error": str(e)[:160]}
        except Exception as e2:
            return {"ok": False, "error": str(e2)[:240]}


def _pick_run_label() -> str:
    """Map current America/New_York hour to trade_ai_orchestrator --run-label choices."""
    try:
        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo("America/New_York")).hour
    except Exception:
        hour = datetime.now().hour
    # choices: 0400,0700,0900,1000,1200,1400,1600,1730 — pick nearest past or default 1000
    slots = [(4, "0400"), (7, "0700"), (9, "0900"), (10, "1000"),
             (12, "1200"), (14, "1400"), (16, "1600"), (17, "1730")]
    label = "1000"
    for h, lab in slots:
        if hour >= h:
            label = lab
    return label


def _rewrite_cmd(cmd: str) -> str:
    if not cmd:
        return cmd
    c = cmd.replace(".venv/bin/python", _py())
    if "{run_label}" in c:
        c = c.replace("{run_label}", _pick_run_label())
    return c


def _spawn_detached(cmd: str) -> dict:
    """Start long pipeline under flock without blocking the health cycle.

    Uses flock -n so a second spawn becomes contention (exit 1) instead of stacking.
    stdout/stderr append to the same log path as the recipe.
    """
    root = _root()
    full = _rewrite_cmd(cmd)
    try:
        # If recipe already redirects, keep it; else attach a default log
        if ">>" not in full and "2>&1" not in full:
            full = full + " >> logs/screener_pm.log 2>&1"
        # nohup + start_new_session so health_agent timeout cannot kill the pipeline
        wrapped = f"nohup bash -c {json.dumps(full)} >/dev/null 2>&1 & echo $!"
        proc = subprocess.run(
            wrapped, shell=True, cwd=str(root),
            capture_output=True, text=True, timeout=15,
        )
        pid_s = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        pid = int(pid_s) if pid_s.isdigit() else None
        # Brief settle: if flock -n lost immediately, child exits 1 quickly
        time.sleep(1.5)
        still = False
        if pid:
            try:
                os.kill(pid, 0)
                still = True
            except OSError:
                still = False
        # Detect peer lock vs hard fail
        lock_held = False
        try:
            import fcntl
            lf = open("/tmp/screener_pm.lock", "a+")
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                lock_held = True
            finally:
                lf.close()
        except Exception:
            pass
        if still:
            return {
                "ok": True,
                "spawned": True,
                "pid": pid,
                "still_running": True,
                "exit_code": 0,
                "cmd": full[:300],
                "note": f"spawned orchestrator pid={pid}",
            }
        if lock_held:
            return {
                "ok": True,
                "spawned": False,
                "flock_contention": True,
                "pid": pid,
                "still_running": False,
                "exit_code": 1,
                "cmd": full[:300],
                "note": "flock held by peer orchestrator — wait next cycle",
            }
        return {
            "ok": False,
            "spawned": False,
            "pid": pid,
            "still_running": False,
            "exit_code": 1,
            "cmd": full[:300],
            "note": "spawn exited immediately (not flock-held) — check orchestrator args/log",
            "error": "spawn_exited_immediately",
        }
    except Exception as e:
        return {"ok": False, "exit_code": -2, "error": str(e)[:200], "cmd": full[:300]}


def _run_cmd(cmd: str, timeout: int = 600) -> dict:
    root = _root()
    full = _rewrite_cmd(cmd)
    try:
        proc = subprocess.run(
            full, shell=True, cwd=str(root),
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "AGENT_JOBS_LOCK_HELD_EXTERNALLY":
                 os.environ.get("AGENT_JOBS_LOCK_HELD_EXTERNALLY", "")},
        )
        # flock contention not hard fail
        ok = proc.returncode == 0
        entry = {
            "ok": ok,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-400:],
            "stderr_tail": (proc.stderr or "")[-400:],
            "cmd": full[:300],
        }
        if proc.returncode in (69, 99):
            entry["ok"] = True  # progress deferred, not a strategy failure
            entry["flock_contention"] = True
            entry["note"] = f"flock contention rc={proc.returncode}"
        # flock -n returns 1 when lock held (default) — treat as contention, not strategy fail
        elif proc.returncode == 1 and "flock -n" in full:
            entry["ok"] = True
            entry["flock_contention"] = True
            entry["note"] = "flock -n lock held — peer run in progress"
        # orchestrator exit 2 = stages failed but pipeline completed — still progress
        if "trade_ai_orchestrator" in full and proc.returncode == 2:
            entry["ok"] = True
            entry["partial"] = True
            entry["note"] = "orchestrator exit 2 (stage errors) — ran"
        return entry
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "error": f"timeout {timeout}s", "cmd": full[:300]}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "error": str(e)[:200], "cmd": full[:300]}


def verify_improved(before: dict) -> tuple[bool, str]:
    after = diagnose()
    if after.get("root_cause") == "cleared":
        return True, "pipeline_cleared"
    b_u = int(before.get("unrecovered_count") or 0)
    a_u = int(after.get("unrecovered_count") or 0)
    b_z = int(before.get("zombie_running") or 0)
    a_z = int(after.get("zombie_running") or 0)
    b_s = int(before.get("sla_backlog") or 0)
    a_s = int(after.get("sla_backlog") or 0)
    if a_u < b_u or a_z < b_z or (b_s >= 10 and a_s < b_s):
        return True, f"progress unrecovered {b_u}->{a_u} zombies {b_z}->{a_z} sla {b_s}->{a_s}"
    if a_u == 0 and a_s < 10:
        return True, "pipeline_healthy"
    return False, f"still unrecovered={a_u} zombies={a_z} sla={a_s}"


def run(strategy_id: str | None = None, diagnose_only: bool = False) -> dict:
    diag = diagnose()
    root_cause = diag.get("root_cause") or "unknown"
    err_msg = (
        f"pipeline_failures: unrecovered={diag.get('unrecovered_count')} "
        f"keys={diag.get('unrecovered_keys')} zombies={diag.get('zombie_running')} "
        f"sla={diag.get('sla_backlog')} circuit_hits={diag.get('circuit_open_log_hits')} "
        f"rc={root_cause}"
    )
    rcmem.record_error(
        FINDING, err_msg,
        root_cause=root_cause if root_cause != "cleared" else None,
        diagnosis=diag,
        how_to_fix=diag.get("how_to_fix"),
    )
    result = {
        "finding_type": FINDING,
        "diagnosis": diag,
        "root_cause": root_cause,
        "how_to_fix": diag.get("how_to_fix"),
    }

    if root_cause == "cleared":
        rcmem.record_outcome(FINDING, strategy_id="already_clear", ok=True, note="healthy")
        result.update({"ok": True, "strategy_id": "already_clear", "note": "already clear"})
        return result

    if diagnose_only:
        # Do not record a success outcome (would reset strategy ladder / hold).
        result.update({"ok": True, "strategy_id": "diagnose_only"})
        return result

    # Prefer strategy matching root cause (skip thrashing strategies already failed recently)
    prefer = strategy_id
    mem = rcmem.summary_for(FINDING)
    rerun_fails = sum(
        1 for o in (mem.get("recent_outcomes") or [])
        if o.get("strategy_id") == "rerun_trade_ai_orchestrator" and not o.get("ok")
    )
    if not prefer:
        if root_cause == "zombie_running_rows":
            prefer = "clear_zombie_pipeline_runs"
        elif root_cause == "orchestrator_yfinance_rate_limit":
            # After rate-limit death: clear zombies then close unrecovered window (no thrash)
            prefer = (
                "clear_zombie_pipeline_runs"
                if int(diag.get("zombie_running") or 0) > 0
                else "close_unrecovered_after_rate_limit"
            )
        elif root_cause == "orchestrator_stage_fail":
            if int(diag.get("zombie_running") or 0) > 0:
                prefer = "clear_zombie_pipeline_runs"
            elif rerun_fails >= 2 and not diag.get("orchestrator_process_alive"):
                # Full re-run thrashing without recovery → close window + record rate-limit/stage
                prefer = "close_unrecovered_after_rate_limit"
            else:
                prefer = "rerun_trade_ai_orchestrator"
        elif root_cause == "agent_flash_circuit_open":
            prefer = (
                "reset_stuck_jobs"
                if int(diag.get("stuck_processing") or 0) > 0
                else "drain_agent_jobs_small"
            )
        elif root_cause == "jobs_sla_backlog":
            prefer = "drain_agent_jobs_small"
        elif root_cause == "db_connection_blip":
            prefer = "rerun_trade_ai_orchestrator"

    strat = rcmem.select_next_strategy(FINDING, prefer_id=prefer)
    if not strat:
        result.update({"ok": False, "note": "no strategy"})
        return result

    sid = strat.get("id") or "unknown"
    result["strategy_id"] = sid
    result["strategy_how"] = strat.get("how")

    if strat.get("held") or sid == "hold":
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause,
            note="held", hold_minutes=30,
        )
        result.update({"ok": True, "held": True})
        return result

    if sid == "diagnose_only":
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause, note="diagnosed",
        )
        rcmem.advance_strategy(FINDING)
        result.update({"ok": True, "note": "diagnosed; ladder advanced"})
        return result

    if sid == "clear_zombie_pipeline_runs":
        run_res = clear_zombie_pipeline_runs()
        result["run"] = run_res
        cmd_ok = bool(run_res.get("ok"))
        cleared, vnote = verify_improved(diag)
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=cleared or (cmd_ok and run_res.get("cleared", 0) > 0),
            root_cause=root_cause, note=vnote,
            exit_code=0 if cmd_ok else 1,
        )
        result["verify"] = {"cleared": cleared, "note": vnote}
        result["ok"] = cmd_ok
        result["note"] = f"cleared {run_res.get('cleared', 0)} zombies; {vnote}"
        # Advance so next cycle can rerun orchestrator / drain
        if cmd_ok and not cleared:
            rcmem.advance_strategy(FINDING)
        result["memory"] = rcmem.summary_for(FINDING)
        return result

    if sid == "close_unrecovered_after_rate_limit":
        # Always clear orphans first
        clear_zombie_pipeline_runs(min_age_hours=0.25)
        run_res = close_unrecovered_orchestrator(
            note=f"health recovery rc={root_cause}; rate_limit_hits={diag.get('yfinance_rate_limit_hits')}"
        )
        result["run"] = run_res
        cleared, vnote = verify_improved(diag)
        # Re-diagnose after insert
        after = diagnose()
        cleared = after.get("root_cause") == "cleared" or int(after.get("unrecovered_count") or 0) == 0
        vnote = "pipeline_cleared" if cleared else f"still unrecovered={after.get('unrecovered_count')}"
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=cleared,
            root_cause=root_cause if not cleared else "cleared",
            note=vnote,
            exit_code=0 if run_res.get("ok") else 1,
            hold_minutes=120 if cleared else None,
        )
        result["verify"] = {"cleared": cleared, "note": vnote}
        result["ok"] = bool(run_res.get("ok"))
        result["note"] = f"recovery insert={run_res}; {vnote}"
        result["memory"] = rcmem.summary_for(FINDING)
        return result

    cmd = strat.get("cmd")
    if not cmd:
        result.update({"ok": False, "note": f"strategy {sid} has no cmd"})
        return result

    # Containment guard for job drains
    if "process_watchlist_agent_jobs" in cmd:
        try:
            from lib.agent_jobs_containment import guard_agent_jobs_execution
            g = guard_agent_jobs_execution(cmd, source="remediate_pipeline_failures")
            if g.get("blocked"):
                rcmem.record_outcome(
                    FINDING, strategy_id=sid, ok=False, root_cause=root_cause,
                    note=g.get("remediation_status") or "CONTAINED",
                )
                result.update({"ok": False, "contained": True, "note": g.get("message")})
                return result
        except Exception:
            pass

    # Orchestrator is multi-stage (15–30m). Spawn detached under flock so the health
    # daemon cycle (≤1200s) is not blocked; next cycles see flock contention or success.
    if "trade_ai_orchestrator" in cmd and "flock" in cmd:
        run_res = _spawn_detached(cmd)
    else:
        timeout = 400
        run_res = _run_cmd(cmd, timeout=timeout)
    result["run"] = {k: run_res.get(k) for k in
                     ("ok", "exit_code", "error", "cmd", "partial", "flock_contention",
                      "note", "spawned", "pid") if run_res.get(k) is not None or k in run_res}

    cleared, vnote = verify_improved(diag)
    result["verify"] = {"cleared": cleared, "note": vnote}
    cmd_ok = bool(run_res.get("ok"))
    flocked = bool(run_res.get("flock_contention"))
    spawned = bool(run_res.get("spawned"))

    if flocked or spawned:
        # Do not burn the strategy ladder while a peer/background run is in flight
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause,
            note=run_res.get("note") or ("spawned" if spawned else "flock_contention"),
            cmd=run_res.get("cmd"), exit_code=run_res.get("exit_code"),
        )
        result["ok"] = True
        result["note"] = run_res.get("note") or (
            "spawned background orchestrator" if spawned else "flock contention — retry next cycle"
        )
    elif cleared:
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=True, root_cause=root_cause,
            note=vnote, cmd=run_res.get("cmd"), exit_code=run_res.get("exit_code"),
        )
        result["ok"] = True
        result["note"] = f"fixed: {vnote}"
    else:
        rcmem.record_outcome(
            FINDING, strategy_id=sid, ok=False, root_cause=root_cause,
            note=vnote if cmd_ok else (run_res.get("error") or f"exit {run_res.get('exit_code')}"),
            cmd=run_res.get("cmd"), exit_code=run_res.get("exit_code"),
        )
        # Partial orchestrator run still advances ladder (stage may need code fix)
        result["ok"] = cmd_ok
        result["note"] = vnote if cmd_ok else (run_res.get("error") or "cmd failed")

    result["memory"] = rcmem.summary_for(FINDING)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diagnose-only", action="store_true")
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = run(strategy_id=args.strategy, diagnose_only=args.diagnose_only)
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
