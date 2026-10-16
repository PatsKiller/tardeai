"""nightly_cutover_txn.py — the nightly cutover controller's durable quota ledger and write-ahead transactions (2026-10-16).

Architect review, 2026-10-16, before anything runs unattended:

1. **Durable nightly quota.** "5 per night" was enforced per evaluation, so a second invocation started a new count.
   The quota ledger ``<receipt_dir>/quota/night-<ET night>.json`` (NightlyCutoverQuota@v1) records one reservation per
   lane, written under the controller lock BEFORE the lane's first mutation, and counted across every invocation. An
   ET night runs noon to noon America/New_York and is named by its evening's date (19:30 Fri and 01:00 Sat are both
   night ``Fri``). A reservation is ``reserved`` -> ``applied`` (committed) or ``released`` (rolled back); reserved and
   applied count.
2. **Write-ahead transaction record.** Before the first mutation of a lane the controller writes
   ``<receipt_dir>/txn/<txn_id>.json`` (NightlyCutoverTxn@v1): the lane, the planned crontab edits, the registry-row
   and health-contract before/after images, the hashes of the files before, and backup copies beside it. Each step
   (crontab -> registry -> contracts -> rollback_receipt) is marked ``intent`` before and ``done`` after. The record
   is rewritten atomically (temp + fsync + rename + directory fsync).
3. **Recovery** (scripts/nightly_cutover_controller.py ``recover``) runs at the start of every armed apply, under the
   controller lock, before any new work. It decides from the ACTUAL state of each target, never from the marks alone:
   every mutation applied -> complete (write the rollback receipt, commit); some applied -> roll back the applied ones
   in reverse order; a target that is neither its before nor its after image -> ``conflict``: nothing is touched and
   both values are reported (AGENTS.md §0 rule 5). Recovery is idempotent: a second run finds nothing open.

AUTHORITY: writes only the controller's own receipt directory. No broker, no send.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional
from zoneinfo import ZoneInfo

NO_CONSUMER_REASON = "Library of scripts/nightly_cutover_controller.py (quota ledger, transaction records, recovery)."
QUOTA_SCHEMA = "NightlyCutoverQuota@v1"
TXN_SCHEMA = "NightlyCutoverTxn@v1"
ET = ZoneInfo("America/New_York")
STEPS = ("crontab", "registry", "contracts", "rollback_receipt")
MUTATION_STEPS = ("crontab", "registry", "contracts")
OPEN_STATUSES = frozenset({"open", "rolling_back", "completing"})
COUNTED = frozenset({"reserved", "applied"})
LOCK_NAME = "controller.lock"


class ControllerBusy(RuntimeError):
    """Another invocation of the controller holds the controller lock."""


def night_key(now: datetime) -> str:
    """The ET night (noon to noon America/New_York), named by its evening's date."""
    if now.tzinfo is None:
        raise ValueError("night_key needs a timezone-aware datetime")
    return (now.astimezone(ET) - timedelta(hours=12)).date().isoformat()


