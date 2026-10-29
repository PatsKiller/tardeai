"""release_train_drain.py — the 06:00 window's drain probe (release train Phase 7, AGENTS.md §25.3).

06:00 may release only when the system is provably quiescent for the whole promote span. ``ReadOnlyDrainProbe``
replaces the controller's hardcoded ``UnprovenDrain`` on the production path (``build_controller``) and answers the
controller's ``DrainProbe`` protocol: ``check(window) -> (ok, detail)``. Every check is read-only, and any check that
cannot be evaluated is a refusal (fail closed): "unproven" is never "drained".

The span. A promote can start anywhere inside the window, so the span is
``[window.start - pre_guard_min, window.end + measured restart impact + buffer_min]``. The measured restart impact is
the worst measured promote + verify + rollback (``release_train_timing.DurationHistory``: at least 3 samples of each,
else refused) and must not exceed ``max_restart_impact_s``.

The checks (``config/release_train_drain_policy.json``, a protected surface of the controller):

  1. policy      — the policy file loads and names this slot.
  2. impact      — promote, verify and rollback are each measured (>= 3 samples) and their worst sum is within
                   ``max_restart_impact_s``.
  3. market      — on a NYSE trading day the span ends at least ``market_guard_min`` before the regular open
                   (``cio_market_session``: holidays, early closes, DST), and never overlaps regular hours.
  4. schedule    — no declared critical lane is due inside ``[span start - pre_guard, span end]``. Critical lanes are
                   the ACTIVE ``config/lane_registry.json`` rows whose ``value_class`` is in
                   ``critical_value_classes``, plus ``critical_lanes_extra``. Fires are computed DST-safe
                   (``cron_schedule.fires_between``). A lane in ``restart_tolerant`` (operator-reviewed, with a
                   reason) is exempt from the due check only. A daemon (systemd ``*.service``, no timer) has no
                   schedule; its restart is the measured impact. Any other schedule that cannot be read is a refusal.
  5. running     — no ``pipeline_runs`` row for a critical lane is in a running status (started within
                   ``running_lookback_h``). The DB unreadable is a refusal.
  6. locks       — no ``flock`` lock named by a critical lane's crontab line (or ``extra_locks``) is held, read from
                   ``/proc/locks`` by inode; never acquired. ``/proc/locks`` unreadable is a refusal.

Inert: the controller consults the probe only for slot 0600, and a live train refuses a disabled slot before any
window rule runs (``REFUSED_WINDOW_DISABLED``); every slot ships disabled. Enabling 06:00 is an operator scope change
(§17, §25.3) made after this probe's proof (a 06:00 receipt with ``drain.ok true`` and ``RELEASED_VERIFIED``).

Stdlib only (the DB reader imports ``scripts.session13_db`` lazily). AUTHORITY: READ_ONLY_ADVISORY: no broker, no
network, no writes, no lock is ever taken.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:
    from scripts.lib import cio_market_session as MS
    from scripts.lib import cron_schedule as CS
    from scripts.lib import release_train_timing as TM
except ImportError:  # pragma: no cover - scripts/ on sys.path
    from lib import cio_market_session as MS  # type: ignore[no-redef]
    from lib import cron_schedule as CS  # type: ignore[no-redef]
    from lib import release_train_timing as TM  # type: ignore[no-redef]

SCHEMA = "ReleaseTrainDrain@v1"
POLICY_SCHEMA = "ReleaseTrainDrainPolicy@v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "release_train_drain_policy.json"
LANE_REGISTRY = REPO_ROOT / "config" / "lane_registry.json"
PROC_LOCKS = Path("/proc/locks")
TZ_NAME = "America/New_York"

_FLOCK_RE = re.compile(r"\bflock\s+(?:-[A-Za-z]+(?:\s+\d+)?\s+)*(/[^\s;|&'\"]+)")

_POLICY_NUMBERS = {"pre_guard_min": (0, 120), "buffer_min": (0, 120), "max_restart_impact_s": (1, 7200),
                   "market_guard_min": (0, 240), "running_lookback_h": (1, 48)}


class PolicyError(ValueError):
    pass


def load_policy(path: Path = POLICY_PATH) -> dict:
    """The drain policy, validated; raises PolicyError (the probe then refuses)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"drain policy unreadable: {type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != POLICY_SCHEMA:
        raise PolicyError(f"drain policy schema is not {POLICY_SCHEMA}")
    for key, (lo, hi) in _POLICY_NUMBERS.items():
        v = doc.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= v <= hi):
            raise PolicyError(f"drain policy {key} must be a number in [{lo}, {hi}]")
    for key in ("slots", "critical_value_classes", "critical_lanes_extra", "critical_pipeline_keys",
                "running_statuses", "extra_locks"):
        v = doc.get(key)
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise PolicyError(f"drain policy {key} must be a list of strings")
    if not doc["critical_value_classes"] and not doc["critical_lanes_extra"]:
        raise PolicyError("drain policy declares no critical lanes")
    if not doc["running_statuses"]:
        raise PolicyError("drain policy running_statuses is empty")
    tol = doc.get("restart_tolerant")
    if not isinstance(tol, dict) or not all(isinstance(k, str) and isinstance(v, str) and len(v.strip()) >= 10
                                            for k, v in tol.items()):
        raise PolicyError("drain policy restart_tolerant must map lane id -> a reason (>= 10 chars)")
    if any(not os.path.isabs(p) for p in doc["extra_locks"]):
        raise PolicyError("drain policy extra_locks must be absolute paths")
    return doc


