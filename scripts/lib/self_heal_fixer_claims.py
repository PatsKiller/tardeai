"""Durable claims, leases and budget reservations for the self-heal fixer (sqlite + flock; no network, no model).

Architect review 2026-10-16 (finding 3): the fixer loaded JSON state, admitted work in memory, attempted it and saved
at the end, so a crash lost the attempt and two concurrent cycles could run the same defect twice. This module is the
durable side of an attempt:

* ``CycleLock``: one non-blocking ``flock`` per state root; a second ``--apply`` cycle exits ``busy`` without work.
* ``claim``: ONE active claim per defect signature (``dedupe_key``), enforced by a partial UNIQUE index inside a
  ``BEGIN IMMEDIATE`` transaction, and the job's whole budget (iterations, USD, seconds) RESERVED in the same
  transaction, BEFORE the backend is launched. Daily caps (jobs, USD) are checked against reservations, not spend.
* ``heartbeat`` / ``Heartbeat``: the owner renews its lease while the backend runs.
* ``record_progress``: per-iteration partial evidence (iterations done, spend so far, evidence dir) is durable.
* ``settle``: the attempt ended; the counted spend becomes the recorded spend.
* ``reconcile``: on start, an ``active`` claim whose lease expired (or whose owner pid on this host is dead) becomes
  ``interrupted`` with its recorded partial evidence. It is NOT restarted. Its reservation stays counted exactly once
  (the actual spend after the last record is unknown, so the reservation is the conservative figure).

Budget accounting: a claim counts ``reserved_usd`` while active or interrupted and ``spent_usd`` once settled. Each
claim is one row, so nothing can be counted twice; ``reconcile`` is idempotent.
"""
from __future__ import annotations

import fcntl
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

SCHEMA = "SelfHealFixerClaims@v1"
ACTIVE, SETTLED, INTERRUPTED = "active", "settled", "interrupted"

_DDL = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL,
    job_id TEXT NOT NULL,
    state TEXT NOT NULL,
    owner_host TEXT NOT NULL,
    owner_pid INTEGER NOT NULL,
    day TEXT NOT NULL,
    claimed_at REAL NOT NULL,
    heartbeat_at REAL NOT NULL,
    lease_expires_at REAL NOT NULL,
    reserved_iterations INTEGER NOT NULL,
    reserved_usd REAL NOT NULL,
    reserved_seconds REAL NOT NULL,
    spent_usd REAL NOT NULL DEFAULT 0,
    iterations_done INTEGER NOT NULL DEFAULT 0,
    evidence_dir TEXT,
    partial_json TEXT,
    ended_at REAL,
    outcome TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_claim_per_signature ON claims(dedupe_key) WHERE state = 'active';
CREATE INDEX IF NOT EXISTS claims_by_day ON claims(day);
"""


def _host() -> str:
    return socket.gethostname()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


@contextmanager
def connect(path: Path, *, write: bool = True) -> Iterator[sqlite3.Connection]:
    """One transaction. ``write`` opens it with BEGIN IMMEDIATE (the database write lock), so check-then-insert is
    atomic across processes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.executescript(_DDL)
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield con
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


class CycleLock:
    """Non-blocking exclusive flock: exactly one fixer cycle per state root at a time."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = self.path.open("a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"pid": os.getpid(), "host": _host(), "at": time.time()}) + "\n")
        fh.flush()
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "CycleLock":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


def _counted_usd(row: sqlite3.Row) -> float:
    return float(row["spent_usd"] if row["state"] == SETTLED else max(row["reserved_usd"], row["spent_usd"]))


def usage(con: sqlite3.Connection, day: str) -> dict:
    rows = con.execute("SELECT * FROM claims WHERE day=?", (day,)).fetchall()
    return {"day": day, "jobs": len(rows), "usd": round(sum(_counted_usd(r) for r in rows), 4),
            "active": sum(1 for r in rows if r["state"] == ACTIVE),
            "interrupted": sum(1 for r in rows if r["state"] == INTERRUPTED)}


def claim(db: Path, *, dedupe_key: str, job_id: str, day: str, reserve_iterations: int, reserve_usd: float,
          reserve_seconds: float, lease_ttl_s: float, daily_job_cap: int, daily_usd_cap: float,
          evidence_dir: Optional[str] = None, now_ts: Optional[float] = None,
          pid: Optional[int] = None) -> tuple[Optional[str], str]:
    """Atomically claim ``dedupe_key`` and reserve the job's whole budget. (claim_id, "claimed") or (None, why)."""
    t = time.time() if now_ts is None else now_ts
    with connect(db) as con:
        held = con.execute("SELECT claim_id, job_id FROM claims WHERE dedupe_key=? AND state=?",
                           (dedupe_key, ACTIVE)).fetchone()
        if held:
            return None, f"claimed_elsewhere:{held['job_id']}"
        u = usage(con, day)
        if u["jobs"] >= int(daily_job_cap):
            return None, f"daily_job_cap:{u['jobs']}/{daily_job_cap}"
        if u["usd"] + float(reserve_usd) > float(daily_usd_cap) + 1e-9:
            return None, f"daily_usd_cap:{u['usd']:.2f}+{float(reserve_usd):.2f}>{float(daily_usd_cap):.2f}"
        cid = f"clm-{uuid.uuid4().hex[:16]}"
        try:
            con.execute(
                "INSERT INTO claims (claim_id, dedupe_key, job_id, state, owner_host, owner_pid, day, claimed_at, "
                "heartbeat_at, lease_expires_at, reserved_iterations, reserved_usd, reserved_seconds, evidence_dir) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, dedupe_key, job_id, ACTIVE, _host(), int(pid or os.getpid()), day, t, t, t + float(lease_ttl_s),
                 int(reserve_iterations), float(reserve_usd), float(reserve_seconds), evidence_dir))
        except sqlite3.IntegrityError:
            return None, "claimed_elsewhere:race"
    return cid, "claimed"