def write_json_durable(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(doc, indent=2, default=str) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


class ControllerLock:
    """Exclusive NON-blocking flock on ``<receipt_dir>/controller.lock``: one apply / rollback at a time. A second
    concurrent invocation gets ControllerBusy and changes nothing."""

    def __init__(self, rdir: Path) -> None:
        self.path = Path(rdir) / LOCK_NAME
        self.fd: Optional[int] = None

    def __enter__(self) -> "ControllerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise ControllerBusy(str(self.path))
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


# ── quota ledger ───────────────────────────────────────────────────────────────────────────────────────────────────

def quota_path(rdir: Path, night: str) -> Path:
    return Path(rdir) / "quota" / f"night-{night}.json"


def quota_read(rdir: Path, night: str) -> dict[str, Any]:
    """The night's quota document (empty when none). An unreadable ledger raises ValueError: the caller stops."""
    p = quota_path(rdir, night)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": QUOTA_SCHEMA, "night": night, "entries": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"quota_ledger_unreadable:{p}:{type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != QUOTA_SCHEMA or not isinstance(doc.get("entries"), list):
        raise ValueError(f"quota_ledger_unreadable:{p}:schema")
    return doc


def quota_used(doc: Mapping[str, Any]) -> int:
    return sum(1 for e in doc.get("entries") or [] if e.get("status") in COUNTED)


def quota_reserve(rdir: Path, night: str, *, lane: str, txn_id: str, cap: int, now: datetime
                  ) -> tuple[bool, int]:
    """Reserve one lane against tonight's cap. Caller holds the ControllerLock. Returns (reserved, used_before)."""
    doc = quota_read(rdir, night)
    used = quota_used(doc)
    if used >= cap:
        return False, used
    doc["entries"].append({"lane_id": lane, "txn_id": txn_id, "status": "reserved", "at": now.isoformat(),
                           "pid": os.getpid()})
    doc["cap_at_last_write"] = cap
    write_json_durable(quota_path(rdir, night), doc)
    return True, used


def quota_mark(rdir: Path, night: str, txn_id: str, status: str) -> None:
    doc = quota_read(rdir, night)
    for e in doc["entries"]:
        if e.get("txn_id") == txn_id:
            e["status"] = status
    write_json_durable(quota_path(rdir, night), doc)


def quota_orphans(rdir: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """(night, entry) for reservations still ``reserved`` whose transaction record never got written (a crash between
    the reservation and the record: nothing was mutated)."""
    qd = Path(rdir) / "quota"
    if not qd.is_dir():
        return
    for p in sorted(qd.glob("night-*.json")):
        night = p.stem[len("night-"):]
        for e in quota_read(rdir, night)["entries"]:
            if e.get("status") == "reserved" and not txn_path(rdir, str(e.get("txn_id"))).exists():
                yield night, e


# ── transaction records ────────────────────────────────────────────────────────────────────────────────────────────

def txn_dir(rdir: Path) -> Path:
    return Path(rdir) / "txn"


def txn_path(rdir: Path, txn_id: str) -> Path:
    return txn_dir(rdir) / f"{txn_id}.json"


def txn_write(rdir: Path, rec: dict[str, Any]) -> Path:
    p = txn_path(rdir, rec["txn_id"])
    write_json_durable(p, rec)
    return p


def txn_mark(rdir: Path, rec: dict[str, Any], step: Optional[str] = None, state: Optional[str] = None, *,
             status: Optional[str] = None, now: Optional[datetime] = None, **extra: Any) -> None:
    at = (now or datetime.now(timezone.utc)).isoformat()
    if step is not None:
        rec["steps"][step] = state
        rec.setdefault("history", []).append({"at": at, "step": step, "state": state})
    if status is not None:
        rec["status"] = status
        rec.setdefault("history", []).append({"at": at, "status": status})
    rec.update(extra)
    txn_write(rdir, rec)


def open_txns(rdir: Path) -> list[dict[str, Any]]:
    """Every transaction not committed / rolled back (oldest first). An unreadable record raises ValueError."""
    out = []
    d = txn_dir(rdir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"txn_record_unreadable:{p.name}:{type(exc).__name__}") from exc
        if rec.get("schema") == TXN_SCHEMA and rec.get("status") in OPEN_STATUSES | {"conflict"}:
            out.append(rec)
    return out


def new_txn(*, txn_id: str, lane: str, night: str, now: datetime, current_sha: str, wave: str,
            crontab: Mapping[str, Any], json_steps: Mapping[str, Any], backups: Mapping[str, Any],
            invocation: str) -> dict[str, Any]:
    return {"schema": TXN_SCHEMA, "txn_id": txn_id, "lane_id": lane, "night": night, "status": "open",
            "created_at": now.isoformat(), "current_sha": current_sha, "wave": wave, "invocation": invocation,
            "crontab": dict(crontab), "registry": json_steps["registry"], "contracts": json_steps.get("contracts"),
            "backups": dict(backups), "steps": {s: "pending" for s in STEPS},
            "rollback_receipt_path": None, "history": [], "outcome": None}
