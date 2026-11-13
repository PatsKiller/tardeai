#!/usr/bin/env python3
"""run_cio_wake_bounded.py: run the CIO persistent wake inside a memory-capped systemd scope (LQ-20261107-2965).

Why. On 2026-11-13 the hourly crontab wake (``run_persistent_wake.py --agent-id cio``) grew to 13 GB RSS, filled
swap and starved the host (LQ-20261107-2954). The cron line had no lock, no timeout and no memory cap, so nothing
stopped one wake from taking the whole box. This runner is the only sanctioned way to start a cio wake once the
cron line is retired:

* single flight: ``flock -n`` on its own lock (``--lock``), and a /proc scan refuses while any
  ``run_persistent_wake.py --agent-id <agent>`` is already running, whoever started it;
* admission fence: refuses while a non-comment crontab line still runs the same wake (two owners = double wakes);
* bound: ``systemd-run --user --scope`` with MemoryMax / MemorySwapMax=0 / OOMPolicy=kill / CPUWeight / IOWeight
  covers the whole process tree; inside it ``nice``/``ionice`` and ``timeout --kill-after``;
* proof: a receipt (``CioWakeBoundedRun@v1``) with exit code, outcome, peak memory read from the scope's
  cgroup ``memory.peak`` while the scope is alive, and the ``oom_kill`` count from ``memory.events``.
  ``ok_at`` advances only when the wake exits 0.

It never runs unbounded: if ``systemd-run --user`` is unavailable the run is refused, not degraded.

Modes. Default is a DRY RUN: evaluate admission, print the exact argv, write nothing and spawn nothing (exit 0
even when it would refuse; ``would_refuse`` says why). ``--apply`` runs the wake. A refused ``--apply`` exits 3
and writes a receipt that keeps the previous ``ok_at``.

Exit codes (--apply): the wake's own code when it ran; 3 refused by admission; 4 the scope could not start.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

_PROJECT = Path(__file__).resolve().parents[1]

SCHEMA = "CioWakeBoundedRun@v1"
LANE_ID = "cio-persistent-wake"
DEFAULT_LOCK = "/tmp/cio_wake_bounded.lock"
DEFAULT_TIMEOUT_S = 1800
DEFAULT_KILL_AFTER_S = 30
DEFAULT_MEMORY_MAX = "2G"
POLL_S = 1.0
EXIT_REFUSED = 3
EXIT_SCOPE_FAILED = 4
CGROUP_ROOT = Path("/sys/fs/cgroup")

#: The non-secret env the retired cron line set inline (crontab, LQ-2954 PAUSED line). setdefault only: an
#: explicit value in the caller's env wins. Secrets are never set here; they come from the executor's env.
WAKE_ENV_DEFAULTS = {
    "WAKE_L3_JUDGMENT": "1",
    "WAKE_L3_ALLOW_LIVE_PROVIDER": "1",
    "PERSISTENT_WAKE_ENABLED": "1",
    "PERSISTENT_WAKE_SCHEDULE_ENABLED": "1",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def wake_pattern(agent_id: str) -> re.Pattern[str]:
    return re.compile(r"run_persistent_wake\.py\b.*--agent-id[ =]" + re.escape(agent_id) + r"(?![\w-])")


# ── admission ────────────────────────────────────────────────────────────────────────────────────────────


def read_crontab() -> tuple[str | None, str | None]:
    """(text, error). No crontab at all is an empty text, not an error; anything else unexpected is an error."""
    try:
        proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"crontab_unreadable:{type(exc).__name__}"
    if proc.returncode == 0:
        return proc.stdout, None
    if "no crontab" in (proc.stderr or "").lower():
        return "", None
    return None, f"crontab_unreadable:rc={proc.returncode}"


def active_cron_lines(text: str, agent_id: str) -> list[int]:
    """1-based numbers of crontab lines that would RUN the wake: not a comment and matching the wake command.

    A line is active when its first non-blank character is not ``#``. ``# PAUSED ... run_persistent_wake.py
    --agent-id cio`` is therefore inactive, which is exactly how the operator retires it.
    """
    pat = wake_pattern(agent_id)
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if pat.search(s):
            out.append(n)
    return out


def running_wakes(agent_id: str, proc_root: Path = Path("/proc"), self_pid: int | None = None) -> list[int]:
    """PIDs whose cmdline runs the wake for ``agent_id``. Unreadable /proc entries are skipped (they exited)."""
    pat = wake_pattern(agent_id)
    me = self_pid if self_pid is not None else os.getpid()
    pids = []
    for entry in proc_root.iterdir() if proc_root.is_dir() else []:
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [a for a in raw.decode("utf-8", "replace").split("\0") if a]
        # Only the python process itself, not a shell or flock/timeout/systemd-run wrapper that carries the text.
        if not argv or "python" not in os.path.basename(argv[0]):
            continue
        if pat.search(" ".join(argv)):
            pids.append(int(entry.name))
    return sorted(pids)


def admission(
    agent_id: str,
    *,
    crontab: Callable[[], tuple[str | None, str | None]] = read_crontab,
    running: Callable[[str], list[int]] = running_wakes,
    systemd_run: Callable[[], str | None] = lambda: shutil.which("systemd-run"),
) -> dict[str, Any]:
    """Every reason this run must not start. Empty ``refusals`` means admitted. Fails closed on unknowns."""
    refusals: list[str] = []
    text, err = crontab()
    lines: list[int] = []
    if err:
        refusals.append(err)
    else:
        lines = active_cron_lines(text or "", agent_id)
        if lines:
            refusals.append("cron_line_active")
    pids = running(agent_id)
    if pids:
        refusals.append("wake_in_flight")
    if not systemd_run():
        refusals.append("systemd_run_unavailable")
    return {"refusals": refusals, "active_cron_lines": lines, "in_flight_pids": pids}


# ── the bounded command ──────────────────────────────────────────────────────────────────────────────────


def unit_name(agent_id: str, when: datetime) -> str:
    return f"cio-wake-{re.sub(r'[^A-Za-z0-9]', '', agent_id)}-{when.strftime('%Y%m%dT%H%M%SZ')}"


def build_argv(
    *, agent_id: str, unit: str, python: str, wake_script: str, timeout_s: int, kill_after_s: int,
    memory_max: str, extra: Iterable[str] = (),
) -> list[str]:
    """systemd-run scope (bounds the whole tree) > nice > ionice > timeout --kill-after > python wake."""
    return [
        "systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}",
        f"--property=MemoryMax={memory_max}",
        "--property=MemorySwapMax=0",
        "--property=OOMPolicy=kill",
        "--property=CPUWeight=20",
        "--property=IOWeight=20",
        "--",
        "nice", "-n", "10",
        "ionice", "-c", "3",
        "timeout", f"--kill-after={kill_after_s}s", f"{timeout_s}s",
        python, wake_script, "--agent-id", agent_id, *extra,
    ]


def wake_env(base: dict[str, str], code_root: Path) -> dict[str, str]:
    env = dict(base)
    for k, v in WAKE_ENV_DEFAULTS.items():
        env.setdefault(k, v)
    feed = code_root / "data" / "persistent_wake" / "selection_feed"
    env.setdefault("TRADEAI_WAKE_MATERIAL_CHANGES_PATH", str(feed / "material_changes.jsonl"))
    env.setdefault("TRADEAI_WAKE_RECEIPTS_PATH", str(feed / "receipts.jsonl"))
    env.setdefault(
        "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH",
        str(Path.home() / "trade-ai-state" / "persistent_wake" / "research_objects.jsonl"),
    )
    return env


# ── cgroup accounting ────────────────────────────────────────────────────────────────────────────────────


def cgroup_dir(pid: int, proc_root: Path = Path("/proc"), cg_root: Path = CGROUP_ROOT) -> Path | None:
    try:
        text = (proc_root / str(pid) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("0::"):
            return cg_root / line[3:].lstrip("/")
    return None


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_oom_kills(cg: Path) -> int | None:
    try:
        for line in (cg / "memory.events").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(" ")
            if k == "oom_kill":
                return int(v)
    except (OSError, ValueError):
        return None
    return None


class ScopeSampler:
    """Remembers the highest memory.peak / swap peak and oom_kill count seen while the scope is alive.

    A ``--scope`` unit disappears with its last process, so the numbers must be read before the exit.
    ``memory.peak`` is monotonic within the cgroup, so the last successful read is the peak up to that moment;
    growth inside the final poll interval can be missed, which is why the receipt also names ``samples``.
    """

    def __init__(self, unit: str | None = None) -> None:
        self.unit = unit
        self.cgroup: Path | None = None
        self.peak: int | None = None
        self.swap_peak: int | None = None
        self.oom_kills: int | None = None
        self.samples = 0

    def sample(self, pid: int, *, proc_root: Path = Path("/proc"), cg_root: Path = CGROUP_ROOT) -> None:
        if self.cgroup is None:
            cg = cgroup_dir(pid, proc_root, cg_root)
            # Until systemd-run has moved itself into the transient scope, /proc/<pid>/cgroup names the CALLER's
            # cgroup (observed: a tmux scope with a 17 GB peak). Accept only the exact unit this run created.
            if cg is None or cg.name != f"{self.unit}.scope":
                return
            self.cgroup = cg
        peak = read_int(self.cgroup / "memory.peak")
        if peak is None:
            return
        self.samples += 1
        self.peak = max(self.peak or 0, peak)
        sp = read_int(self.cgroup / "memory.swap.peak")
        if sp is not None:
            self.swap_peak = max(self.swap_peak or 0, sp)
        ok = read_oom_kills(self.cgroup)
        if ok is not None:
            self.oom_kills = max(self.oom_kills or 0, ok)


def unit_result(unit: str) -> dict[str, str]:
    """Read-only ``systemctl --user show`` of the finished scope.

    A scope that ended cleanly is already unloaded (empty / LoadState=not-found). A scope the kernel OOM-killed stays
    loaded in ``failed`` with ``Result=oom-kill`` and an exact ``MemoryPeak`` (observed 2026-11-13 on systemd 259),
    which is the authoritative answer the in-flight sampler can miss when the kill lands between two polls. Nothing
    here resets or stops the unit; a failed scope is left for the operator to see.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "LoadState", "-p", "Result", "-p", "MemoryPeak"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in proc.stdout.splitlines():
        k, _, v = line.partition("=")
        if k:
            out[k] = v
    return out