def heartbeat(db: Path, claim_id: str, *, lease_ttl_s: float, now_ts: Optional[float] = None) -> bool:
    t = time.time() if now_ts is None else now_ts
    with connect(db) as con:
        cur = con.execute("UPDATE claims SET heartbeat_at=?, lease_expires_at=? WHERE claim_id=? AND state=?",
                          (t, t + float(lease_ttl_s), claim_id, ACTIVE))
        return cur.rowcount == 1


def record_progress(db: Path, claim_id: str, *, iterations_done: int, spent_usd: float,
                    partial: Optional[dict] = None) -> None:
    with connect(db) as con:
        con.execute("UPDATE claims SET iterations_done=?, spent_usd=?, partial_json=? WHERE claim_id=? AND state=?",
                    (int(iterations_done), float(spent_usd), json.dumps(partial or {}, default=str, sort_keys=True),
                     claim_id, ACTIVE))


def settle(db: Path, claim_id: str, *, outcome: str, spent_usd: float, iterations_done: int,
           now_ts: Optional[float] = None) -> bool:
    t = time.time() if now_ts is None else now_ts
    with connect(db) as con:
        cur = con.execute("UPDATE claims SET state=?, outcome=?, spent_usd=?, iterations_done=?, ended_at=? "
                          "WHERE claim_id=? AND state=?",
                          (SETTLED, outcome, float(spent_usd), int(iterations_done), t, claim_id, ACTIVE))
        return cur.rowcount == 1


def reconcile(db: Path, *, now_ts: Optional[float] = None,
              alive: Callable[[int], bool] = pid_alive) -> list[dict]:
    """Mark every dead active claim ``interrupted`` (lease expired, or owner pid on this host gone). Returns them,
    with their recorded partial evidence. Idempotent: an already-interrupted claim is never touched again."""
    t = time.time() if now_ts is None else now_ts
    host = _host()
    out = []
    with connect(db) as con:
        for r in con.execute("SELECT * FROM claims WHERE state=?", (ACTIVE,)).fetchall():
            expired = float(r["lease_expires_at"]) <= t
            dead = r["owner_host"] == host and not alive(int(r["owner_pid"]))
            if not (expired or dead):
                continue
            why = "lease_expired" if expired else "owner_pid_dead"
            con.execute("UPDATE claims SET state=?, outcome=?, ended_at=? WHERE claim_id=? AND state=?",
                        (INTERRUPTED, why, t, r["claim_id"], ACTIVE))
            try:
                partial = json.loads(r["partial_json"] or "{}")
            except ValueError:
                partial = {}
            out.append({"claim_id": r["claim_id"], "job_id": r["job_id"], "dedupe_key": r["dedupe_key"], "why": why,
                        "owner_pid": r["owner_pid"], "owner_host": r["owner_host"],
                        "heartbeat_at": datetime.fromtimestamp(r["heartbeat_at"], tz=timezone.utc).isoformat(),
                        "iterations_done": r["iterations_done"], "spent_usd_recorded": r["spent_usd"],
                        "reserved_usd_counted": r["reserved_usd"], "evidence_dir": r["evidence_dir"],
                        "partial": partial})
    return out


def rows(db: Path) -> list[dict]:
    if not Path(db).exists():
        return []
    with connect(db, write=False) as con:
        return [dict(r) for r in con.execute("SELECT * FROM claims ORDER BY claimed_at").fetchall()]


def day_usage(db: Path, day: str) -> dict:
    with connect(db, write=False) as con:
        return usage(con, day)


class Heartbeat:
    """Renews a claim's lease every ``every_s`` seconds on a daemon thread while the attempt runs."""

    def __init__(self, db: Path, claim_id: str, *, lease_ttl_s: float, every_s: float):
        self.db, self.claim_id, self.ttl, self.every = Path(db), claim_id, float(lease_ttl_s), float(every_s)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, name=f"shf-heartbeat-{claim_id}", daemon=True)
        self.beats = 0
        self.lost = False

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                ok = heartbeat(self.db, self.claim_id, lease_ttl_s=self.ttl)
            except sqlite3.Error:
                ok = False
            self.beats += 1
            if not ok:
                self.lost = True

    def __enter__(self) -> "Heartbeat":
        self._t.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._t.join(timeout=5)
