"""Atomic IPC contracts for the dedicated Moomoo L2 gateway.

The gateway service is the only OpenD owner. HTTP handlers and cron jobs consume a
bounded JSON snapshot through this module and never instantiate a quote context.
All files are mode 0600 and published with fsync + atomic rename.

Read plane only: no order, trade unlock, credential, 2FA, or database-write path.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SNAPSHOT_CONTRACT = "moomoo-l2-gateway-snapshot-v1"
STATE_CONTRACT = "moomoo-l2-gateway-state-v1"
INTENT_CONTRACT = "moomoo-l2-gateway-intent-v1"
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,19}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def default_runtime_dir() -> Path:
    env = os.environ.get("TRADEAI_RUNTIME_DIR", "").strip()
    return expand_path(env or "~/.tradeai/runtime")


def default_snapshot_path() -> Path:
    env = os.environ.get("MOOMOO_L2_GATEWAY_SNAPSHOT", "").strip()
    return expand_path(env or default_runtime_dir() / "moomoo_l2_gateway_snapshot.json")


def default_state_path() -> Path:
    env = os.environ.get("MOOMOO_L2_GATEWAY_STATE", "").strip()
    return expand_path(env or default_runtime_dir() / "moomoo_l2_gateway_state.json")


def default_lock_path() -> Path:
    env = os.environ.get("MOOMOO_L2_GATEWAY_LOCK", "").strip()
    return expand_path(env or default_runtime_dir() / "moomoo_l2_gateway.lock")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: str | Path, payload: Mapping[str, Any], *, mode: int = 0o600) -> None:
    """Write JSON without exposing a partial snapshot to concurrent readers."""
    target = expand_path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, mode)
        _fsync_directory(target.parent)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def read_json(path: str | Path) -> Optional[dict[str, Any]]:
    target = expand_path(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


class OwnerLockError(RuntimeError):
    """A second process attempted to become the OpenD owner."""


class OwnerLock:
    """Non-blocking advisory lock proving one service-level owner."""

    def __init__(self, path: str | Path):
        self.path = expand_path(path)
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, metadata: Optional[Mapping[str, Any]] = None) -> "OwnerLock":
        if self._fd is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                detail = read_json(self.path) or {}
                raise OwnerLockError(f"Moomoo L2 owner already active: {detail}") from exc
            raise
        owner = {
            "contract": "moomoo-l2-owner-lock-v1",
            "pid": os.getpid(),
            "acquired_at": utc_now_iso(),
            **dict(metadata or {}),
        }
        encoded = (json.dumps(owner, sort_keys=True, separators=(",", ":")) + "\n").encode()
        os.ftruncate(fd, 0)
        os.write(fd, encoded)
        os.fsync(fd)
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "OwnerLock":
        return self.acquire()

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


@dataclass(frozen=True)
class SnapshotRead:
    payload: Optional[dict[str, Any]]
    fresh: bool
    reason: str
    age_seconds: Optional[float]


class SnapshotPublisher:
    def __init__(self, path: str | Path):
        self.path = expand_path(path)
        self.generation = 0

    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.generation += 1
        body = {
            **dict(payload),
            "contract": SNAPSHOT_CONTRACT,
            "generation": self.generation,
            "published_at": utc_now_iso(),
        }
        atomic_write_json(self.path, body)
        return body


class SnapshotClient:
    """Read and validate gateway snapshots without touching OpenD."""

    def __init__(self, path: str | Path | None = None, *, max_age_seconds: float = 5.0):
        self.path = expand_path(path or default_snapshot_path())
        self.max_age_seconds = float(max_age_seconds)

    def read(self, *, now: Optional[datetime] = None) -> SnapshotRead:
        payload = read_json(self.path)
        if payload is None:
            return SnapshotRead(None, False, "SNAPSHOT_MISSING_OR_INVALID", None)
        if payload.get("contract") != SNAPSHOT_CONTRACT:
            return SnapshotRead(payload, False, "CONTRACT_MISMATCH", None)
        heartbeat = parse_iso(payload.get("heartbeat_at") or payload.get("published_at"))
        if heartbeat is None:
            return SnapshotRead(payload, False, "HEARTBEAT_MISSING_OR_INVALID", None)
        current = now or datetime.now(timezone.utc)
        age = (current - heartbeat.astimezone(timezone.utc)).total_seconds()
        if age < -1.0:
            return SnapshotRead(payload, False, "HEARTBEAT_FUTURE_CLOCK_SKEW", age)
        if age > self.max_age_seconds:
            return SnapshotRead(payload, False, "SNAPSHOT_STALE", age)
        if not bool((payload.get("owner") or {}).get("exclusive_lock_held")):
            return SnapshotRead(payload, False, "OWNER_LOCK_UNPROVEN", max(0.0, age))
        if payload.get("service_state") not in (None, "RUNNING"):
            return SnapshotRead(payload, False, "SERVICE_NOT_RUNNING", max(0.0, age))
        return SnapshotRead(payload, True, "OK", max(0.0, age))


class GatewayStateStore:
    def __init__(self, path: str | Path | None = None):
        self.path = expand_path(path or default_state_path())

    def load(self) -> dict[str, Any]:
        payload = read_json(self.path) or {}
        return payload if payload.get("contract") == STATE_CONTRACT else {}

    def save(self, payload: Mapping[str, Any]) -> None:
        atomic_write_json(
            self.path,
            {**dict(payload), "contract": STATE_CONTRACT, "saved_at": utc_now_iso()},
        )


def normalize_symbol(value: Any) -> Optional[str]:
    symbol = str(value or "").strip().upper()
    if symbol.startswith("US."):
        symbol = symbol[3:]
    return symbol if _SYMBOL.fullmatch(symbol) else None


def _legacy_armed(payload: Mapping[str, Any], *, now_epoch: float) -> dict[str, dict[str, Any]]:
    raw = payload.get("armed") if isinstance(payload, Mapping) else None
    result: dict[str, dict[str, Any]] = {}
    if isinstance(raw, Mapping):
        iterator: Iterable[tuple[Any, Any]] = raw.items()
    elif isinstance(raw, list):
        iterator = ((item.get("symbol"), item) for item in raw if isinstance(item, Mapping))
    else:
        return result
    for raw_symbol, raw_detail in iterator:
        symbol = normalize_symbol(raw_symbol)
        if symbol is None:
            continue
        detail = dict(raw_detail) if isinstance(raw_detail, Mapping) else {}
        try:
            expires_at = float(detail.get("expires_at")) if detail.get("expires_at") is not None else None
        except (TypeError, ValueError):
            expires_at = None
        if expires_at is not None and expires_at <= now_epoch:
            continue
        result[symbol] = {
            "symbol": symbol,
            "reason": str(detail.get("reason") or "legacy_arm_intent"),
            "priority": str(detail.get("priority") or "P2").upper(),
            "require_tape": bool(detail.get("require_tape", False)),
            "is_fire": bool(detail.get("is_fire", False)),
            "armed_at": detail.get("armed_at"),
            "expires_at": expires_at,
            "source": str(detail.get("source") or "legacy_arm_state"),
        }
    return result


def load_intent_file(path: str | Path, *, now_epoch: Optional[float] = None) -> dict[str, dict[str, Any]]:
    payload = read_json(path) or {}
    current = float(now_epoch if now_epoch is not None else time.time())
    if payload.get("contract") == INTENT_CONTRACT:
        desired = payload.get("desired")
        return _legacy_armed({"armed": desired}, now_epoch=current)
    return _legacy_armed(payload, now_epoch=current)


def merge_intents(
    paths: Iterable[str | Path], *, now_epoch: Optional[float] = None
) -> dict[str, dict[str, Any]]:
    """Merge intent files deterministically; higher-priority facts win."""
    current = float(now_epoch if now_epoch is not None else time.time())
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        for symbol, detail in load_intent_file(path, now_epoch=current).items():
            old = merged.get(symbol)
            if old is None or priority_rank.get(detail.get("priority", "P2"), 2) < priority_rank.get(
                old.get("priority", "P2"), 2
            ):
                merged[symbol] = detail
            elif old is not None:
                old["require_tape"] = bool(old.get("require_tape") or detail.get("require_tape"))
                old["is_fire"] = bool(old.get("is_fire") or detail.get("is_fire"))
                expiries = [x for x in (old.get("expires_at"), detail.get("expires_at")) if x is not None]
                old["expires_at"] = max(expiries) if expiries else None
    return {key: merged[key] for key in sorted(merged)}
