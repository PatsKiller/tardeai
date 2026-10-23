#!/usr/bin/env python3
"""process_reaper.py — defense-in-depth auto-recovery for hung / piled-up BATCH jobs.

Background: several auto-remediations historically re-spawned heavy jobs without a single-flight
guard and orphaned the child on timeout (the 2026-06-25 trade_ai_orchestrator pile-up that starved
the single-threaded API server; the watchlist-jobs and escalation-retry herds before it). The root
cause is fixed at each spawner (flock + killpg). This reaper is the SAFETY NET: if a pile-up or a
runaway orphan ever slips through (an unknown spawner, a wedged process that ignored SIGTERM), it is
detected and — only when enabled — killed, so no human `pkill` is ever needed.

SAFETY:
  • Acts ONLY on an explicit allowlist of known batch-job patterns. Never touches the API server,
    Ollama, Postgres, continuous_runner, system services, PID 1, or itself.
  • ADVISORY by default: detect + log + alert, NO kill. Set REAP_ENABLED=1 (env) or
    process_reaper_policy.json {"enabled": true} to allow killing.
  • Kill = SIGTERM, grace, then SIGKILL. Always logged to logs/process_reaper.jsonl.

Detection per rule:
  • over-runtime: a matching process older than max_runtime_min (orphaned / wedged).
  • pile-up: more than max_concurrent matching processes — keep the oldest max_concurrent that are
    NOT over-runtime, flag the rest (the newest duplicates).

Cron: every ~3 min.
    .venv/bin/python scripts/process_reaper.py            # advisory unless enabled
    .venv/bin/python scripts/process_reaper.py --dry-run  # force advisory regardless of policy
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOG = PROJECT_ROOT / "logs" / "process_reaper.jsonl"
POLICY_FILE = PROJECT_ROOT / "config" / "process_reaper_policy.json"
SELF_PID = os.getpid()

# Reapable batch jobs ONLY. (pattern matched against full cmdline.) Anything not here is never touched.
# TIME SETTINGS — docs/ops/PIPELINE_TIME_SETTINGS.md. Do not lower a max_runtime_min without
# measured runtime evidence. trade_ai_orchestrator: 30m since 2026-10-22 (20m reaped every
# market-hours run on 10-21/22 at 1216-1377s); must equal config/process_reaper_policy.json and
# stay under continuous_runner.py's 2700s hard limit (tests/test_pipeline_time_settings_20261022.py).
DEFAULT_RULES = [
    {"name": "trade_ai_orchestrator",         "pattern": "trade_ai_orchestrator.py",         "max_concurrent": 1, "max_runtime_min": 30},
    {"name": "process_watchlist_agent_jobs",  "pattern": "process_watchlist_agent_jobs.py",  "max_concurrent": 2, "max_runtime_min": 15},
    {"name": "health_agent",                  "pattern": "scripts/health_agent.py",          "max_concurrent": 1, "max_runtime_min": 8},
    {"name": "system_health_agent",           "pattern": "system_health_agent.py",           "max_concurrent": 1, "max_runtime_min": 10},
    {"name": "hermes_embedding_worker",       "pattern": "hermes_embedding_worker.py",        "max_concurrent": 1, "max_runtime_min": 15},
    {"name": "watchlist_enrichment_sweep",    "pattern": "watchlist_enrichment_sweep.py",     "max_concurrent": 1, "max_runtime_min": 15},
]
# Hard never-kill guard: even if a rule pattern somehow matched these, skip. Belt-and-suspenders.
NEVER_KILL = ("portfolio_server", "api_v2", "ollama", "postgres", "continuous_runner",
              "process_reaper.py", "uvicorn", "gunicorn", "nginx", "systemd")


def _load_policy() -> dict:
    try:
        return json.loads(POLICY_FILE.read_text())
    except Exception:
        return {}


def _ps_snapshot() -> list[dict]:
    """All processes: pid, etimes (age sec), full args. Best-effort via ps."""
    out = []
    try:
        raw = subprocess.run(["ps", "-eo", "pid=,etimes=,args="], capture_output=True, text=True, timeout=15).stdout
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            try:
                pid, etimes, args = int(parts[0]), int(parts[1]), parts[2]
            except ValueError:
                continue
            # Sanity-guard the age: ps can momentarily report a garbage etimes for a just-spawned
            # process (observed 2026-06-25: 68,719,476 min ≈ 2^32 s on a fresh process_watchlist run →
            # false 'over runtime cap' kill of a healthy job). No real batch job runs longer than the
            # 30-day ceiling; an implausible reading is treated as age 0 (never reaped for runtime; a
            # genuinely hung proc gets a correct reading on the next 3-min pass and is reaped then).
            if etimes < 0 or etimes > 2_592_000:
                etimes = 0
            try:
                identity = _proc_identity(pid)
            except (OSError, ValueError):
                # A process may exit between ps and procfs reads. Keep the snapshot row for
                # diagnostics, but it cannot be signalled without a captured identity.
                identity = None
            out.append({"pid": pid, "etimes": etimes, "args": args, "identity": identity})
    except Exception:
        pass
    return out


def _matches(procs: list[dict], pattern: str) -> list[dict]:
    res = []
    for p in procs:
        a = p["args"]
        if pattern not in a:
            continue
        if p["pid"] == SELF_PID:
            continue
        if " grep " in f" {a} " or a.strip().startswith("grep"):
            continue
        if any(nk in a for nk in NEVER_KILL):
            continue
        # Count ONLY the actual python worker, not its wrappers. A single cron run is a process tree —
        # `bash -c … → flock … → timeout … → python … <script>` — and EVERY level carries the script
        # name in argv. Counting all of them read one legit run as a 3-4× "pile-up" and the reaper
        # killed healthy "duplicates" (the 2026-06-25 false positives). The real worker is the python
        # process; its argv[0] basename starts with "python". Wrappers (bash/sh/flock/timeout/
        # safe_flock.sh) have a non-python argv[0] and are skipped.
        argv0 = a.split(None, 1)[0] if a else ""
        if not argv0.rsplit("/", 1)[-1].startswith("python"):
            continue
        res.append(p)
    return res


def _flag(rule: dict, procs: list[dict]) -> tuple[list[dict], list[str]]:
    """Return (procs_to_reap, reasons)."""
    matches = _matches(procs, rule["pattern"])
    if not matches:
        return [], []
    cap_sec = float(rule["max_runtime_min"]) * 60
    max_conc = int(rule["max_concurrent"])
    reasons = []
    over = [p for p in matches if p["etimes"] > cap_sec]
    reap = {p["pid"]: p for p in over}
    if over:
        reasons.append(f"{len(over)} over runtime cap {rule['max_runtime_min']}m "
                       f"({', '.join(str(p['pid']) + '@' + str(round(p['etimes']/60)) + 'm' for p in over)})")
    # pile-up among the not-over-runtime ones: keep the oldest max_concurrent, flag newer extras
    healthy = sorted([p for p in matches if p["pid"] not in reap], key=lambda p: -p["etimes"])  # oldest first
    if len(healthy) > max_conc:
        excess = healthy[max_conc:]  # the newest beyond the cap = pile-on duplicates
        for p in excess:
            reap[p["pid"]] = p
        reasons.append(f"pile-up {len(matches)} > max_concurrent {max_conc} "
                       f"(reaping {len(excess)} newest dup(s))")
    return list(reap.values()), reasons


def _proc_identity(pid: int) -> tuple[int, bytes]:
    """Return Linux process start ticks and raw argv, failing closed if unreadable."""
    stat = Path(f"/proc/{pid}/stat").read_text()
    # comm is parenthesized and may itself contain spaces or ')' characters.
    tail = stat[stat.rfind(")") + 1:].split()
    if len(tail) <= 19:
        raise ValueError("short /proc stat record")
    start_ticks = int(tail[19])  # field 22; tail starts at field 3
    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    if not cmdline:
        raise ValueError("empty cmdline")
    return start_ticks, cmdline


def _same_identity(target: dict) -> bool:
    expected = target.get("identity")
    if expected is None:
        return False
    try:
        return _proc_identity(int(target["pid"])) == expected
    except (OSError, ValueError, TypeError):
        return False


def _open_pidfd(pid: int) -> int | None:
    opener = getattr(os, "pidfd_open", None)
    sender = getattr(signal, "pidfd_send_signal", None)
    if opener is None or sender is None:
        return None
    try:
        return opener(pid, 0)
    except (OSError, NotImplementedError):
        # Older kernels and restricted proc environments use the checked fallback below.
        return None


def _send_signal(target: dict, sig: int, pidfd: int | None) -> None:
    if pidfd is not None:
        signal.pidfd_send_signal(pidfd, sig, None, 0)
    else:
        # Fallback for kernels without pidfd: revalidate immediately before each numeric-PID signal.
        if not _same_identity(target):
            raise ProcessLookupError("process identity changed")
        os.kill(int(target["pid"]), sig)


def _kill(target: dict, enabled: bool) -> str:
    if not enabled:
        return "advisory"
    pid = int(target["pid"])
    if target.get("identity") is None:
        return "identity_unavailable"
    pidfd = _open_pidfd(pid)
    try:
        # pidfd pins the process instance. Also compare starttime + argv to the candidate
        # snapshot so a process that exec'd into something else is never signalled.
        if not _same_identity(target):
            return "identity_changed"
        try:
            _send_signal(target, signal.SIGTERM, pidfd)
        except ProcessLookupError:
            return "already_gone"
        except Exception as e:
            return f"sigterm_err:{e}"
        try:
            time.sleep(3)
            current = _proc_identity(pid)
        except (ProcessLookupError, FileNotFoundError):
            return "terminated"
        except Exception:
            return "identity_unavailable"
        if current != target["identity"]:
            return "identity_changed_after_sigterm"
        try:
            _send_signal(target, signal.SIGKILL, pidfd)
            return "killed_sigkill"
        except ProcessLookupError:
            return "terminated"
        except Exception as e:
            return f"sigkill_err:{e}"
    finally:
        if pidfd is not None:
            try:
                os.close(pidfd)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description="Reaper for hung/piled-up batch jobs")
    ap.add_argument("--dry-run", action="store_true", help="force advisory (never kill) regardless of policy")
    ap.add_argument("--json", action="store_true", help="print findings as json")
    args = ap.parse_args()

    policy = _load_policy()
    rules = policy.get("rules") or DEFAULT_RULES
    enabled = (not args.dry_run) and (
        str(os.getenv("REAP_ENABLED", "")).lower() in ("1", "true", "yes")
        or bool(policy.get("enabled", False))
    )
    procs = _ps_snapshot()
    now = datetime.now(timezone.utc).isoformat()
    findings = []
    for rule in rules:
        to_reap, reasons = _flag(rule, procs)
        if not to_reap:
            continue
        actions = []
        for p in to_reap:
            result = _kill(p, enabled)
            actions.append({"pid": p["pid"], "age_min": round(p["etimes"] / 60, 1), "result": result})
        findings.append({"rule": rule["name"], "reasons": reasons, "enabled": enabled, "actions": actions})

    if findings:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a") as fh:
                fh.write(json.dumps({"at": now, "enabled": enabled, "findings": findings}) + "\n")
        except Exception:
            pass
        # Alert (advisory or action) — free Telegram lane, best-effort.
        try:
            from telegram_alert import send_telegram
            verb = "🔪 Reaped" if enabled else "⚠️ Would reap (advisory)"
            lines = [f"{verb} hung/piled-up batch jobs:"]
            for f in findings:
                acts = ", ".join(f"{a['pid']}@{a['age_min']}m→{a['result']}" for a in f["actions"])
                lines.append(f"• {f['rule']}: {'; '.join(f['reasons'])} [{acts}]")
            if not enabled:
                lines.append("Set REAP_ENABLED=1 to auto-kill.")
            # P3: reaper report is ops FYI -> digest (SND2, AGENTS.md §24.1 intents).
            send_telegram("\n".join(lines), priority="P3", producer="process_reaper")
        except Exception:
            pass

    if args.json:
        print(json.dumps({"at": now, "enabled": enabled, "findings": findings}, indent=2))
    else:
        n_reap = sum(len(f["actions"]) for f in findings)
        print(f"[process_reaper] enabled={enabled} · {len(findings)} rule(s) tripped · "
              f"{n_reap} proc(s) {'reaped' if enabled else 'flagged (advisory)'}")


if __name__ == "__main__":
    main()