def norm_key(s: Any) -> str:
    return str(s or "").strip().lower().replace("_", "-")


# ── readers (each injectable; each returns None when it cannot read, which is a refusal) ─────────────

def read_registry(path: Path = LANE_REGISTRY) -> Optional[dict]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("lanes"), list) else None


PIPELINE_SQL = (
    "SELECT pipeline_key, run_id, status, started_at FROM pipeline_runs "
    "WHERE LOWER(status) = ANY(%s) AND started_at > NOW() - make_interval(hours => %s) "
    "ORDER BY started_at DESC LIMIT 500"
)


def read_running_pipelines(statuses: list[str], lookback_h: int) -> Optional[list[dict]]:
    """Running ``pipeline_runs`` rows, in a READ ONLY transaction; None when the DB cannot be read."""
    conn = None
    try:
        from scripts.session13_db import get_conn  # lazy: hermetic tests inject a reader instead
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(PIPELINE_SQL, ([s.lower() for s in statuses], int(lookback_h)))
        rows = cur.fetchall()
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append({k: r.get(k) for k in ("pipeline_key", "run_id", "status", "started_at")})
            else:
                out.append({"pipeline_key": r[0], "run_id": r[1], "status": r[2], "started_at": r[3]})
        return out
    except Exception:  # noqa: BLE001 — any failure is UNREADABLE, never "nothing running"
        return None
    finally:
        if conn is not None:
            try:
                conn.rollback()
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def read_held_locks(paths: Iterable[str], proc_locks: Path = PROC_LOCKS) -> Optional[dict[str, bool]]:
    """{path: held} from ``/proc/locks`` by device and inode; a path that does not exist is not held. None when
    ``/proc/locks`` cannot be read. Read-only: no lock is ever attempted."""
    try:
        text = Path(proc_locks).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    held_ids = set()
    for line in text.splitlines():
        parts = line.split()
        # "1: FLOCK  ADVISORY  WRITE 1234 00:1f:5678 0 EOF" ("->" marks a blocked waiter; skip it)
        if len(parts) < 6 or parts[1] == "->":
            continue
        ident = parts[5]
        if ident.count(":") == 2:
            held_ids.add(ident.lower())
    out: dict[str, bool] = {}
    for p in paths:
        try:
            st = os.stat(p)
        except FileNotFoundError:
            out[p] = False
            continue
        except OSError:
            return None
        ident = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
        out[p] = ident in held_ids
    return out


# ── the probe ─────────────────────────────────────────────────────────────────────────────────────