def classify(rc: int | None, oom_kills: int | None, result: str | None = None) -> str:
    if rc is None:
        return "scope_failed"
    if oom_kills or result == "oom-kill":
        return "oom_killed"
    if rc == 0:
        return "ok"
    if rc in (124, 137):
        return "timeout"  # timeout(1): 124 after TERM, 137 after --kill-after KILL
    if rc < 0:
        return "killed"  # signalled from outside the scope
    return "failed"


# ── receipt ──────────────────────────────────────────────────────────────────────────────────────────────


def _runtime(state_root: str | None) -> Path:
    root = state_root or os.environ.get("TRADEAI_STATE_ROOT")
    if not root:
        if str(_PROJECT) not in sys.path:
            sys.path.insert(0, str(_PROJECT))
        from scripts.lib.lane_last_receipt import runtime_dir  # noqa: PLC0415

        return runtime_dir()
    return Path(root) / "data" / "runtime"


def receipt_path(state_root: str | None) -> Path:
    """The detailed CioWakeBoundedRun@v1 receipt (peak memory, cgroup, admission)."""
    return _runtime(state_root) / f"{LANE_ID}_bounded_last.json"


def lane_receipt_path(state_root: str | None) -> Path:
    """The lane's LaneRunReceipt@v2 (``<lane>_last.json``): the registry output_signal and the executor's verdict."""
    return _runtime(state_root) / f"{LANE_ID}_last.json"


