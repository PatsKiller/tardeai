"""PlatformHealth@v1 — is the machinery up? One read-only projection for the Command Center.

GET /api/v2/system/platform-health (scripts/api_v2.py ``_system_platform_health``) serves ``get_platform_health``.
Built 2026-10-21 so the operator can see at a glance whether n8n, the always-on host units, disk / CPU / memory,
the nightly backup and the main Postgres are up.

Every item is ``{id, group, label, status, value, as_of, source, reason, detail}`` with status one of
OK | WARN | CRIT | UNKNOWN. Rules this module keeps:

* Read-only. Probes are ``docker inspect``, one ``SELECT`` through ``docker exec … psql`` (n8n_live_inventory's
  SELECT-only path), ``systemctl --user show`` / ``list-units``, a ``mode=ro`` SQLite open of the coordination
  ledger, ``os.statvfs``-style disk usage, ``/proc/meminfo``, ``os.getloadavg``, a GET of n8n ``/healthz`` and
  three read-only SELECTs on the main DB. No restart, no write, never a shell (argv lists only).
* Fast. Each probe is capped at ``PROBE_TIMEOUT_S`` (2 s, subprocess timeouts too) and the whole collection at
  ``TOTAL_BUDGET_S`` (5 s). The main-DB probe runs on its own single worker thread (db_adapter's connection is
  thread-local and its connect_timeout is 10 s) and is abandoned — reported UNKNOWN — after 2 s.
* Never raises, never zero-fills. A probe that fails, times out or cannot be parsed yields UNKNOWN with
  ``value: None`` and a reason; "could not look" is never reported as OK or as 0 (the convention in
  apps/command-center-v3/src/lib/commsDeliveryHealth.ts).
* Cached ``CACHE_TTL_S`` (30 s) so a page refresh storm runs the probes once.

Thresholds: disk bands come from config/disk_hygiene_rules.json ``monitor.warn_pct`` / ``critical_pct`` (the same
numbers scripts/disk_usage_monitor.py alerts on; 80 / 90 at authoring). Backup: WARN > 26 h, CRIT > 50 h.

AUTHORITY: READ_ONLY_ADVISORY. No broker, no order path, no store writes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "PlatformHealth@v1"
ROOT = Path(__file__).resolve().parents[2]

PROBE_TIMEOUT_S = 2.0
TOTAL_BUDGET_S = 5.0
CACHE_TTL_S = 30.0

STATUSES = ("OK", "WARN", "CRIT", "UNKNOWN")
_RANK = {"OK": 0, "UNKNOWN": 1, "WARN": 2, "CRIT": 3}

N8N_CONTAINERS = ("m8m-n8n", "m8m-n8n-db")
N8N_HEALTHZ_URL = "http://127.0.0.1:5678/healthz"
N8N_ACTIVE_SQL = "select count(*) from workflow_entity where active"

#: The always-on user units, by their real ids (the bare names, e.g. ``cio-telegram``, are not-found on the host).
ALWAYS_ON_UNITS = (
    "portfolio-server.service",
    "tradeai-cio-telegram.service",
    "tradeai-health-agent.service",
    "tradeai-ops-agent.service",
    "tradeai-telegram-callback-poller.service",
    "tradeai-active-trader-motion.service",
    "tradeai-n8n-coordination-gateway.service",
    "tradeai-n8n-run-relay.service",
    "tradeai-n8n-run-executor.service",
    "tradeai-lab-postgres.service",
)
FAILED_UNIT_PATTERN = "tradeai*"
BACKUP_UNIT = "tradeai-portfolio-backup-cadence.service"
#: linux_launchers/run_pg_backup.sh BACKUP_DIR; finished dumps are trade_ai_<ts>.sql.gz (in-flight dumps are .part).
BACKUP_DIR = Path.home() / "db_backups"
BACKUP_GLOB = "trade_ai_*.sql.gz"
BACKUP_WARN_H = 26.0
BACKUP_CRIT_H = 50.0

DISK_CONFIG = ROOT / "config" / "disk_hygiene_rules.json"
DISK_DEFAULT_WARN = 80.0
DISK_DEFAULT_CRIT = 90.0

LOAD_WARN_PER_CPU = 1.5
LOAD_CRIT_PER_CPU = 3.0
MEM_WARN_AVAIL_PCT = 15.0
MEM_CRIT_AVAIL_PCT = 5.0
#: The n8n dispatcher requests runs every few minutes (largest gap 2026-10-17..21: 5 min).
DISPATCH_WARN_MIN = 15.0
DISPATCH_CRIT_MIN = 60.0
PG_CONN_WARN_PCT = 80.0
PG_CONN_CRIT_PCT = 95.0

PG_SQL = (
    "SET LOCAL statement_timeout = '1500ms'; "
    "SELECT pg_database_size(current_database()) AS size_bytes, "
    "(SELECT count(*) FROM pg_stat_activity) AS connections, "
    "current_setting('max_connections')::int AS max_connections"
)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_state_root() -> Path:
    try:
        from scripts.lib import lane_registry  # type: ignore
    except Exception:
        try:
            from lib import lane_registry  # type: ignore
        except Exception:
            lane_registry = None  # type: ignore
    if lane_registry is not None:
        try:
            return Path(lane_registry.state_root())
        except Exception:
            pass
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _systemctl_env() -> dict:
    # systemctl --user needs the user runtime bus; the server may lack it (same injection as api_v2's timers view).
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def _http_get(url: str, timeout: float) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — fixed loopback URL
        return resp.status, resp.read(4096).decode("utf-8", "replace")


def _read_meminfo() -> str:
    return Path("/proc/meminfo").read_text()


@dataclass
class Deps:
    """Everything a probe touches, injectable for hermetic tests."""

    runner: Callable[..., Any] = subprocess.run
    disk_usage: Callable[[str], Any] = shutil.disk_usage
    db_query: Optional[Callable[..., Any]] = None
    http_get: Callable[[str, float], tuple] = _http_get
    loadavg: Callable[[], tuple] = os.getloadavg
    cpu_count: Callable[[], Optional[int]] = os.cpu_count
    meminfo: Callable[[], str] = _read_meminfo
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    state_root: Optional[Path] = None
    ledger_path: Optional[Path] = None
    backup_dir: Path = BACKUP_DIR
    disk_config: Path = DISK_CONFIG
    probe_timeout_s: float = PROBE_TIMEOUT_S
    extra: dict = field(default_factory=dict)


def _item(id_: str, group: str, label: str, source: str, status: str, value: Any, reason: Optional[str],
          as_of: Optional[str], detail: Optional[dict] = None) -> dict:
    return {
        "id": id_,
        "group": group,
        "label": label,
        "status": status if status in STATUSES else "UNKNOWN",
        "value": value,
        "as_of": as_of,
        "source": source,
        "reason": reason,
        "detail": detail or {},
    }


def _unknown(spec: tuple, reason: str, as_of: Optional[str]) -> dict:
    id_, group, label, source = spec
    return _item(id_, group, label, source, "UNKNOWN", None, reason, as_of)


def _run(deps: Deps, argv: list, env: Optional[dict] = None):
    """subprocess with an argv list (never through a shell) and the per-probe timeout."""
    kw = {"capture_output": True, "text": True, "timeout": deps.probe_timeout_s}
    if env is not None:
        kw["env"] = env
    return deps.runner(argv, **kw)


def _fmt_dur(seconds: float) -> str:
    s = max(0, int(seconds))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── n8n ──────────────────────────────────────────────────────────────────────


def _container_spec(name: str) -> tuple:
    return (f"n8n.container.{name}", "n8n", f"container {name}", f"docker inspect {name}")


def probe_n8n_containers(deps: Deps) -> list[dict]:
    now = deps.now()
    as_of = _iso(now)
    argv = ["docker", "inspect", "--format", "{{json .State}}", *N8N_CONTAINERS]
    try:
        proc = _run(deps, argv)
    except subprocess.TimeoutExpired:
        return [_unknown(_container_spec(n), "docker inspect timed out", as_of) for n in N8N_CONTAINERS]
    except OSError as exc:
        return [_unknown(_container_spec(n), f"docker not runnable: {type(exc).__name__}", as_of) for n in N8N_CONTAINERS]
    err = str(getattr(proc, "stderr", "") or "")
    if "permission denied" in err.lower():
        return [_unknown(_container_spec(n), "docker permission denied for this user", as_of) for n in N8N_CONTAINERS]
    lines = [ln for ln in str(getattr(proc, "stdout", "") or "").splitlines() if ln.strip()]
    out = []
    # docker inspect prints one line per FOUND object, in argv order, and exits 1 if any is missing.
    absent = {m.group(1) for m in re.finditer(r"no such object:\s*(\S+)", err, re.I)}
    missing = {n for n in N8N_CONTAINERS if n in absent}
    found = [n for n in N8N_CONTAINERS if n not in missing]
    if len(lines) != len(found):
        reason = f"docker inspect exit {getattr(proc, 'returncode', '?')}: {err.strip()[:160] or 'unexpected output'}"
        return [_unknown(_container_spec(n), reason, as_of) for n in N8N_CONTAINERS]
    by_name = dict(zip(found, lines))
    for name in N8N_CONTAINERS:
        spec = _container_spec(name)
        if name in missing:
            out.append(_item(*spec, "CRIT", "absent", "container does not exist", as_of))
            continue
        try:
            st = json.loads(by_name[name])
        except (ValueError, TypeError):
            out.append(_unknown(spec, "docker inspect output is not JSON", as_of))
            continue
        status = str(st.get("Status") or "")
        health = ((st.get("Health") or {}).get("Status") or None) if isinstance(st.get("Health"), dict) else None
        started = _parse_ts(st.get("StartedAt"))
        uptime_s = (now - started).total_seconds() if started and status == "running" else None
        detail = {"state": status, "health": health, "started_at": _iso(started) if started else None,
                  "uptime_s": int(uptime_s) if uptime_s is not None else None}
        if status == "running":
            sev, reason = "OK", None
            if health == "unhealthy":
                sev, reason = "CRIT", "container healthcheck reports unhealthy"
            elif health == "starting":
                sev, reason = "WARN", "container healthcheck still starting"
            value = "running" + (f", up {_fmt_dur(uptime_s)}" if uptime_s is not None else "") + (f" ({health})" if health else "")
        elif status in ("restarting", "created"):
            sev, value, reason = "WARN", status, f"container is {status}"
        else:
            sev, value, reason = "CRIT", status or "not running", f"container state {status or 'unknown'}"
        out.append(_item(*spec, sev, value, reason, as_of, detail))
    return out


HEALTHZ_SPEC = ("n8n.healthz", "n8n", "n8n /healthz", N8N_HEALTHZ_URL)


def probe_n8n_healthz(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    try:
        code, body = deps.http_get(N8N_HEALTHZ_URL, deps.probe_timeout_s)
    except urllib.error.HTTPError as exc:
        return [_item(*HEALTHZ_SPEC, "CRIT", f"HTTP {exc.code}", "n8n health endpoint returned an error", as_of)]
    except urllib.error.URLError as exc:
        if "timed out" in str(exc.reason).lower():
            return [_unknown(HEALTHZ_SPEC, "health endpoint timed out", as_of)]
        return [_item(*HEALTHZ_SPEC, "CRIT", "unreachable", f"connection failed: {exc.reason}", as_of)]
    except (TimeoutError, OSError) as exc:
        return [_unknown(HEALTHZ_SPEC, f"health read failed: {type(exc).__name__}", as_of)]
    try:
        ok = code == 200 and (json.loads(body) or {}).get("status") == "ok"
    except (ValueError, AttributeError):
        ok = False
    if ok:
        return [_item(*HEALTHZ_SPEC, "OK", "ok", None, as_of)]
    return [_item(*HEALTHZ_SPEC, "CRIT", f"HTTP {code}", f"unexpected health answer: {str(body)[:80]}", as_of)]


ACTIVE_WF_SPEC = ("n8n.active_workflows", "n8n", "active workflows", "docker exec m8m-n8n-db psql (SELECT only)")


def probe_n8n_active_workflows(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    try:
        try:
            from scripts.lib import n8n_live_inventory as inv  # type: ignore
        except Exception:
            from lib import n8n_live_inventory as inv  # type: ignore
        n = inv.run_select(N8N_ACTIVE_SQL, runner=deps.runner, timeout=deps.probe_timeout_s)
    except subprocess.TimeoutExpired:
        return [_unknown(ACTIVE_WF_SPEC, "n8n DB read timed out", as_of)]
    except Exception as exc:  # InventoryUnavailable, ImportError, …
        return [_unknown(ACTIVE_WF_SPEC, f"n8n DB unreadable: {str(exc)[:160]}", as_of)]
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return [_unknown(ACTIVE_WF_SPEC, "n8n DB returned a non-count", as_of)]
    if n == 0:
        return [_item(*ACTIVE_WF_SPEC, "WARN", 0, "n8n reports no active workflow", as_of)]
    return [_item(*ACTIVE_WF_SPEC, "OK", n, None, as_of)]


DISPATCH_SPEC = ("n8n.dispatcher_last_run", "n8n", "dispatcher last run", "n8n coordination ledger runs (sqlite ro)")


def _ledger_path(deps: Deps) -> Path:
    if deps.ledger_path is not None:
        return Path(deps.ledger_path)
    try:
        try:
            from scripts.lib import lane_registry  # type: ignore
        except Exception:
            from lib import lane_registry  # type: ignore
        return Path(lane_registry.n8n_ledger_path(deps.state_root))
    except Exception:
        return (deps.state_root or _default_state_root()) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def probe_n8n_dispatcher(deps: Deps) -> list[dict]:
    now = deps.now()
    as_of = _iso(now)
    path = _ledger_path(deps)
    source = f"{DISPATCH_SPEC[3]} {path}"
    spec = (DISPATCH_SPEC[0], DISPATCH_SPEC[1], DISPATCH_SPEC[2], source)
    if not path.is_file():
        return [_unknown(spec, "coordination ledger absent", as_of)]
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=deps.probe_timeout_s)
        try:
            row = conn.execute(
                "SELECT requested_at, state, verdict, lane_id FROM runs ORDER BY requested_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError) as exc:
        return [_unknown(spec, f"ledger unreadable: {type(exc).__name__}", as_of)]
    if not row:
        return [_item(*spec, "WARN", "no runs", "the ledger has no run rows", as_of)]
    last = _parse_ts(row[0])
    if last is None:
        return [_unknown(spec, "latest run has no parseable requested_at", as_of)]
    age_min = (now - last).total_seconds() / 60.0
    detail = {"last_requested_at": _iso(last), "state": row[1], "verdict": row[2], "lane_id": row[3],
              "age_min": round(age_min, 1)}
    value = f"{_fmt_dur(age_min * 60)} ago ({row[3]}, {row[1]})"
    if age_min > DISPATCH_CRIT_MIN:
        return [_item(*spec, "CRIT", value, f"no dispatcher run for > {DISPATCH_CRIT_MIN:.0f} min", as_of, detail)]
    if age_min > DISPATCH_WARN_MIN:
        return [_item(*spec, "WARN", value, f"no dispatcher run for > {DISPATCH_WARN_MIN:.0f} min", as_of, detail)]
    return [_item(*spec, "OK", value, None, as_of, detail)]


# ── host units ───────────────────────────────────────────────────────────────


def _unit_spec(unit: str) -> tuple:
    return (f"unit.{unit.removesuffix('.service')}", "services", unit.removesuffix(".service"), "systemctl --user show")


def _parse_show_blocks(text: str) -> list[dict]:
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k.strip()] = v.strip()
    if cur:
        blocks.append(cur)
    return blocks


def _unix_ts(value: str) -> Optional[datetime]:
    v = (value or "").strip()
    if not v.startswith("@"):
        return None
    try:
        return datetime.fromtimestamp(float(v[1:]), tz=timezone.utc)
    except ValueError:
        return None


def probe_units(deps: Deps) -> list[dict]:
    now = deps.now()
    as_of = _iso(now)
    argv = ["systemctl", "--user", "show", "--timestamp=unix",
            "-p", "Id,LoadState,ActiveState,SubState,ActiveEnterTimestamp,NRestarts", *ALWAYS_ON_UNITS]
    try:
        proc = _run(deps, argv, env=_systemctl_env())
    except subprocess.TimeoutExpired:
        return [_unknown(_unit_spec(u), "systemctl timed out", as_of) for u in ALWAYS_ON_UNITS]
    except OSError as exc:
        return [_unknown(_unit_spec(u), f"systemctl not runnable: {type(exc).__name__}", as_of) for u in ALWAYS_ON_UNITS]
    if getattr(proc, "returncode", 1) != 0:
        reason = f"systemctl exit {proc.returncode}: {str(proc.stderr or '').strip()[:120]}"
        return [_unknown(_unit_spec(u), reason, as_of) for u in ALWAYS_ON_UNITS]
    by_id = {b.get("Id"): b for b in _parse_show_blocks(str(proc.stdout or "")) if b.get("Id")}
    out = []
    for unit in ALWAYS_ON_UNITS:
        spec = _unit_spec(unit)
        b = by_id.get(unit)
        if b is None:
            out.append(_unknown(spec, "systemctl returned no block for this unit", as_of))
            continue
        if b.get("LoadState") != "loaded":
            out.append(_unknown(spec, f"unit LoadState={b.get('LoadState') or '?'}", as_of))
            continue
        active, sub = b.get("ActiveState", ""), b.get("SubState", "")
        since = _unix_ts(b.get("ActiveEnterTimestamp", ""))
        try:
            restarts = int(b.get("NRestarts", ""))
        except ValueError:
            restarts = None
        detail = {"active_state": active, "sub_state": sub, "since": _iso(since) if since else None,
                  "restarts": restarts}
        if active == "active" and sub == "running":
            up = f"up {_fmt_dur((now - since).total_seconds())}" if since else "up (since unknown)"
            value = up + (f", {restarts} restart(s)" if restarts else "")
            out.append(_item(*spec, "OK", value, None, as_of, detail))
        elif active in ("activating", "reloading", "deactivating") or (active == "active" and sub != "running"):
            out.append(_item(*spec, "WARN", f"{active}/{sub}", f"unit is {active}/{sub}", as_of, detail))
        elif active in ("failed", "inactive"):
            out.append(_item(*spec, "CRIT", f"{active}/{sub}", f"always-on unit is {active}", as_of, detail))
        else:
            out.append(_unknown(spec, f"unrecognised ActiveState={active!r}", as_of))
    return out


FAILED_SPEC = ("unit.failed_tradeai", "services", "failed tradeai* units", "systemctl --user list-units --failed")


def probe_failed_units(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    argv = ["systemctl", "--user", "list-units", "--failed", "--no-legend", "--plain", "--no-pager", FAILED_UNIT_PATTERN]
    try:
        proc = _run(deps, argv, env=_systemctl_env())
    except subprocess.TimeoutExpired:
        return [_unknown(FAILED_SPEC, "systemctl timed out", as_of)]
    except OSError as exc:
        return [_unknown(FAILED_SPEC, f"systemctl not runnable: {type(exc).__name__}", as_of)]
    if getattr(proc, "returncode", 1) != 0:
        return [_unknown(FAILED_SPEC, f"systemctl exit {proc.returncode}", as_of)]
    names = [ln.split()[0] for ln in str(proc.stdout or "").splitlines() if ln.strip()]
    detail = {"units": names}
    if not names:
        return [_item(*FAILED_SPEC, "OK", 0, None, as_of, detail)]
    return [_item(*FAILED_SPEC, "WARN", len(names), "failed: " + ", ".join(names), as_of, detail)]


# ── disk / cpu / memory ──────────────────────────────────────────────────────


def disk_thresholds(path: Path) -> tuple[float, float, str]:
    try:
        mon = json.loads(Path(path).read_text()).get("monitor") or {}
        return float(mon["warn_pct"]), float(mon["critical_pct"]), f"{Path(path).name} monitor"
    except Exception:
        return DISK_DEFAULT_WARN, DISK_DEFAULT_CRIT, "defaults (config unreadable)"


def probe_disk(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    warn, crit, tsrc = disk_thresholds(deps.disk_config)
    state_root = deps.state_root or _default_state_root()
    mounts = [("host.disk.root", "disk /", "/"), ("host.disk.state", "disk persistent-state", str(state_root))]
    out, seen = [], {}
    for id_, label, path in mounts:
        spec = (id_, "host", label, f"disk_usage({path}); thresholds {tsrc} {warn:.0f}/{crit:.0f}%")
        try:
            du = deps.disk_usage(path)
            total, used, free = int(du.total), int(du.used), int(du.free)
        except Exception as exc:
            out.append(_unknown(spec, f"disk usage unreadable: {type(exc).__name__}", as_of))
            continue
        reach = used + free  # df-style, matching disk_usage_monitor.py
        if reach <= 0:
            out.append(_unknown(spec, "filesystem reports zero size", as_of))
            continue
        pct = round(used / reach * 100.0, 1)
        detail = {"used_pct": pct, "free_bytes": free, "total_bytes": total, "warn_pct": warn, "critical_pct": crit,
                  "path": path}
        sev = "CRIT" if pct >= crit else "WARN" if pct >= warn else "OK"
        reason = None if sev == "OK" else f"{pct}% used >= {crit if sev == 'CRIT' else warn:.0f}%"
        key = (total, used, free)
        if key in seen and seen[key] != path:
            reason = (reason + "; " if reason else "") + f"same filesystem as {seen[key]}"
        seen.setdefault(key, path)
        out.append(_item(*spec, sev, f"{pct}% used, {_fmt_bytes(free)} free", reason, as_of, detail))
    return out


CPU_SPEC = ("host.cpu", "host", "CPU load", "os.getloadavg / cpu count")


def probe_cpu(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    try:
        l1, l5, l15 = deps.loadavg()
        n = deps.cpu_count()
    except Exception as exc:
        return [_unknown(CPU_SPEC, f"load average unreadable: {type(exc).__name__}", as_of)]
    if not n or n <= 0:
        return [_unknown(CPU_SPEC, "cpu count unknown", as_of)]
    per = l5 / n
    detail = {"load1": round(l1, 2), "load5": round(l5, 2), "load15": round(l15, 2), "cpus": n,
              "load5_per_cpu": round(per, 2)}
    value = f"load {l1:.2f}/{l5:.2f}/{l15:.2f} on {n} CPUs"
    if per >= LOAD_CRIT_PER_CPU:
        return [_item(*CPU_SPEC, "CRIT", value, f"5-min load {per:.2f}/CPU >= {LOAD_CRIT_PER_CPU}", as_of, detail)]
    if per >= LOAD_WARN_PER_CPU:
        return [_item(*CPU_SPEC, "WARN", value, f"5-min load {per:.2f}/CPU >= {LOAD_WARN_PER_CPU}", as_of, detail)]
    return [_item(*CPU_SPEC, "OK", value, None, as_of, detail)]


MEM_SPEC = ("host.memory", "host", "memory", "/proc/meminfo MemAvailable")


def probe_memory(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    try:
        vals = {}
        for line in deps.meminfo().splitlines():
            k, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                vals[k.strip()] = int(parts[0]) * 1024
        total, avail = vals["MemTotal"], vals["MemAvailable"]
    except Exception as exc:
        return [_unknown(MEM_SPEC, f"meminfo unreadable: {type(exc).__name__}", as_of)]
    if total <= 0:
        return [_unknown(MEM_SPEC, "MemTotal is zero", as_of)]
    pct = round(avail / total * 100.0, 1)
    detail = {"available_bytes": avail, "total_bytes": total, "available_pct": pct}
    value = f"{_fmt_bytes(avail)} available of {_fmt_bytes(total)} ({pct}%)"
    if pct < MEM_CRIT_AVAIL_PCT:
        return [_item(*MEM_SPEC, "CRIT", value, f"available < {MEM_CRIT_AVAIL_PCT:.0f}%", as_of, detail)]
    if pct < MEM_WARN_AVAIL_PCT:
        return [_item(*MEM_SPEC, "WARN", value, f"available < {MEM_WARN_AVAIL_PCT:.0f}%", as_of, detail)]
    return [_item(*MEM_SPEC, "OK", value, None, as_of, detail)]


# ── backup ───────────────────────────────────────────────────────────────────


def probe_backup_artifact(deps: Deps) -> list[dict]:
    now = deps.now()
    as_of = _iso(now)
    d = Path(deps.backup_dir)
    spec = ("backup.latest_artifact", "backup", "newest DB backup", f"{d}/{BACKUP_GLOB} mtime")
    if not d.is_dir():
        return [_unknown(spec, "backup dir absent", as_of)]
    try:
        files = [(p.stat().st_mtime, p.stat().st_size, p) for p in d.glob(BACKUP_GLOB) if p.is_file()]
    except OSError as exc:
        return [_unknown(spec, f"backup dir unreadable: {type(exc).__name__}", as_of)]
    if not files:
        return [_item(*spec, "CRIT", "none", "no finished backup artifact in the backup dir", as_of)]
    mtime, size, p = max(files)
    age_h = (now.timestamp() - mtime) / 3600.0
    detail = {"file": p.name, "size_bytes": size, "mtime": _iso(datetime.fromtimestamp(mtime, tz=timezone.utc)),
              "age_h": round(age_h, 1)}
    value = f"{_fmt_dur(age_h * 3600)} old ({p.name}, {_fmt_bytes(size)})"
    if age_h > BACKUP_CRIT_H:
        return [_item(*spec, "CRIT", value, f"newest backup older than {BACKUP_CRIT_H:.0f}h", as_of, detail)]
    if age_h > BACKUP_WARN_H:
        return [_item(*spec, "WARN", value, f"newest backup older than {BACKUP_WARN_H:.0f}h", as_of, detail)]
    return [_item(*spec, "OK", value, None, as_of, detail)]


BACKUP_UNIT_SPEC = ("backup.cadence_unit", "backup", "backup cadence last run", f"systemctl --user show {BACKUP_UNIT}")


def probe_backup_unit(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    argv = ["systemctl", "--user", "show", "--timestamp=unix",
            "-p", "LoadState,ActiveState,Result,ExecMainStatus,ExecMainExitTimestamp", BACKUP_UNIT]
    try:
        proc = _run(deps, argv, env=_systemctl_env())
    except subprocess.TimeoutExpired:
        return [_unknown(BACKUP_UNIT_SPEC, "systemctl timed out", as_of)]
    except OSError as exc:
        return [_unknown(BACKUP_UNIT_SPEC, f"systemctl not runnable: {type(exc).__name__}", as_of)]
    if getattr(proc, "returncode", 1) != 0:
        return [_unknown(BACKUP_UNIT_SPEC, f"systemctl exit {proc.returncode}", as_of)]
    blocks = _parse_show_blocks(str(proc.stdout or ""))
    b = blocks[0] if blocks else {}
    if b.get("LoadState") != "loaded":
        return [_unknown(BACKUP_UNIT_SPEC, f"unit LoadState={b.get('LoadState') or '?'}", as_of)]
    ended = _unix_ts(b.get("ExecMainExitTimestamp", ""))
    detail = {"result": b.get("Result"), "exit_status": b.get("ExecMainStatus"), "active_state": b.get("ActiveState"),
              "last_exit": _iso(ended) if ended else None}
    if b.get("ActiveState") in ("activating", "active"):
        return [_item(*BACKUP_UNIT_SPEC, "OK", "running now", None, as_of, detail)]
    if ended is None:
        return [_unknown(BACKUP_UNIT_SPEC, "no completed run since the user manager started", as_of)]
    when = ended.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    if b.get("Result") == "success":
        return [_item(*BACKUP_UNIT_SPEC, "OK", f"success at {when}", None, as_of, detail)]
    return [_item(*BACKUP_UNIT_SPEC, "WARN", f"{b.get('Result')} (exit {b.get('ExecMainStatus')}) at {when}",
                  f"last backup cadence run did not succeed: Result={b.get('Result')}", as_of, detail)]


# ── main Postgres ────────────────────────────────────────────────────────────


PG_SPEC = ("postgres.main", "postgres", "main Postgres", "db_adapter read-only SELECT (pg_database_size, pg_stat_activity)")


def probe_postgres(deps: Deps) -> list[dict]:
    as_of = _iso(deps.now())
    if deps.db_query is None:
        return [_unknown(PG_SPEC, "no DB reader wired", as_of)]
    try:
        row = deps.db_query(PG_SQL, None, fetch="one")
    except Exception as exc:
        return [_unknown(PG_SPEC, f"DB query raised {type(exc).__name__}", as_of)]
    if not row:
        return [_unknown(PG_SPEC, "DB unreachable or query failed (reader returned nothing)", as_of)]
    try:
        size, conns, mx = int(row["size_bytes"]), int(row["connections"]), int(row["max_connections"])
    except (KeyError, TypeError, ValueError):
        return [_unknown(PG_SPEC, "DB answer is malformed", as_of)]
    pct = round(conns / mx * 100.0, 1) if mx > 0 else None
    detail = {"size_bytes": size, "connections": conns, "max_connections": mx, "connections_pct": pct}
    value = f"{_fmt_bytes(size)}, {conns}/{mx} connections"
    if pct is not None and pct >= PG_CONN_CRIT_PCT:
        return [_item(*PG_SPEC, "CRIT", value, f"connections at {pct}% of max", as_of, detail)]
    if pct is not None and pct >= PG_CONN_WARN_PCT:
        return [_item(*PG_SPEC, "WARN", value, f"connections at {pct}% of max", as_of, detail)]
    return [_item(*PG_SPEC, "OK", value, None, as_of, detail)]


# ── collection ───────────────────────────────────────────────────────────────

#: (probe, the item specs it owns — used to emit UNKNOWN rows when the probe itself times out or raises).
PROBES: list[tuple[Callable[[Deps], list], list[tuple]]] = [
    (probe_n8n_containers, [_container_spec(n) for n in N8N_CONTAINERS]),
    (probe_n8n_healthz, [HEALTHZ_SPEC]),
    (probe_n8n_active_workflows, [ACTIVE_WF_SPEC]),
    (probe_n8n_dispatcher, [DISPATCH_SPEC]),
    (probe_units, [_unit_spec(u) for u in ALWAYS_ON_UNITS]),
    (probe_failed_units, [FAILED_SPEC]),
    (probe_disk, [("host.disk.root", "host", "disk /", "disk_usage(/)"),
                  ("host.disk.state", "host", "disk persistent-state", "disk_usage(state root)")]),
    (probe_cpu, [CPU_SPEC]),
    (probe_memory, [MEM_SPEC]),
    (probe_backup_artifact, [("backup.latest_artifact", "backup", "newest DB backup", str(BACKUP_DIR))]),
    (probe_backup_unit, [BACKUP_UNIT_SPEC]),
    (probe_postgres, [PG_SPEC]),
]

_POOL = ThreadPoolExecutor(max_workers=len(PROBES), thread_name_prefix="platform-health")
#: The main-DB probe gets its own single thread: db_adapter's connection is thread-local, so pinning it here keeps
#: at most one extra connection open, and a hung connect blocks only the next DB probe (which then reports UNKNOWN).
_DB_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="platform-health-db")


def _safe(fn: Callable[[Deps], list], specs: list[tuple], deps: Deps) -> list[dict]:
    try:
        rows = fn(deps)
        if not isinstance(rows, list) or not rows:
            raise ValueError("probe returned no rows")
        return rows
    except Exception as exc:
        as_of = _iso(datetime.now(timezone.utc))
        return [_unknown(s, f"probe error: {type(exc).__name__}: {str(exc)[:120]}", as_of) for s in specs]


def collect(deps: Optional[Deps] = None, *, total_budget_s: float = TOTAL_BUDGET_S,
            probes: Optional[list] = None) -> dict:
    """Run every probe in parallel; each is capped at deps.probe_timeout_s, the whole run at total_budget_s."""
    deps = deps or Deps()
    probes = probes if probes is not None else PROBES
    started = time.monotonic()
    futures = []
    for fn, specs in probes:
        pool = _DB_POOL if fn is probe_postgres else _POOL
        futures.append((fn, specs, pool.submit(_safe, fn, specs, deps)))
    items: list[dict] = []
    for fn, specs, fut in futures:
        remaining = total_budget_s - (time.monotonic() - started)
        wait = max(0.0, min(deps.probe_timeout_s, remaining))
        try:
            items.extend(fut.result(timeout=wait))
        except FutureTimeout:
            fut.cancel()
            as_of = _iso(datetime.now(timezone.utc))
            why = "probe exceeded the 5 s budget" if remaining <= deps.probe_timeout_s else \
                f"probe exceeded {deps.probe_timeout_s:g} s"
            items.extend(_unknown(s, why, as_of) for s in specs)
        except Exception as exc:  # pragma: no cover — _safe already catches
            as_of = _iso(datetime.now(timezone.utc))
            items.extend(_unknown(s, f"probe error: {type(exc).__name__}", as_of) for s in specs)
    counts = {s: 0 for s in STATUSES}
    for it in items:
        counts[it["status"]] += 1
    worst = max((it["status"] for it in items), key=lambda s: _RANK[s], default="UNKNOWN")
    return {
        "schema": SCHEMA,
        "status": "OK",
        "as_of": _iso(deps.now()),
        "overall": worst,
        "counts": counts,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "cache_ttl_s": CACHE_TTL_S,
        "items": items,
        "note": "UNKNOWN means the probe could not look (reason given), never that the thing is fine.",
    }


_CACHE: dict = {"at": None, "payload": None}
_CACHE_LOCK = threading.Lock()


def get_platform_health(db_query: Optional[Callable[..., Any]] = None, *, deps: Optional[Deps] = None,
                        use_cache: bool = True, clock: Callable[[], float] = time.monotonic) -> dict:
    """The endpoint body. Never raises; cached CACHE_TTL_S."""
    with _CACHE_LOCK:
        at = _CACHE["at"]
        if use_cache and at is not None and _CACHE["payload"] is not None and clock() - at < CACHE_TTL_S:
            return dict(_CACHE["payload"], cached=True)
    try:
        d = deps or Deps(db_query=db_query)
        if d.db_query is None and db_query is not None:
            d.db_query = db_query
        payload = collect(d)
    except Exception as exc:
        return {"schema": SCHEMA, "status": "UNAVAILABLE", "overall": "UNKNOWN", "items": [],
                "as_of": _iso(datetime.now(timezone.utc)), "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    with _CACHE_LOCK:
        _CACHE["at"] = clock()
        _CACHE["payload"] = payload
    return dict(payload, cached=False)


def _reset_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["at"] = None
        _CACHE["payload"] = None
