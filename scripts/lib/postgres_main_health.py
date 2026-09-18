"""postgres_main_health.py — disk + main-cluster liveness helpers for health_agent.

Pure functions (no broker, no writes). Used to:
  * classify connect failures as postgres_main_down vs slot exhaustion
  * evaluate disk free% / free_GB floors (inclusive thresholds)
  * decide whether an allowlisted restart is safe

Incident 2026-09-18: ENOSPC → WAL PANIC → postgresql@17-main down for hours while
disk hygiene later freed ~41GB but nobody restarted the cluster.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


DEFAULT_DISK_CFG: dict[str, Any] = {
    "mountpoint": "/",
    # Inclusive free floors — page earlier than the old used>90% gate.
    "warn_free_pct": 15.0,
    "crit_free_pct": 10.0,
    "warn_free_gb": 40.0,
    "crit_free_gb": 15.0,
}

# Restart is only attempted when free space can absorb WAL. Absolute GB is the
# binding floor; % is a low backstop so a tiny filesystem cannot pass on GB alone.
# (On a ~468G disk, 10% ≈ 47G — using that as a hard AND blocked a healthy 46G
# free restart after the 2026-09-18 hygiene reclaim.)
DEFAULT_RESTART_CFG: dict[str, Any] = {
    "min_free_pct": 5.0,
    "min_free_gb": 15.0,
    "unit": "postgresql@17-main",
    "cooldown_minutes": 60,
}


@dataclass(frozen=True)
class DiskVerdict:
    mountpoint: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_pct: float
    free_gb: float
    severity: Optional[str]  # None | "warning" | "critical"
    finding_type: Optional[str]  # None | disk_low | disk_critical
    message: str


def evaluate_disk_usage(
    *,
    total_bytes: int,
    used_bytes: int,
    free_bytes: int,
    cfg: Mapping[str, Any] | None = None,
) -> DiskVerdict:
    """Return a disk verdict using inclusive free% and free_GB floors.

    Critical if free_pct <= crit_free_pct OR free_gb <= crit_free_gb.
    Warning if free_pct <= warn_free_pct OR free_gb <= warn_free_gb.
    """
    c = {**DEFAULT_DISK_CFG, **(cfg or {})}
    mp = str(c.get("mountpoint") or "/")
    total = max(int(total_bytes), 1)
    free = max(int(free_bytes), 0)
    used = int(used_bytes) if used_bytes is not None else max(0, total - free)
    free_pct = (free / total) * 100.0
    free_gb = free / (1024 ** 3)
    warn_pct = float(c.get("warn_free_pct", DEFAULT_DISK_CFG["warn_free_pct"]))
    crit_pct = float(c.get("crit_free_pct", DEFAULT_DISK_CFG["crit_free_pct"]))
    warn_gb = float(c.get("warn_free_gb", DEFAULT_DISK_CFG["warn_free_gb"]))
    crit_gb = float(c.get("crit_free_gb", DEFAULT_DISK_CFG["crit_free_gb"]))

    if free_pct <= crit_pct or free_gb <= crit_gb:
        return DiskVerdict(
            mountpoint=mp,
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            free_pct=round(free_pct, 2),
            free_gb=round(free_gb, 2),
            severity="critical",
            finding_type="disk_critical",
            message=(
                f"Disk {mp}: {free_gb:.1f}GB free ({free_pct:.1f}%) — at/below critical "
                f"floor ({crit_gb:g}GB / {crit_pct:g}% free)"
            ),
        )
    if free_pct <= warn_pct or free_gb <= warn_gb:
        return DiskVerdict(
            mountpoint=mp,
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            free_pct=round(free_pct, 2),
            free_gb=round(free_gb, 2),
            severity="warning",
            finding_type="disk_low",
            message=(
                f"Disk {mp}: {free_gb:.1f}GB free ({free_pct:.1f}%) — at/below warn "
                f"floor ({warn_gb:g}GB / {warn_pct:g}% free)"
            ),
        )
    return DiskVerdict(
        mountpoint=mp,
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        free_pct=round(free_pct, 2),
        free_gb=round(free_gb, 2),
        severity=None,
        finding_type=None,
        message=f"Disk {mp}: {free_gb:.1f}GB free ({free_pct:.1f}%) — ok",
    )


def classify_pg_connect_error(exc: BaseException | str) -> str:
    """Classify a psycopg2 connect failure.

    Returns one of:
      * ``slots_exhausted`` — connection slot FATAL (existing finding)
      * ``postgres_main_down`` — refused / unreachable / not running
      * ``auth_failed`` — credentials / role
      * ``other`` — unexpected; still surface as down-ish for operators
    """
    msg = str(exc or "").lower()
    if "connection slot" in msg or "too many connections" in msg:
        return "slots_exhausted"
    if any(
        t in msg
        for t in (
            "password authentication failed",
            "authenticity",
            'role "',
            "no password supplied",
        )
    ):
        return "auth_failed"
    if any(
        t in msg
        for t in (
            "connection refused",
            "could not connect",
            "failed to connect",
            "server closed the connection",
            "connection timed out",
            "timeout expired",
            "is the server running",
            "cluster is not running",
            "no route to host",
            "network is unreachable",
            "no such file or directory",  # missing unix socket under ENOSPC crash
        )
    ):
        return "postgres_main_down"
    # Default: treat hard connect failure as down so we never silently return.
    if "connect" in msg or "connection" in msg:
        return "postgres_main_down"
    return "other"


def restart_safe(
    *,
    free_pct: float,
    free_gb: float,
    cfg: Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    """Whether an allowlisted postgres restart may run given current free space."""
    c = {**DEFAULT_RESTART_CFG, **(cfg or {})}
    min_pct = float(c.get("min_free_pct", DEFAULT_RESTART_CFG["min_free_pct"]))
    min_gb = float(c.get("min_free_gb", DEFAULT_RESTART_CFG["min_free_gb"]))
    if free_pct < min_pct or free_gb < min_gb:
        return (
            False,
            f"disk below restart floor ({free_gb:.1f}GB / {free_pct:.1f}% free; "
            f"need ≥{min_gb:g}GB and ≥{min_pct:g}%) — page disk_critical, do not restart",
        )
    return True, "disk above restart floor"


def unit_inactive_statuses() -> frozenset[str]:
    return frozenset({"inactive", "failed", "deactivating", "not-found", "unknown", "dead"})