def write_lane_run_receipt(path: Path, doc: dict[str, Any]) -> None:
    """LaneRunReceipt@v2 for a REAL run. produced_count = 1 bounded wake that exited 0; a refusal is a typed
    empty_reason. Never raises (write_lane_receipt's own contract); the detailed receipt is already on disk."""
    if str(_PROJECT) not in sys.path:
        sys.path.insert(0, str(_PROJECT))
    from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415

    ok = doc.get("outcome") == "ok"
    refused = doc.get("outcome") == "refused"
    write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=doc.get("exit_code"),
        started_at=doc.get("started_at"),
        script="scripts/run_cio_wake_bounded.py",
        summary={k: doc.get(k) for k in ("outcome", "unit", "peak_memory_bytes", "oom_kill_events",
                                          "unit_result", "duration_s", "memory_max")},
        error=None if ok else str(doc.get("outcome")),
        path=path,
        produced_count=1 if ok else 0,
        attempted_count=0 if refused else 1,
        skipped_reasons={r: 1 for r in (doc.get("admission") or {}).get("refusals", [])} if refused else None,
        empty_reason="admission_refused" if refused else None,
        # build_receipt makes every not-ok run "error" (ok_at never advances); a refused LIVE fire is a failure the
        # breaker should count, not an empty success. The finer outcome rides in outcome_reason.
        outcome="ok" if ok else "error",
        outcome_reason=str(doc.get("outcome")),
    )


