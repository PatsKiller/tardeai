#!/usr/bin/env python3
"""portfolio-server fast memory sampler (LQ-20261113-3020). A bounded daemon, not an n8n lane. MBI_BEHAVIOR = 0.

Moved into the repo from the lead's interim ``lead/scratch/mem_sampler_fast.py`` (the record keys it wrote are kept,
so a report reads both). Why: RCA-SERVER-KILL-20261113 needs a before-picture of a freeze; one sample a minute can
miss a spike that lasts seconds.

Every INTERVAL s (1..5, default 2) it appends ONE JSON line to OUT:
  proc        the server's main process: RSS, VmHWM, VmSwap, threads, ``swr-build`` threads, cwd
  split       process-vs-unit: main RSS, summed RSS of every pid in the cgroup, the other pids' RSS, and
              ``cg_unexplained_b`` = cgroup memory.current minus the pids' summed RSS (page cache, kernel, shmem)
  cg_*        memory.current / peak / swap.current, memory.stat anon/file/shmem, memory.events and its DELTA,
              memory.pressure
  host        MemAvailable, SwapFree
  tcp7777     sockets on the server port by state (read from /proc/net/tcp, no probe)
  app_log     when SAMPLER_APP_LOG names a file: how many "[watchdog] reaped abandoned compute" lines appeared since
              the last sample and the last one's path; null when no log is configured or readable
  markers     ``start``, ``unit_read_failed`` (pid is then null), ``pid_changed`` (only between two KNOWN pids), ``release_changed``, ``cgroup_recreated`` (an events counter went DOWN)
  swap_top    every 60 s: the top 10 swap holders, pid + comm only (never cmdline or environ)

Unknown beats wrong: a file that cannot be read is null, never 0. A counter that went down gives a null delta and the
``cgroup_recreated`` marker, never a negative number.

Reads /proc and /sys only (plus ``systemctl --user show`` for MainPID/ControlGroup, every 10 s). Writes only OUT, its
numbered segments and ``<OUT>_archive/``. It never deletes (AGENTS.md rule 6): when OUT passes ROTATE_MB it is renamed
to ``OUT.1``..``OUT.KEEP``; the segment beyond KEEP is RENAMED into the archive directory. The total (live + archive)
is capped at TOTAL_CAP_MB: at the cap the sampler writes one ``stopped_at_cap`` line and exits 40 (not 3: that is EXIT_FINDING) instead of growing.
A bad SAMPLER_* value (not finite, <= 0) exits 2 before sampling. A write error writes ``stopped_on_error`` and exits 41.
It also exits after MAX_HOURS. No network, no DB, no signals, no writes anywhere else.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "ServerMemorySample@v2"
UNIT = "portfolio-server.service"
PORT_HEX = "%04X" % 7777
REAPED_RE = re.compile(r"\[watchdog\] reaped abandoned compute: (\S+) after (\d+)s")
OUT_NAME = "server_memory_samples_fast.jsonl"
PROC = Path("/proc")
SYS = Path("/sys/fs/cgroup")
MIN_INTERVAL, MAX_INTERVAL = 1.0, 5.0
MAX_TOTAL_CAP_MB = 1024.0
#: Exit codes. NOT 3: scripts/lib/monitor_exit_codes.EXIT_FINDING is 3, so a runner using the usual finding_rc would
#: read "stopped recording at the cap" as green. 1 is a Python crash, 2 a bad configuration.
EXIT_OK, EXIT_BAD_CONFIG, EXIT_STOPPED_AT_CAP, EXIT_WRITE_ERROR = 0, 2, 40, 41


class ConfigError(ValueError):
    pass


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _positive(name: str, default: float) -> float:
    """A finite value > 0, else ConfigError. NaN/inf/0/negative would disable the cap, end the run at once with exit 0
    and no output, or crash the first rotation (review 3020r S1)."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return float(default)
    try:
        v = float(raw)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a number") from None
    if not math.isfinite(v) or v <= 0:
        raise ConfigError(f"{name}={raw!r} must be finite and > 0")
    return v


def _state_root() -> Path:
    """TRADEAI_STATE_ROOT, else the durable-state resolver (the root the lane receipts use)."""
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.lib.persistent_state_root import resolve_durable_dir
    return Path(resolve_durable_dir("data/ops")).parent.parent


