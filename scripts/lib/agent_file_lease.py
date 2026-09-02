"""Atomic file / state-store leases for multi-agent coordination (SOP Stage 4).

Host-local store under the common Git directory (not committed source, not
checkout-relative production state). Uses flock for atomicity.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "AgentFileLease@v1"
DEFAULT_TTL_S = 3600
HEARTBEAT_S = 60


def coordination_root(git_common_dir: Path | str | None = None) -> Path:
    if git_common_dir is None:
        import subprocess
        raw = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], text=True).strip()
        git_common_dir = Path(raw).resolve()
    root = Path(git_common_dir) / "tradeai-agent-coordination"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _norm_path(p: str) -> str:
    s = str(p or "").replace("\\", "/").strip()
    if not s or s.startswith("/") or ".." in s.split("/"):
        raise ValueError(f"illegal claim path: {p!r}")
    return s


def paths_overlap(a: str, b: str) -> bool:
    a, b = _norm_path(a), _norm_path(b)
    if a == b:
        return True
    return a.startswith(b + "/") or b.startswith(a + "/")


@dataclass
class Lease:
    lease_id: str
    session_id: str
    agent_id: str
    paths: list[str]
    stores: list[str]
    issued_at: float
    expires_at: float
    heartbeat_s: float
    deployment: bool = False
    production: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema"] = SCHEMA
        return d


class LeaseCoordinator:
    def __init__(self, root: Path | str | None = None, *, git_common_dir: Path | str | None = None):
        """``root`` is the coordination directory. If omitted, derive from git common dir."""
        if root is not None:
            self.root = Path(root)
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            self.root = coordination_root(git_common_dir)
        self.leases_dir = self.root / "leases"
        self.leases_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / "coordinator.lock"

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

    def _read_all(self) -> list[Lease]:
        now = time.monotonic()
        out: list[Lease] = []
        for p in self.leases_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                lease = Lease(
                    lease_id=d["lease_id"],
                    session_id=d["session_id"],
                    agent_id=d["agent_id"],
                    paths=list(d.get("paths") or []),
                    stores=list(d.get("stores") or []),
                    issued_at=float(d["issued_at"]),
                    expires_at=float(d["expires_at"]),
                    heartbeat_s=float(d.get("heartbeat_s") or HEARTBEAT_S),
                    deployment=bool(d.get("deployment")),
                    production=bool(d.get("production")),
                )
                if lease.expires_at < now:
                    # abandoned — leave file for audit; skip as active
                    continue
                out.append(lease)
            except Exception:  # noqa: BLE001
                continue
        return out

    def list_active(self) -> list[dict[str, Any]]:
        self._lock()
        try:
            return [l.to_dict() for l in self._read_all()]
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
        norm_paths = [_norm_path(p) for p in paths]
        stores_l = [str(s) for s in (stores or [])]
        self._lock()
        try:
            active = self._read_all()
            if deployment or production:
                for a in active:
                    if a.deployment or a.production:
                        raise RuntimeError(
                            "refusing simultaneous deployment/production lease")
            for a in active:
                for p in norm_paths:
                    for q in a.paths:
                        if paths_overlap(p, q):
                            raise RuntimeError(
                                f"overlap with lease {a.lease_id} path {q}")
                for s in stores_l:
                    if s in a.stores:
                        raise RuntimeError(
                            f"overlap with lease {a.lease_id} store {s}")
            now = time.monotonic()
            lease = Lease(
                lease_id=str(uuid.uuid4()),
                session_id=session_id,
                agent_id=agent_id,
                paths=norm_paths,
                stores=stores_l,
                issued_at=now,
                expires_at=now + float(ttl_s),
                heartbeat_s=HEARTBEAT_S,
                deployment=deployment,
                production=production,
            )
            path = self.leases_dir / f"{lease.lease_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(lease.to_dict(), indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
            return lease
        finally:
            self._unlock()

    def heartbeat(self, lease_id: str, *, ttl_s: float = DEFAULT_TTL_S) -> Lease:
        self._lock()
        try:
            path = self.leases_dir / f"{lease_id}.json"
            if not path.is_file():
                raise FileNotFoundError(lease_id)
            d = json.loads(path.read_text(encoding="utf-8"))
            now = time.monotonic()
            d["expires_at"] = now + float(ttl_s)
            path.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
            return Lease(
                lease_id=d["lease_id"], session_id=d["session_id"],
                agent_id=d["agent_id"], paths=list(d["paths"]),
                stores=list(d.get("stores") or []),
                issued_at=float(d["issued_at"]),
                expires_at=float(d["expires_at"]),
                heartbeat_s=float(d.get("heartbeat_s") or HEARTBEAT_S),
                deployment=bool(d.get("deployment")),
                production=bool(d.get("production")),
            )
        finally:
            self._unlock()

    def release(self, lease_id: str, *, session_id: Optional[str] = None) -> bool:
        self._lock()
        try:
            path = self.leases_dir / f"{lease_id}.json"
            if not path.is_file():
                return False
            if session_id is not None:
                d = json.loads(path.read_text(encoding="utf-8"))
                if d.get("session_id") != session_id:
                    raise RuntimeError("session_id mismatch on release")
            # audit: rename aside rather than delete peer records
            audit = self.root / "released"
            audit.mkdir(parents=True, exist_ok=True)
            os.replace(path, audit / f"{lease_id}.{int(time.time())}.json")
            return True
        finally:
            self._unlock()