def write_receipt(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    prior_ok = None
    try:
        prior_ok = json.loads(path.read_text(encoding="utf-8")).get("ok_at")
    except (OSError, ValueError, AttributeError):
        prior_ok = None
    doc = {**doc, "ok_at": doc["ended_at"] if doc.get("outcome") == "ok" else prior_ok}
    out = doc
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return out


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────────


def run(
    args: argparse.Namespace,
    *,
    admit: Callable[[str], dict[str, Any]] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    sampler: ScopeSampler | None = None,
    show: Callable[[str], dict[str, str]] = unit_result,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _now,
) -> int:
    started = now()
    unit = unit_name(args.agent_id, started)
    python = os.environ.get("TRADEAI_VENV_PYTHON") or sys.executable
    argv = build_argv(
        agent_id=args.agent_id, unit=unit, python=python,
        wake_script=args.wake_script or str(_PROJECT / "scripts" / "run_persistent_wake.py"),
        timeout_s=args.timeout_s, kill_after_s=args.kill_after_s, memory_max=args.memory_max,
        extra=["--dry-run"] if args.wake_dry_run else [],
    )
    base = {
        "schema": SCHEMA, "lane_id": LANE_ID, "agent_id": args.agent_id, "unit": unit,
        "memory_max": args.memory_max, "timeout_s": args.timeout_s, "argv": argv,
        "started_at": _iso(started), "mode": "apply" if args.apply else "dry_run",
    }

    lock_fd = os.open(args.lock, os.O_RDWR | os.O_CREAT, 0o664)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            locked = False
        adm = (admit or admission)(args.agent_id)
        if not locked:
            adm["refusals"] = ["lock_held", *adm["refusals"]]
        base["admission"] = adm

        if not args.apply:
            print(json.dumps({**base, "outcome": "dry_run", "would_refuse": adm["refusals"],
                              "detail": "nothing spawned, nothing written"}, sort_keys=True))
            return 0

        rpath = receipt_path(args.state_root)
        if adm["refusals"]:
            doc = {**base, "outcome": "refused", "exit_code": EXIT_REFUSED, "ended_at": _iso(now()),
                   "peak_memory_bytes": None, "oom_kill_events": None}
            doc = write_receipt(rpath, doc)
            write_lane_run_receipt(lane_receipt_path(args.state_root), doc)
            print(json.dumps(doc, sort_keys=True))
            return EXIT_REFUSED

        smp = sampler or ScopeSampler(unit)
        rc: int | None
        try:
            # close_fds (default) keeps the single-flight lock out of the child: a killed runner must not leave
            # an orphaned wake holding it.
            proc = popen(argv, env=wake_env(dict(os.environ), _PROJECT), cwd=str(_PROJECT))
        except OSError as exc:
            rc = None
            base["detail"] = f"spawn_failed:{type(exc).__name__}"
        else:
            while proc.poll() is None:
                smp.sample(proc.pid)
                sleep(POLL_S)
            rc = proc.returncode
        ended = now()
        unit_state: dict[str, str] = {}
        if rc is not None and rc != 0:
            # A clean exit unloads the scope; only a failed one lingers. systemd may not have recorded the
            # Result yet when our child is reaped, so give it a few short reads.
            for _ in range(5):
                unit_state = show(f"{unit}.scope")
                if unit_state.get("LoadState") != "loaded" or unit_state.get("Result") not in (None, "", "success"):
                    break
                sleep(0.2)
        result = unit_state.get("Result") if unit_state.get("LoadState") == "loaded" else None
        peak = smp.peak
        if result is not None and (unit_state.get("MemoryPeak") or "").isdigit():
            peak = max(peak or 0, int(unit_state["MemoryPeak"]))
        outcome = classify(rc, smp.oom_kills, result)
        doc = {
            **base,
            "outcome": outcome,
            "exit_code": EXIT_SCOPE_FAILED if rc is None else rc,
            "ended_at": _iso(ended),
            "duration_s": round((ended - started).total_seconds(), 3),
            "cgroup": str(smp.cgroup) if smp.cgroup else None,
            "peak_memory_bytes": peak,
            "unit_result": result,
            "peak_swap_bytes": smp.swap_peak,
            "oom_kill_events": smp.oom_kills,
            "samples": smp.samples,
        }
        doc = write_receipt(rpath, doc)
        write_lane_run_receipt(lane_receipt_path(args.state_root), doc)
        print(json.dumps(doc, sort_keys=True))
        return doc["exit_code"]
    finally:
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--agent-id", default="cio")
    p.add_argument("--apply", action="store_true", help="run the wake (default: dry run, nothing spawned)")
    p.add_argument("--wake-dry-run", action="store_true",
                   help="pass --dry-run to run_persistent_wake.py inside the bounded scope (canary of the bound)")
    p.add_argument("--wake-script", default=None, help=argparse.SUPPRESS)  # tests / bound smoke only
    p.add_argument("--lock", default=DEFAULT_LOCK)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--kill-after-s", type=int, default=DEFAULT_KILL_AFTER_S)
    p.add_argument("--memory-max", default=DEFAULT_MEMORY_MAX)
    p.add_argument("--state-root", default=None, help="receipt root (default TRADEAI_STATE_ROOT)")
    args = p.parse_args(argv)
    if not re.fullmatch(r"\d+[KMG]?", args.memory_max):
        p.error("--memory-max must look like 2G / 512M / bytes")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
