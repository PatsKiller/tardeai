"""worker_contract.py — the ONE worker contract every lane converges on (Wave 4 O-W4-1; 06 §3, due-diligence §5).

    with worker_contract.lease("edge-fanout-consumer") as w:      # one lease per lane (owner, boot_id, TTL)
        w.claimed(n); ... ; w.done(k) / w.failed(e)                  # counts → one heartbeat at exit
        w.status(item_id, "RUNNING")                                 # the shared vocabulary

Status vocabulary (QUEUED → LEASED → RUNNING → DONE | FAILED | ABANDONED; EXPIRED by the reaper) with the
mapping from every existing queue's words (``STATUS_MAP``), so a dashboard reads one language. The lease
is a file under ``<state>/data/runtime/leases/<lane>.json`` guarded by flock: a second worker on the same
lane while the lease is fresh gets ``LeaseHeld``; a stale lease (expired TTL or a different boot_id) is
reclaimed and the reclaim is recorded. Heartbeat: ``supervisor_heartbeat.beat`` at exit (success or not).
Reference implementation: ``scripts/edge_fanout_consumer.py``. Migration of the other queues is per lane,
each keeping its store and gaining lease + heartbeat + this vocabulary. Zero authority.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "WorkerLease@v1"
STATUSES = ("QUEUED", "LEASED", "RUNNING", "DONE", "FAILED", "ABANDONED", "EXPIRED")
STATUS_MAP = {
    # hermes research store (cio_hermes_research)
    "idle": "QUEUED", "queued": "QUEUED", "started": "LEASED", "running": "RUNNING", "completed": "DONE", "failed": "FAILED",
    "reused": "DONE", "superseded": "ABANDONED", "cancelled": "ABANDONED",
    # watchlist_agent_jobs
    "pending": "QUEUED", "processing": "RUNNING", "deferred": "QUEUED", "expired": "EXPIRED",
    # inference_ensemble_jobs
    "done": "DONE", "error": "FAILED",
    # cio wake jobs
    "PENDING": "QUEUED", "CLAIMED": "LEASED", "DISPATCHED": "RUNNING", "ACKNOWLEDGED": "RUNNING", "IN_FLIGHT": "RUNNING",
    "RETRY_PENDING": "QUEUED", "COMPLETED": "DONE", "EXPIRED": "EXPIRED", "CANCELLED": "ABANDONED",
    # cio runs
    "BLOCKED": "FAILED", "FAILED": "FAILED", "WAITING_FOR_SPECIALISTS": "RUNNING", "WAITING_FOR_HERMES": "RUNNING",
    # escalation queue
    "dispatched": "RUNNING", "investigating": "RUNNING", "fixed": "DONE",
}
DEFAULT_TTL_S = 900


class LeaseHeld(RuntimeError):
    """Another live worker holds this lane's lease."""


def canonical_status(raw: str | None) -> str:
    s = str(raw or "").strip()
    return STATUS_MAP.get(s) or STATUS_MAP.get(s.lower()) or (s.upper() if s.upper() in STATUSES else "QUEUED")


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown-boot"


def _state_root(env: dict) -> Path:
    if env.get("TRADEAI_STATE_ROOT"):
        return Path(env["TRADEAI_STATE_ROOT"])
    try:
        from canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def leases_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_LEASES_DIR") or (_state_root(env) / "data" / "runtime" / "leases"))