@dataclass
class ReadOnlyDrainProbe:
    """``check(window) -> (ok, detail)``; ``last_report`` holds the full ReleaseTrainDrain@v1 evidence."""

    history: TM.DurationHistory
    policy_loader: Callable[[], dict] = load_policy
    registry_reader: Callable[[], Optional[dict]] = read_registry
    pipeline_reader: Callable[[list, int], Optional[list]] = read_running_pipelines
    lock_reader: Callable[[Iterable[str]], Optional[dict]] = read_held_locks
    session: MS.NYSESessionService = field(default_factory=MS.NYSESessionService)
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    last_report: dict = field(default_factory=dict)

    def check(self, window: Any) -> tuple[bool, str]:
        report: dict[str, Any] = {"schema": SCHEMA, "slot": getattr(window, "slot", None),
                                  "window_id": getattr(window, "window_id", None),
                                  "probed_at": self.clock().astimezone(timezone.utc).isoformat(), "checks": {}}
        self.last_report = report
        try:
            ok, why = self._check(window, report)
        except Exception as exc:  # noqa: BLE001 — a probe that cannot finish has proven nothing
            ok, why = False, f"drain probe error: {type(exc).__name__}: {str(exc)[:160]}"
        report["ok"], report["detail"] = ok, why
        return ok, why

    def _fail(self, report: dict, name: str, why: str, **kw: Any) -> tuple[bool, str]:
        report["checks"][name] = {"ok": False, "detail": why, **kw}
        return False, f"{name}: {why}"

    def _check(self, w: Any, report: dict) -> tuple[bool, str]:
        # 1. policy
        try:
            pol = self.policy_loader()
        except PolicyError as exc:
            return self._fail(report, "policy", str(exc))
        if str(w.slot) not in pol["slots"]:
            return self._fail(report, "policy", f"slot {w.slot} is not a drain slot {pol['slots']}")
        report["checks"]["policy"] = {"ok": True}

        # 2. measured restart impact
        worst, why = self.history.worst_all()
        report["durations"] = self.history.summary()
        if worst is None:
            return self._fail(report, "impact", why)
        impact = sum(worst.values())
        if impact > pol["max_restart_impact_s"]:
            return self._fail(report, "impact", f"measured restart impact {impact:.0f}s exceeds "
                              f"{pol['max_restart_impact_s']}s", worst=worst)
        start = w.start - timedelta(minutes=pol["pre_guard_min"])
        end = w.end + timedelta(seconds=impact) + timedelta(minutes=pol["buffer_min"])
        report["span"] = {"start": start.isoformat(), "end": end.isoformat(), "impact_s": round(impact, 1)}
        report["checks"]["impact"] = {"ok": True, "worst": worst}

        # 3. market hours (each session day the span touches)
        for day in sorted({start.astimezone(self.session.tz).date(), end.astimezone(self.session.tz).date()}):
            open_dt, close_dt, _ = self.session.official_bounds(day)
            if open_dt is None:
                continue
            guard_open = open_dt - timedelta(minutes=pol["market_guard_min"])
            if start < close_dt and end > guard_open:
                return self._fail(report, "market", f"span {start.isoformat()}..{end.isoformat()} reaches "
                                  f"{guard_open.isoformat()} ({pol['market_guard_min']} min before the "
                                  f"{open_dt.strftime('%H:%M')} open on {day})")
        report["checks"]["market"] = {"ok": True}

        # critical lanes
        reg = self.registry_reader()
        if reg is None:
            return self._fail(report, "schedule", "lane registry unreadable")
        lanes = critical_lanes(reg, pol)
        missing = sorted(set(pol["critical_lanes_extra"]) - {l["lane_id"] for l in lanes})
        if missing:
            return self._fail(report, "schedule", f"declared critical lanes not ACTIVE in the registry: {missing}")
        report["critical_lanes"] = [l["lane_id"] for l in lanes]

        # 4. schedule
        due: list[dict] = []
        unknown: list[str] = []
        for lane in lanes:
            lid, sched = lane["lane_id"], lane.get("scheduler") or {}
            if lid in pol["restart_tolerant"] or is_daemon(sched):
                continue
            exprs = schedules_of(sched)
            if not exprs:
                unknown.append(lid)
                continue
            tz = sched.get("timezone") or TZ_NAME
            for ex in exprs:
                try:
                    fires = list(CS.fires_between(ex, start, end, tz=tz))
                except (ValueError, KeyError) as exc:
                    unknown.append(f"{lid} ({type(exc).__name__})")
                    break
                if fires:
                    due.append({"lane": lid, "expression": ex, "fires": [f.at.isoformat() for f in fires[:3]]})
                    break
        if unknown:
            return self._fail(report, "schedule", f"schedule not readable for critical lanes {sorted(unknown)[:8]}")
        if due:
            names = ", ".join(f"{d['lane']}@{d['fires'][0][11:16]}" for d in due[:6])
            return self._fail(report, "schedule", f"{len(due)} critical lane(s) due inside the span: {names}",
                              due=due)
        report["checks"]["schedule"] = {"ok": True, "lanes": len(lanes)}

        # 5. running pipeline_runs
        keys = {norm_key(l["lane_id"]) for l in lanes} | {norm_key(k) for k in pol["critical_pipeline_keys"]}
        rows = self.pipeline_reader(list(pol["running_statuses"]), int(pol["running_lookback_h"]))
        if rows is None:
            return self._fail(report, "running", "pipeline_runs unreadable")
        running = [r for r in rows if norm_key(r.get("pipeline_key")) in keys]
        if running:
            names = sorted({str(r.get("pipeline_key")) for r in running})
            return self._fail(report, "running", f"critical pipeline run(s) in progress: {names[:6]}",
                              runs=[{"pipeline_key": r.get("pipeline_key"), "run_id": r.get("run_id"),
                                     "status": r.get("status"), "started_at": str(r.get("started_at"))}
                                    for r in running[:10]])
        report["checks"]["running"] = {"ok": True, "pipeline_keys": len(keys)}

        # 6. locks
        paths = sorted({p for l in lanes for p in lock_paths(l.get("scheduler") or {})} | set(pol["extra_locks"]))
        held = self.lock_reader(paths)
        if held is None:
            return self._fail(report, "locks", "/proc/locks or a lock path unreadable")
        busy = sorted(p for p, h in held.items() if h)
        if busy:
            return self._fail(report, "locks", f"critical lock(s) held: {busy[:6]}")
        report["checks"]["locks"] = {"ok": True, "paths": len(paths)}

        return True, (f"drained: {len(lanes)} critical lanes not due/running, {len(paths)} locks free, span "
                      f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')} ET clear of the open, impact {impact:.0f}s")


def critical_lanes(reg: dict, pol: dict) -> list[dict]:
    classes, extra = set(pol["critical_value_classes"]), set(pol["critical_lanes_extra"])
    out = []
    for lane in reg.get("lanes") or []:
        if not isinstance(lane, dict) or lane.get("state") != "ACTIVE":
            continue
        if lane.get("value_class") in classes or lane.get("lane_id") in extra:
            out.append(lane)
    return out


def is_daemon(sched: dict) -> bool:
    """A long-running systemd service (no timer): restarted by the promote, never "due"."""
    expr = str(sched.get("expression") or "")
    return (sched.get("kind") == "systemd" and expr.endswith(".service") and not sched.get("on_calendar")
            and not sched.get("schedules"))


def schedules_of(sched: dict) -> list[str]:
    if sched.get("kind") not in ("cron", "n8n"):
        return []
    out: list[str] = []
    for ex in ([sched.get("expression"), sched.get("cadence")] + list(sched.get("schedules") or [])
               + list(sched.get("due_schedules") or [])):
        if isinstance(ex, str):
            out.extend(f for f in CS.cron_schedules(ex) if f != CS.REBOOT)
    return out


def lock_paths(sched: dict) -> list[str]:
    out = []
    for v in sched.values():
        if isinstance(v, str):
            out.extend(_FLOCK_RE.findall(v))
    return out


def default_drain_probe(state_root: Path) -> ReadOnlyDrainProbe:
    """The production probe: the controller's train_measurements.jsonl plus the deploy receipt history."""
    return ReadOnlyDrainProbe(history=TM.DurationHistory(Path(state_root) / "train_measurements.jsonl"))
