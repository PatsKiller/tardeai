#!/usr/bin/env python3
"""health_agent_daemon.py — Continuous Layer-4 Health score + auto-remediate loop.

Runs without crontab (systemd user service). Adaptive sleep:
  healthy   → less frequent
  degraded  → medium
  unhealthy → fast recheck + tier1 escalation drain

Uses the same flock as cron (`/tmp/health_agent.lock`) so cron + daemon never double-run.

Usage:
    .venv/bin/python scripts/health_agent_daemon.py
    .venv/bin/python scripts/health_agent_daemon.py --once
    .venv/bin/python scripts/health_agent_daemon.py --no-escalation
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Prefer DEV tree (has .venv + full scripts); health_agent resolves live stamp for state.
from lib.live_project_root import DEV_ROOT, DEV_VENV_PYTHON, get_live_project_root

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if DEV_ROOT.is_dir():
    PROJECT_ROOT = DEV_ROOT

LOCK_PATH = Path(os.environ.get("HEALTH_AGENT_LOCK", "/tmp/health_agent.lock"))
ESCALATION_LOCK = Path("/tmp/tradeai_escalation_handler.lock")
STATE_NAME = ("data", "runtime", "health_agent_daemon_state.json")

DEFAULT_CADENCE = {
    "healthy": 1800,    # 30m
    "degraded": 300,    # 5m
    "unhealthy": 90,    # 90s
    "unknown": 300,
}


def _py() -> str:
    if DEV_VENV_PYTHON.is_file():
        return str(DEV_VENV_PYTHON)
    cand = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(cand) if cand.is_file() else sys.executable


def _state_paths() -> list[Path]:
    paths = []
    try:
        live = get_live_project_root()
        paths.append(Path(live).joinpath(*STATE_NAME))
    except Exception:
        pass
    paths.append(PROJECT_ROOT.joinpath(*STATE_NAME))
    # de-dupe
    out, seen = [], set()
    for p in paths:
        k = str(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _save_state(st: dict) -> None:
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(st, indent=2, default=str) + "\n"
    for p in _state_paths():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        except Exception:
            pass


def _load_policy_cadence() -> dict:
    try:
        pol_path = PROJECT_ROOT / "config" / "health_agent_policy.json"
        if pol_path.is_file():
            pol = json.loads(pol_path.read_text())
            d = (pol.get("daemon") or {}).get("cadence_seconds") or {}
            if isinstance(d, dict) and d:
                return {**DEFAULT_CADENCE, **{k: int(v) for k, v in d.items()}}
    except Exception:
        pass
    return dict(DEFAULT_CADENCE)


def _cadence_seconds(status: str, score: float | None) -> int:
    cad = _load_policy_cadence()
    st = (status or "unknown").lower()
    if st not in cad and score is not None:
        if score >= 85:
            st = "healthy"
        elif score >= 65:
            st = "degraded"
        else:
            st = "unhealthy"
    return int(cad.get(st) or cad.get("unknown") or 300)


def _run_health(no_enqueue: bool = False, no_alert: bool = False) -> dict:
    """Run one health_agent cycle under flock. Returns summary dict."""
    py = _py()
    cmd = [py, str(PROJECT_ROOT / "scripts" / "health_agent.py")]
    if no_enqueue:
        cmd.append("--no-enqueue")
    if no_alert:
        cmd.append("--no-alert")
    cmd.append("--json")

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1200,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "unhealthy",
            "overall_score": 0,
            "error": "health_agent timeout 1200s",
            "elapsed_s": round(time.time() - t0, 1),
        }

    score, status = None, "unknown"
    enqueued, remediated_ok = 0, 0
    # Parse last JSON object from stdout
    out = proc.stdout or ""
    try:
        i = out.find("{")
        if i >= 0:
            # health may print lines then JSON — take from first { to end, or balanced
            raw = out[i:]
            # if multiple objects, prefer last complete-looking parse
            snap = None
            for start in range(len(out) - 1, -1, -1):
                if out[start] == "{":
                    try:
                        snap = json.loads(out[start:])
                        break
                    except Exception:
                        continue
            if snap is None:
                snap = json.loads(raw)
            score = snap.get("overall_score")
            status = snap.get("status") or status
            enqueued = int(snap.get("enqueued") or 0)
            rem = snap.get("remediated") or []
            remediated_ok = sum(1 for r in rem if r.get("ok"))
    except Exception as e:
        # Fall back to status file
        try:
            live = get_live_project_root()
            for p in (
                Path(live) / "data" / "portfolios" / "state" / "health_agent_status.json",
                PROJECT_ROOT / "data" / "portfolios" / "state" / "health_agent_status.json",
            ):
                if p.is_file():
                    snap = json.loads(p.read_text())
                    score = snap.get("overall_score")
                    status = snap.get("status") or status
                    break
        except Exception:
            pass
        if score is None:
            return {
                "ok": proc.returncode == 0,
                "status": status,
                "overall_score": score,
                "error": f"parse:{e}",
                "stderr_tail": (proc.stderr or "")[-400:],
                "elapsed_s": round(time.time() - t0, 1),
            }

    return {
        "ok": proc.returncode == 0,
        "status": status,
        "overall_score": score,
        "enqueued": enqueued,
        "remediated_ok": remediated_ok,
        "returncode": proc.returncode,
        "elapsed_s": round(time.time() - t0, 1),
        "stderr_tail": (proc.stderr or "")[-200:] if proc.returncode else "",
    }


def _run_escalation_tier1(*, background: bool = True) -> dict:
    """Drain escalation queue (tier1 only).

    Default: fire-and-forget background process so a stuck ingest/backup cannot
    block the health score loop for 10 minutes (was making automation look dead).
    """
    py = _py()
    cmd = [py, str(PROJECT_ROOT / "scripts" / "claude_escalation_handler.py"), "--tier1-only"]
    log_path = PROJECT_ROOT / "logs" / "claude_escalation_daemon.log"
    try:
        lock_fd = os.open(str(ESCALATION_LOCK), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            return {"ok": True, "skipped": "escalation_lock_held", "elapsed_s": 0}
        # Release lock before spawn — child acquires its own flock in handler
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(lock_fd)

        if background:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logf = open(log_path, "a")
            # Use shell flock so we don't double-run with cron
            shell_cmd = (
                f"flock -n {ESCALATION_LOCK} {py} "
                f"{PROJECT_ROOT / 'scripts' / 'claude_escalation_handler.py'} --tier1-only"
            )
            subprocess.Popen(
                shell_cmd,
                shell=True,
                cwd=str(PROJECT_ROOT),
                stdout=logf,
                stderr=logf,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            return {"ok": True, "spawned": True, "log": str(log_path), "elapsed_s": 0}

        t0 = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_s": round(time.time() - t0, 1),
            "stdout_tail": (proc.stdout or "")[-300:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "escalation timeout", "elapsed_s": 180}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "elapsed_s": 0}


def run_cycle(*, no_enqueue: bool, no_alert: bool, run_escalation: bool) -> dict:
    """One health cycle under /tmp/health_agent.lock; optional escalation when unhealthy."""
    lock_fd = os.open(str(LOCK_PATH), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {
                "skipped": "health_lock_held",
                "status": "unknown",
                "overall_score": None,
                "ok": True,
            }
        try:
            os.ftruncate(lock_fd, 0)
            os.write(lock_fd, f"pid={os.getpid()}\n".encode())
        except Exception:
            pass

        result = _run_health(no_enqueue=no_enqueue, no_alert=no_alert)
        status = (result.get("status") or "unknown").lower()
        score = result.get("overall_score")

        esc = None
        if run_escalation and status in ("unhealthy", "degraded"):
            esc = _run_escalation_tier1()
            result["escalation"] = esc

        return result
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(lock_fd)
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Continuous Health Agent daemon (no cron required)")
    ap.add_argument("--once", action="store_true", help="Single cycle then exit")
    ap.add_argument("--no-enqueue", action="store_true")
    ap.add_argument("--no-alert", action="store_true")
    ap.add_argument("--no-escalation", action="store_true", help="Do not run tier1 escalation after unhealthy cycles")
    ap.add_argument("--min-sleep", type=int, default=30, help="Floor sleep seconds")
    args = ap.parse_args()

    print(
        json.dumps(
            {
                "daemon": "health_agent_daemon",
                "project_root": str(PROJECT_ROOT),
                "python": _py(),
                "lock": str(LOCK_PATH),
                "mode": "once" if args.once else "loop",
            }
        ),
        flush=True,
    )

    while True:
        t0 = time.time()
        try:
            result = run_cycle(
                no_enqueue=args.no_enqueue,
                no_alert=args.no_alert,
                run_escalation=not args.no_escalation,
            )
        except Exception as e:
            result = {"ok": False, "status": "unhealthy", "overall_score": 0, "error": str(e)[:200]}

        status = result.get("status") or "unknown"
        score = result.get("overall_score")
        if result.get("skipped"):
            sleep_s = 30  # lock held by cron — retry soon
        else:
            sleep_s = _cadence_seconds(str(status), float(score) if score is not None else None)
            sleep_s = int(sleep_s * (0.9 + 0.2 * random.random()))  # ±10% jitter

        sleep_s = max(args.min_sleep, sleep_s)
        st = {
            "last_cycle": datetime.now(timezone.utc).isoformat(),
            "last_status": status,
            "last_score": score,
            "next_sleep_s": sleep_s,
            "last_result": {
                k: result.get(k)
                for k in (
                    "ok", "status", "overall_score", "enqueued", "remediated_ok",
                    "skipped", "error", "elapsed_s", "escalation",
                )
            },
        }
        _save_state(st)
        print(
            json.dumps(
                {
                    "cycle_done": True,
                    "status": status,
                    "score": score,
                    "sleep_s": sleep_s,
                    "elapsed_s": round(time.time() - t0, 1),
                    "enqueued": result.get("enqueued"),
                    "remediated_ok": result.get("remediated_ok"),
                    "skipped": result.get("skipped"),
                    "escalation": (result.get("escalation") or {}).get("skipped")
                    or (result.get("escalation") or {}).get("ok"),
                }
            ),
            flush=True,
        )

        if args.once:
            return 0 if result.get("ok") or result.get("skipped") else 1
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())
