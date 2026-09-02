"""Atomic file / state-store leases for multi-agent coordination (SOP Stage 4).

Host-local store under the common Git directory (not committed source, not
checkout-relative production state). Uses flock for atomicity.

Path claims are canonicalized before overlap comparison or persistence.
Persisted expiry uses schema-versioned UTC epoch seconds plus boot identity;
``time.monotonic()`` is never the sole cross-process / cross-reboot clock.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "AgentFileLease@v2"
SCHEMA_VERSION = 2
DEFAULT_TTL_S = 3600.0
HEARTBEAT_S = 60.0
MIN_TTL_S = 0.01
MAX_TTL_S = 7.0 * 86400.0
CLOCK_REGRESSION_SKEW_S = 300.0  # tolerate small backward jumps before stale

_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def coordination_root(git_common_dir: Path | str | None = None) -> Path:
    if git_common_dir is None:
        import subprocess

        raw = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], text=True).strip()
        git_common_dir = Path(raw).resolve()
    root = Path(git_common_dir) / "tradeai-agent-coordination"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_boot_id() -> str | None:
    """Return kernel boot id when available (Linux); else None."""
    try:
        if _BOOT_ID_PATH.is_file():
            val = _BOOT_ID_PATH.read_text(encoding="utf-8").strip()
            return val or None
    except OSError:
        return None
    return None


def utc_now() -> float:
    return time.time()


def validate_ttl(ttl_s: float) -> float:
    t = float(ttl_s)
    if t < MIN_TTL_S or t > MAX_TTL_S:
        raise ValueError(f"ttl_s out of bounds [{MIN_TTL_S}, {MAX_TTL_S}]: {ttl_s!r}")
    return t


def canonicalize_claim_path(p: str, *, repo_root: Path | str | None = None) -> str:
    """Convert a claim to a canonical repo-relative POSIX path.

    Normalizes harmless aliases (``./``, repeated ``/``, trailing ``/``).
    Rejects absolute paths, empty/root-only, ``..`` traversal, NUL/control
    characters, and paths that resolve outside ``repo_root`` when provided.
    """
    if p is None:
        raise ValueError("illegal claim path: None")
    if not isinstance(p, str):
        raise ValueError(f"illegal claim path type: {type(p).__name__}")
    if _CONTROL_RE.search(p):
        raise ValueError(f"illegal claim path (control/NUL): {p!r}")

    s = p.replace("\\", "/").strip()
    if not s or s in {".", "/"}:
        raise ValueError(f"illegal claim path (empty/root-only): {p!r}")
    if s.startswith("/"):
        raise ValueError(f"illegal claim path (absolute): {p!r}")

    # Strip repeated leading ./
    while s.startswith("./"):
        s = s[2:]
        if not s or s == ".":
            raise ValueError(f"illegal claim path (empty after ./): {p!r}")

    parts: list[str] = []
    for part in s.split("/"):
        if part == "" or part == ".":
            continue  # collapse // and .
        if part == "..":
            raise ValueError(f"illegal claim path (traversal): {p!r}")
        parts.append(part)
    if not parts:
        raise ValueError(f"illegal claim path (empty): {p!r}")

    canon = "/".join(parts)

    if repo_root is not None:
        root = Path(repo_root).resolve()
        # Pure lexical join + resolve; reject escape.
        resolved = (root / canon).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"illegal claim path (outside repo): {p!r}") from exc

    return canon


# Backward-compatible name used by older tests/callers.
def _norm_path(p: str, *, repo_root: Path | str | None = None) -> str:
    return canonicalize_claim_path(p, repo_root=repo_root)


def paths_overlap(a: str, b: str, *, repo_root: Path | str | None = None) -> bool:
    """True when claims collide (exact alias or parent/child directory)."""
    ca = canonicalize_claim_path(a, repo_root=repo_root)
    cb = canonicalize_claim_path(b, repo_root=repo_root)
    if ca == cb:
        return True
    return ca.startswith(cb + "/") or cb.startswith(ca + "/")


@dataclass
class Lease:
    lease_id: str
    session_id: str
    agent_id: str
    paths: list[str]
    stores: list[str]
    issued_at_utc: float
    expires_at_utc: float
    heartbeat_s: float
    boot_id: str | None = None
    schema_version: int = SCHEMA_VERSION
    deployment: bool = False
    production: bool = False
    # In-process only hints — never sole authority for durable expiry.
    issued_at_monotonic: float | None = None
    last_heartbeat_monotonic: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema"] = SCHEMA
        # Legacy aliases for readers that still look at issued_at/expires_at:
        # these are UTC epoch seconds under v2 (not monotonic).
        d["issued_at"] = self.issued_at_utc
        d["expires_at"] = self.expires_at_utc
        return d


class LeaseCoordinator:
    def __init__(
        self,
        root: Path | str | None = None,
        *,
        git_common_dir: Path | str | None = None,
        repo_root: Path | str | None = None,
        boot_id: str | None | object = ...,  # type: ignore[assignment]
        now_utc: Any = None,
    ):
        """``root`` is the coordination directory. If omitted, derive from git common dir.

        ``boot_id`` / ``now_utc`` are injectable for deterministic tests.
        Pass ``boot_id=None`` to simulate missing boot identity.
        """
        if root is not None:
            self.root = Path(root)
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            self.root = coordination_root(git_common_dir)
        self.leases_dir = self.root / "leases"
        self.leases_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / "coordinator.lock"
        self.repo_root = Path(repo_root).resolve() if repo_root is not None else None
        if boot_id is ...:
            self._boot_id = read_boot_id()
        else:
            self._boot_id = boot_id  # type: ignore[assignment]
        self._now_utc = now_utc or utc_now

    def _lock(self):
        import fcntl

        self._lock_fh = open(self.lock_path, "a+", encoding="utf-8")
        fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_EX)

    def _unlock(self):
        import fcntl

        try:
            fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
            self._lock_fh.close()
        except Exception:  # noqa: BLE001
            pass

    def _parse_lease(self, d: dict[str, Any]) -> Lease:
        schema_version = int(d.get("schema_version") or 1)
        if "issued_at_utc" in d:
            issued = float(d["issued_at_utc"])
            expires = float(d["expires_at_utc"])
        else:
            # v1 monotonic payloads — preserved for audit but treated as non-durable.
            issued = float(d.get("issued_at") or 0)
            expires = float(d.get("expires_at") or 0)
        return Lease(
            lease_id=d["lease_id"],
            session_id=d["session_id"],
            agent_id=d["agent_id"],
            paths=[canonicalize_claim_path(p, repo_root=self.repo_root) for p in (d.get("paths") or [])],
            stores=list(d.get("stores") or []),
            issued_at_utc=issued,
            expires_at_utc=expires,
            heartbeat_s=float(d.get("heartbeat_s") or HEARTBEAT_S),
            boot_id=d.get("boot_id"),
            schema_version=schema_version,
            deployment=bool(d.get("deployment")),
            production=bool(d.get("production")),
            issued_at_monotonic=d.get("issued_at_monotonic"),
            last_heartbeat_monotonic=d.get("last_heartbeat_monotonic"),
        )

    def _stale_reason(self, lease: Lease, *, now: float) -> str | None:
        """Return recovery event code if lease must not be treated as active."""
        # v1 monotonic-only records cannot survive process/reboot boundaries.
        if lease.schema_version < SCHEMA_VERSION:
            return "ABANDONED_SCHEMA_UPGRADE"
        if lease.expires_at_utc < lease.issued_at_utc:
            return "ABANDONED_CLOCK_REGRESSION"
        if now + CLOCK_REGRESSION_SKEW_S < lease.issued_at_utc:
            return "ABANDONED_CLOCK_REGRESSION"
        if lease.expires_at_utc < now:
            return "ABANDONED_TTL_EXPIRED"
        # Boot identity: when both sides known and disagree → reboot/stale.
        if self._boot_id and lease.boot_id and lease.boot_id != self._boot_id:
            return "ABANDONED_BOOT_ID_CHANGED"
        # Persisted without boot_id while coordinator has one: pre-reboot/unknown.
        if self._boot_id and not lease.boot_id:
            return "ABANDONED_BOOT_ID_MISSING"
        return None

    def _read_all(self, *, include_expired: bool = False) -> list[Lease]:
        now = float(self._now_utc())
        out: list[Lease] = []
        for p in self.leases_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                lease = self._parse_lease(d)
                if not include_expired and self._stale_reason(lease, now=now):
                    continue
                out.append(lease)
            except Exception:  # noqa: BLE001
                continue
        return out

    def _audit_move(self, src: Path, d: dict[str, Any], *, event: str, dest_dir: Path) -> dict[str, Any]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        d = dict(d)
        d["recovered_at_utc"] = float(self._now_utc())
        d["recovery_event"] = event
        d["recovery_boot_id"] = self._boot_id
        dest = dest_dir / f"{d.get('lease_id')}.{int(d['recovered_at_utc'])}.json"
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, dest)
        src.unlink()
        return d

    def recover_abandoned(self) -> list[dict[str, Any]]:
        """Move stale lease files to audit/abandoned without deleting peer sessions."""
        self._lock()
        try:
            now = float(self._now_utc())
            audit = self.root / "abandoned"
            recovered: list[dict[str, Any]] = []
            for p in list(self.leases_dir.glob("*.json")):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    lease = self._parse_lease(d)
                    reason = self._stale_reason(lease, now=now)
                    if not reason:
                        continue
                    recovered.append(self._audit_move(p, d, event=reason, dest_dir=audit))
                except Exception:  # noqa: BLE001
                    continue
            return recovered
        finally:
            self._unlock()

    def list_active(self) -> list[dict[str, Any]]:
        self._lock()
        try:
            return [lease.to_dict() for lease in self._read_all()]
        finally:
            self._unlock()

    def acquire(
        self,
        *,
        session_id: str,
        agent_id: str,
        paths: Iterable[str],
        stores: Iterable[str] | None = None,
        ttl_s: float = DEFAULT_TTL_S,
        deployment: bool = False,
        production: bool = False,
    ) -> Lease:
        ttl = validate_ttl(ttl_s)
        # Normalize under the lock so validation + acquisition are atomic w.r.t peers.
        self._lock()
        try:
            norm_paths = [canonicalize_claim_path(p, repo_root=self.repo_root) for p in paths]
            if not norm_paths and not stores:
                raise ValueError("acquire requires at least one path or store claim")
            stores_l = [str(s) for s in (stores or [])]
            # Persist only canonical claims.
            active = self._read_all()
            if deployment or production:
                for a in active:
                    if a.deployment or a.production:
                        raise RuntimeError("refusing simultaneous deployment/production lease")
            for a in active:
                for p in norm_paths:
                    for q in a.paths:
                        if paths_overlap(p, q, repo_root=self.repo_root):
                            raise RuntimeError(f"overlap with lease {a.lease_id} path {q}")
                for s in stores_l:
                    if s in a.stores:
                        raise RuntimeError(f"overlap with lease {a.lease_id} store {s}")
            now_utc = float(self._now_utc())
            mono = time.monotonic()
            lease = Lease(
                lease_id=str(uuid.uuid4()),
                session_id=session_id,
                agent_id=agent_id,
                paths=norm_paths,
                stores=stores_l,
                issued_at_utc=now_utc,
                expires_at_utc=now_utc + ttl,
                heartbeat_s=HEARTBEAT_S,
                boot_id=self._boot_id,
                schema_version=SCHEMA_VERSION,
                deployment=deployment,
                production=production,
                issued_at_monotonic=mono,
                last_heartbeat_monotonic=mono,
            )
            path = self.leases_dir / f"{lease.lease_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(lease.to_dict(), indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
            return lease
        finally:
            self._unlock()

    def heartbeat(self, lease_id: str, *, ttl_s: float = DEFAULT_TTL_S) -> Lease:
        ttl = validate_ttl(ttl_s)
        self._lock()
        try:
            path = self.leases_dir / f"{lease_id}.json"
            if not path.is_file():
                raise FileNotFoundError(lease_id)
            d = json.loads(path.read_text(encoding="utf-8"))
            lease = self._parse_lease(d)
            now = float(self._now_utc())
            reason = self._stale_reason(lease, now=now)
            if reason:
                raise RuntimeError(f"cannot heartbeat stale lease: {reason}")
            # Extend using UTC; record monotonic only as in-process hint.
            d["expires_at_utc"] = now + ttl
            d["expires_at"] = d["expires_at_utc"]
            d["last_heartbeat_monotonic"] = time.monotonic()
            d["boot_id"] = self._boot_id
            d["schema_version"] = SCHEMA_VERSION
            d["schema"] = SCHEMA
            # Re-canonicalize stored paths on heartbeat.
            d["paths"] = [canonicalize_claim_path(p, repo_root=self.repo_root) for p in lease.paths]
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
            return self._parse_lease(d)
        finally:
            self._unlock()

    def release(self, lease_id: str, *, session_id: Optional[str] = None) -> bool:
        self._lock()
        try:
            path = self.leases_dir / f"{lease_id}.json"
            if not path.is_file():
                return False
            d = json.loads(path.read_text(encoding="utf-8"))
            if session_id is not None and d.get("session_id") != session_id:
                raise RuntimeError("session_id mismatch on release")
            # Audit rename — never silently delete another session's record.
            audit = self.root / "released"
            self._audit_move(path, d, event="RELEASED", dest_dir=audit)
            return True
        finally:
            self._unlock()
