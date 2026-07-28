"""Append-only, hash-chained shadow journal for Active Trader motion evidence.

The journal stores local observations and derived shadow snapshots only. It performs no
network I/O and has no broker or order authority. A broken hash chain fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

CONTRACT = "active-trader-motion-journal-v1"
ALLOWED_KINDS = frozenset({
    "candidate_observation",
    "position_observation",
    "motion_snapshot",
    "operator_annotation",
})

_LOCK = threading.Lock()


class JournalIntegrityError(RuntimeError):
    """Raised when an existing journal cannot be verified."""


@dataclass(frozen=True)
class JournalVerification:
    ok: bool
    record_count: int
    last_sequence: int
    last_hash: Optional[str]
    error: Optional[str] = None
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_record(record_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(record_without_hash).encode("utf-8")).hexdigest()


def default_journal_path() -> Path:
    env = os.environ.get("ACTIVE_TRADER_MOTION_JOURNAL", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "active_trader" / "motion_shadow.jsonl"


class MotionJournal:
    def __init__(self, path: str | Path | None = None, *, fsync: bool = False) -> None:
        self.path = Path(path).expanduser() if path else default_journal_path()
        self.fsync = bool(fsync)

    def _raw_records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise JournalIntegrityError(f"invalid JSON at line {line_no}: {exc}") from exc
            if not isinstance(row, dict):
                raise JournalIntegrityError(f"journal line {line_no} is not an object")
            rows.append(row)
        return rows

    def verify(self) -> JournalVerification:
        try:
            previous_hash: Optional[str] = None
            expected_sequence = 1
            rows = self._raw_records()
            for row in rows:
                if row.get("contract") != CONTRACT:
                    raise JournalIntegrityError("journal contract mismatch")
                if int(row.get("sequence") or 0) != expected_sequence:
                    raise JournalIntegrityError(
                        f"sequence mismatch: expected {expected_sequence}, got {row.get('sequence')}"
                    )
                if row.get("previous_hash") != previous_hash:
                    raise JournalIntegrityError(f"previous_hash mismatch at sequence {expected_sequence}")
                supplied_hash = str(row.get("record_hash") or "")
                unsigned = {k: v for k, v in row.items() if k != "record_hash"}
                if not supplied_hash or supplied_hash != _hash_record(unsigned):
                    raise JournalIntegrityError(f"record_hash mismatch at sequence {expected_sequence}")
                previous_hash = supplied_hash
                expected_sequence += 1
            return JournalVerification(
                ok=True,
                record_count=len(rows),
                last_sequence=len(rows),
                last_hash=previous_hash,
            )
        except Exception as exc:
            return JournalVerification(
                ok=False,
                record_count=0,
                last_sequence=0,
                last_hash=None,
                error=str(exc),
            )

    def append(
        self,
        kind: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: float | None = None,
    ) -> dict[str, Any]:
        kind = str(kind or "").strip()
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"unsupported journal kind: {kind}")
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")

        with _LOCK:
            verification = self.verify()
            if not verification.ok:
                raise JournalIntegrityError(verification.error or "journal verification failed")
            record = {
                "contract": CONTRACT,
                "sequence": verification.last_sequence + 1,
                "kind": kind,
                "recorded_at": float(time.time() if recorded_at is None else recorded_at),
                "payload": dict(payload),
                "previous_hash": verification.last_hash,
            }
            record["record_hash"] = _hash_record(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(_canonical(record) + "\n")
                fh.flush()
                if self.fsync:
                    os.fsync(fh.fileno())
            return dict(record)

    def records(
        self,
        *,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        verification = self.verify()
        if not verification.ok:
            raise JournalIntegrityError(verification.error or "journal verification failed")
        rows = self._raw_records()
        if kind is not None:
            rows = [row for row in rows if row.get("kind") == kind]
        if limit is not None:
            rows = rows[-max(0, int(limit)):]
        return [dict(row) for row in rows]

    def latest(self, kind: str | None = None) -> Optional[dict[str, Any]]:
        rows = self.records(kind=kind, limit=1)
        return rows[0] if rows else None

    def payloads(self, kind: str) -> Iterable[dict[str, Any]]:
        for row in self.records(kind=kind):
            payload = row.get("payload")
            if isinstance(payload, Mapping):
                yield dict(payload)