class Worker:
    def __init__(self, lane_id: str, *, ttl_s: int, env: dict, root: Path | None):
        self.lane_id = lane_id; self.ttl_s = ttl_s; self.env = env; self.root = root
        self.lease_id = "lease_" + uuid.uuid4().hex[:12]; self.boot = boot_id(); self.pid = os.getpid()
        self.work_claimed = 0; self.work_done = 0; self.work_failed = 0
        self.transitions: list[dict] = []; self.reclaimed_from: dict | None = None; self.error: str | None = None
        self._fh = None

    def claimed(self, n: int = 1) -> None:
        self.work_claimed += int(n)

    def done(self, n: int = 1) -> None:
        self.work_done += int(n)

    def failed(self, err: str | None = None, n: int = 1) -> None:
        self.work_failed += int(n)
        if err:
            self.error = str(err)[:300]

    def status(self, item_id: str, raw_status: str, **extra: Any) -> dict:
        row = {"lane_id": self.lane_id, "item_id": str(item_id), "status": canonical_status(raw_status), "raw": raw_status,
               "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), **extra}
        self.transitions.append(row)
        return row

    def touch(self) -> None:
        """Extend the lease (long jobs)."""
        _write_lease(self, extend=True)


def _lease_path(w: Worker) -> Path:
    return leases_dir(w.env) / f"{w.lane_id}.json"


def _write_lease(w: Worker, *, extend: bool = False) -> dict:
    now = _dt.datetime.now(_dt.timezone.utc)
    row = {"schema": SCHEMA, "lane_id": w.lane_id, "lease_id": w.lease_id, "owner_pid": w.pid, "boot_id": w.boot,
           "acquired_at": now.isoformat() if not extend else None, "expires_at": (now + _dt.timedelta(seconds=w.ttl_s)).isoformat(),
           "ttl_s": w.ttl_s, "reclaimed_from": w.reclaimed_from}
    p = _lease_path(w)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, sort_keys=True, default=str) + "\n", encoding="utf-8"); os.replace(tmp, p)
    return row


def _read_lease(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _stale(lease: dict, now: _dt.datetime, boot: str) -> str | None:
    if lease.get("boot_id") and lease["boot_id"] != boot:
        return "different boot_id"
    try:
        if _dt.datetime.fromisoformat(str(lease.get("expires_at")).replace("Z", "+00:00")) < now:
            return "ttl expired"
    except (ValueError, TypeError):
        return "unparseable expiry"
    return None


@contextlib.contextmanager
def lease(lane_id: str, *, ttl_s: int = DEFAULT_TTL_S, env: dict | None = None, root: Path | None = None, heartbeat: bool = True):
    """Acquire the lane's lease (or raise LeaseHeld), yield the Worker, release + heartbeat at exit."""
    env = os.environ if env is None else env
    w = Worker(lane_id, ttl_s=ttl_s, env=env, root=root)
    d = leases_dir(env); d.mkdir(parents=True, exist_ok=True)
    lock = (d / f"{lane_id}.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        cur = _read_lease(_lease_path(w))
        if cur and cur.get("lease_id") and not cur.get("released_at"):
            why = _stale(cur, now, w.boot)
            if why is None:
                raise LeaseHeld(f"{lane_id}: lease {cur.get('lease_id')} held by pid {cur.get('owner_pid')} until {cur.get('expires_at')}")
            w.reclaimed_from = {"lease_id": cur.get("lease_id"), "owner_pid": cur.get("owner_pid"), "why": why}
        _write_lease(w)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
    ok = False
    try:
        yield w
        ok = w.work_failed == 0 and w.error is None
    except Exception as exc:  # noqa: BLE001
        w.failed(f"{type(exc).__name__}:{exc}")
        raise
    finally:
        try:
            p = _lease_path(w)
            cur = _read_lease(p) or {}
            if cur.get("lease_id") == w.lease_id:
                cur["released_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(); cur["outcome"] = "DONE" if ok else "FAILED"
                cur["work"] = {"claimed": w.work_claimed, "done": w.work_done, "failed": w.work_failed}
                tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(cur, sort_keys=True, default=str) + "\n", encoding="utf-8"); os.replace(tmp, p)
        except OSError:
            pass
        if heartbeat:
            try:
                import supervisor_heartbeat as hb  # type: ignore
                hb.beat(lane_id, success=ok, output_signal=w.work_done > 0, work_claimed=w.work_claimed, work_done=w.work_done,
                        work_failed=w.work_failed, degraded_reasons=[w.error] if w.error else None, root=root, env=env)
            except Exception:  # noqa: BLE001
                pass
        try:
            lock.close()
        except OSError:
            pass