class Config:
    def __init__(self) -> None:
        self.interval = min(MAX_INTERVAL, max(MIN_INTERVAL, _f("SAMPLER_INTERVAL_S", 2)))
        self.max_hours = _positive("SAMPLER_MAX_HOURS", 8)
        self.rotate_mb = _positive("SAMPLER_ROTATE_MB", 40)
        self.keep = max(1, int(_positive("SAMPLER_KEEP", 4)))
        self.total_cap_mb = min(MAX_TOTAL_CAP_MB, _positive("SAMPLER_TOTAL_CAP_MB", MAX_TOTAL_CAP_MB))
        root = _state_root()
        self.out = Path(os.environ["SAMPLER_OUT"]) if os.environ.get("SAMPLER_OUT") else root / "data" / "ops" / OUT_NAME
        self.current = os.environ.get("SAMPLER_CURRENT") or str(root.parent / "portfolio-server" / "CURRENT")
        self.app_log = os.environ.get("SAMPLER_APP_LOG") or None


def rd(path: Path) -> Optional[str]:
    try:
        return Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return None


def kv(text: Optional[str], keys: set) -> Optional[dict[str, int]]:
    """Selected ``key value`` / ``Key: value kB`` lines as ints (kB left as kB); None if the file is unreadable."""
    if text is None:
        return None
    out: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.replace(":", " ").split()
        if len(parts) >= 2 and parts[0] in keys:
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return out


def scalar(text: Optional[str]) -> Optional[int]:
    try:
        return int((text or "").strip())
    except ValueError:
        return None   # also "max" and unreadable: unknown, never 0


def unit_info() -> Optional[tuple[int, str]]:
    """(MainPID, ControlGroup); MainPID 0 is a real answer (the unit is stopped). None = the read FAILED (timeout, no
    systemctl, non-zero exit, no MainPID key): an unknown, which must never be recorded as a restart (review 3020r B1)."""
    try:
        r = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID,ControlGroup", UNIT],
                           capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return None
        d = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        if "MainPID" not in d:
            return None
        return int(d["MainPID"] or 0), d.get("ControlGroup") or ""
    except Exception:  # noqa: BLE001 -- an unreadable unit is an unknown, the sampler keeps running
        return None


def proc_stats(pid: int, proc: Path) -> dict[str, Any]:
    if not pid:
        return {}
    st = kv(rd(proc / str(pid) / "status"), {"VmRSS", "VmHWM", "VmSwap", "Threads"})
    swr: Optional[int] = None
    try:
        swr = sum(1 for t in os.listdir(proc / str(pid) / "task")
                  if (rd(proc / str(pid) / "task" / t / "comm") or "").startswith("swr-build"))
    except OSError:
        pass
    try:
        cwd: Optional[str] = os.readlink(proc / str(pid) / "cwd")
    except OSError:
        cwd = None
    st = st or {}
    return {"rss_kb": st.get("VmRSS"), "hwm_kb": st.get("VmHWM"), "swap_kb": st.get("VmSwap"),
            "threads": st.get("Threads"), "swr_build_threads": swr, "cwd": cwd}


def unit_split(main_pid: int, cg_dir: Optional[Path], cg_current: Optional[int], proc: Path) -> dict[str, Any]:
    """Process vs unit. Pids that exit between the two reads are skipped, so the sum is a floor."""
    pids_text = rd(cg_dir / "cgroup.procs") if cg_dir else None
    if pids_text is None:
        return {"unit_pids": None, "main_rss_kb": None, "unit_rss_kb": None, "other_rss_kb": None,
                "cg_unexplained_b": None}
    pids = [int(x) for x in pids_text.split() if x.isdigit()]
    rss: dict[int, int] = {}
    for p in pids:
        v = (kv(rd(proc / str(p) / "status"), {"VmRSS"}) or {}).get("VmRSS")
        if v is not None:
            rss[p] = v
    unit_kb = sum(rss.values())
    main_kb = rss.get(main_pid)
    return {"unit_pids": len(pids), "main_rss_kb": main_kb, "unit_rss_kb": unit_kb,
            "other_rss_kb": None if main_kb is None else unit_kb - main_kb,
            "cg_unexplained_b": None if cg_current is None else cg_current - unit_kb * 1024}


def tcp_states(proc: Path) -> Optional[dict[str, int]]:
    """Sockets on the server port by state; None when neither /proc/net file is readable (unknown, never 0)."""
    c = {"est": 0, "close_wait": 0, "other": 0}
    texts = [rd(proc / f) for f in ("net/tcp", "net/tcp6")]
    if all(t is None for t in texts):
        return None
    for text in texts:
        for line in (text or "").splitlines()[1:]:
            p = line.split()
            if len(p) < 4 or not p[1].endswith(":" + PORT_HEX):
                continue
            if p[3] == "01":
                c["est"] += 1
            elif p[3] == "08":
                c["close_wait"] += 1
            elif p[3] != "0A":
                c["other"] += 1
    return c


def swap_top(proc: Path, n: int = 10) -> Optional[list[dict[str, Any]]]:
    rows = []
    try:
        names = [d for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return None
    for d in names:
        s = rd(proc / d / "status")
        if not s:
            continue
        v = (kv(s, {"VmSwap"}) or {}).get("VmSwap") or 0
        if v:
            name = next((ln.split(None, 1)[1].strip() for ln in s.splitlines() if ln.startswith("Name:") and len(ln.split(None, 1)) > 1), "?")
            rows.append((v, int(d), name[:32]))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [{"pid": p, "comm": nm, "swap_kb": v} for v, p, nm in rows[:n]]


class AppLogTail:
    """Reaped-compute lines appended to the server log since the last call. Reads only the new bytes, and only COMPLETE
    lines: the offset advances to the last newline, so a line the server wrote in two chunks (its print is unflushed)
    is counted once, on the poll that sees its end (review 3020r B2). A log replaced by rename-and-recreate (new inode)
    or truncated is read from the start."""

    MAX_READ = 1 << 20

    def __init__(self, path: Optional[str]) -> None:
        self.path, self.pos, self.ino = path, None, None

    def poll(self) -> Optional[dict[str, Any]]:
        if not self.path:
            return None
        try:
            stt = os.stat(self.path)
            with open(self.path, "rb") as fh:
                if self.pos is None:                           # first look: start at the end, not the history
                    self.pos, self.ino = stt.st_size, stt.st_ino
                elif stt.st_ino != self.ino or stt.st_size < self.pos:   # replaced, or truncated
                    self.pos, self.ino = 0, stt.st_ino
                fh.seek(self.pos)
                raw = fh.read(self.MAX_READ)
        except OSError:
            return None
        cut = raw.rfind(b"\n") + 1
        if cut == 0 and len(raw) >= self.MAX_READ:             # one line longer than a read: do not stall on it
            cut = len(raw)
        self.pos += cut
        hits = REAPED_RE.findall(raw[:cut].decode("utf-8", "replace"))
        return {"reaped": len(hits), "last_path": hits[-1][0] if hits else None,
                "last_age_s": int(hits[-1][1]) if hits else None}


def events_delta(ev: Optional[dict[str, int]], prev: Optional[dict[str, int]]) -> tuple[Optional[dict[str, int]], bool]:
    if ev is None or prev is None:
        return None, False
    delta = {}
    for k, v in ev.items():
        b = prev.get(k)
        if b is None:
            continue
        if v < b:
            return None, True
        delta[k] = v - b
    return delta, False


class State:
    def __init__(self) -> None:
        self.prev_events: Optional[dict[str, int]] = None
        self.prev_pid: Optional[int] = None
        self.prev_release: Optional[str] = None
        self.last_top = 0.0
        self.first = True


def sample(now: float, st: State, pid: int, cg: str, log: AppLogTail, proc: Path = PROC, sysroot: Path = SYS,
           release: Optional[str] = None, current: str = "", unit_failed: bool = False) -> dict[str, Any]:
    """``pid``/``cg`` are the LAST KNOWN unit values. When the unit read failed (``unit_failed``) they keep the other
    reads going, the record's ``pid`` is null, ``unit_read_failed`` is marked, and no ``pid_changed`` can fire: it
    needs two KNOWN pids (review 3020r B1)."""
    base = (sysroot / cg.lstrip("/")) if cg else None
    ev = kv(rd(base / "memory.events"), {"high", "max", "oom", "oom_kill"}) if base else None
    delta, recreated = events_delta(ev, st.prev_events)
    cur = scalar(rd(base / "memory.current")) if base else None
    if release is None:
        try:
            release = os.path.realpath(current).rsplit("/", 1)[-1]
        except OSError:
            release = None
    markers = []
    if st.first:
        markers.append("start")
    if unit_failed:
        markers.append("unit_read_failed")
    elif st.prev_pid is not None and pid != st.prev_pid:
        markers.append("pid_changed")
    if st.prev_release is not None and release != st.prev_release:
        markers.append("release_changed")
    if recreated:
        markers.append("cgroup_recreated")
    pressure = rd(base / "memory.pressure") if base else None
    rec: dict[str, Any] = {
        "schema": SCHEMA, "ts": round(now, 3), "pid": None if unit_failed else pid, "release": release,
        "pid_changed": "pid_changed" in markers, "markers": markers,
        "proc": proc_stats(pid, proc),
        "split": unit_split(pid, base, cur, proc),
        "cg_current_b": cur,
        "cg_peak_b": scalar(rd(base / "memory.peak")) if base else None,
        "cg_swap_b": scalar(rd(base / "memory.swap.current")) if base else None,
        "cg_stat": kv(rd(base / "memory.stat"), {"anon", "file", "shmem"}) if base else None,
        "cg_events": ev, "cg_events_delta": delta,
        "cg_pressure": pressure.strip().replace("\n", " | ") if pressure else None,
        "host": kv(rd(proc / "meminfo"), {"MemAvailable", "SwapFree"}),
        "tcp7777": tcp_states(proc),
        "app_log": log.poll(),
    }
    if now - st.last_top >= 60:
        rec["swap_top"] = swap_top(proc)
        st.last_top = now
    st.prev_events, st.prev_release, st.first = ev, release, False
    if not unit_failed:
        st.prev_pid = pid
    return rec


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def total_bytes(out: Path) -> int:
    arch = out.parent / (out.name + "_archive")
    t = sum(_size(p) for p in out.parent.glob(out.name + "*") if p.is_file())
    if arch.is_dir():
        t += sum(_size(p) for p in arch.iterdir() if p.is_file())
    return t


def rotate(out: Path, rotate_mb: float, keep: int, stamp: Optional[str] = None) -> Optional[str]:
    """Rename only. OUT -> OUT.1 -> ... -> OUT.keep; the segment past keep goes into the archive directory."""
    keep = max(1, int(keep))                  # KEEP=0 would os.replace OUT onto OUT.1: an overwrite, i.e. a delete (rule 6)
    if not out.exists() or _size(out) < rotate_mb * 1048576:
        return None
    last = out.with_name(f"{out.name}.{keep}")
    if last.exists():
        arch = out.parent / (out.name + "_archive")
        arch.mkdir(exist_ok=True)
        dest = arch / f"{out.name}.{stamp or int(time.time())}"
        n = 0
        while dest.exists():
            n += 1
            dest = arch / f"{out.name}.{stamp or int(time.time())}.{n}"
        os.replace(last, dest)
    for i in range(keep - 1, 0, -1):
        src = out.with_name(f"{out.name}.{i}")
        if src.exists():
            os.replace(src, out.with_name(f"{out.name}.{i + 1}"))
    os.replace(out, out.with_name(f"{out.name}.1"))
    return "rotated"


def run(cfg: Config, proc: Path = PROC, sysroot: Path = SYS,
        unit: Callable[[], Optional[tuple[int, str]]] = unit_info,
        clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
        max_iterations: Optional[int] = None, release: Optional[str] = None) -> int:
    cfg.out.parent.mkdir(parents=True, exist_ok=True)
    end = clock() + cfg.max_hours * 3600
    st, log = State(), AppLogTail(cfg.app_log)
    pid, cg, failed = 0, "", True               # last KNOWN unit values; failed = the latest unit read did not answer
    last_unit = -1e18
    n = 0
    while clock() < end and (max_iterations is None or n < max_iterations):
        t0 = clock()
        if t0 - last_unit > 10 or failed:
            got = unit()
            last_unit = t0
            failed = got is None
            if got is not None:
                pid, cg = got
        rec = sample(t0, st, pid, cg, log, proc, sysroot, release, cfg.current, unit_failed=failed)
        try:
            rotate(cfg.out, cfg.rotate_mb, cfg.keep)
            if total_bytes(cfg.out) >= cfg.total_cap_mb * 1048576:
                with cfg.out.open("a") as fh:
                    fh.write(json.dumps({"schema": SCHEMA, "ts": round(t0, 3), "markers": ["stopped_at_cap"]}) + "\n")
                return EXIT_STOPPED_AT_CAP
            with cfg.out.open("a") as fh:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except OSError as exc:                   # ENOSPC, EROFS, a vanished directory: say so, once, and stop
            print(f"server_memory_sampler: stopped_on_error {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                with cfg.out.open("a") as fh:
                    fh.write(json.dumps({"schema": SCHEMA, "ts": round(t0, 3), "markers": ["stopped_on_error"],
                                         "error": type(exc).__name__}) + "\n")
            except OSError:
                pass
            return EXIT_WRITE_ERROR
        n += 1
        sleep(max(0.2, cfg.interval - (clock() - t0)))
    return EXIT_OK


def main() -> int:
    try:
        cfg = Config()
    except ConfigError as exc:
        print(f"server_memory_sampler: bad configuration: {exc}", file=sys.stderr)
        return EXIT_BAD_CONFIG
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
