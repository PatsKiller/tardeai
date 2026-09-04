#!/usr/bin/env python3
"""Report which governed state stores have forked between producer and served roots.

WHY THIS EXISTS
---------------
Producers run under cron with ``cd $PROJ`` and resolve state as
``root/"data"/"portfolios"/"state"``. Every deployed release symlinks that
directory at ``GOOD_PERSISTENT_ROOT``. A producer that resolves its own path
from the checkout therefore writes a tree the server never reads, reports
success, and the served numbers quietly stop moving.

Measured on 2026-09-03 against the live tree: **57 of 88** state files had
forked, many by more than a week, while every surface that read them rendered
as though nothing was wrong. ``portfolio_stops.save_risk_state`` fixed one file
in August and predicted the recurrence; ``canonical_observation.write_state_json``
fixed three more. The remaining forks are invisible because nothing reports them.

``persistent_state_root.report_authoritative_divergence`` already knows how to
compare two copies byte-for-byte. Until now it had **no caller outside two
docstrings** — the detector existed and nothing asked it anything. This module
is the missing consumer, and it is deliberately a *report*, never a repair.

AUTHORITY
---------
READ_ONLY_ADVISORY. This module stats and hashes files. It never writes, moves,
merges, deletes or reconciles a store, and it performs no financial calculation.
AGENTS.md 9.4 / WAVE G1: divergent authoritative copies are reported and
escalated, never auto-merged — detection must not become resolution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "StateRootDivergenceReport@v1"
CALCULATION_VERSION = "1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Logical state directory every portfolio producer and the served API share.
STATE_REL = "data/portfolios/state"

#: Divergence verdicts.
IDENTICAL = "IDENTICAL"
SAME_INODE = "SAME_INODE"
DIVERGENT = "DIVERGENT"
PRODUCER_ONLY = "PRODUCER_ONLY"
SERVED_ONLY = "SERVED_ONLY"
ABSENT = "ABSENT"

#: Which side is ahead. The direction matters: a producer-ahead fork means the
#: server is serving stale truth; a served-ahead fork means the running service
#: is the only writer and the checkout copy is a fossil.
PRODUCER_AHEAD = "PRODUCER_AHEAD"
SERVED_AHEAD = "SERVED_AHEAD"
NEITHER = "NEITHER"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()


def producer_checkout_root() -> Path:
    """The tree cron actually runs producers in.

    NOT this process's own root. A deployed release symlinks
    ``data/portfolios/state`` at the persistent root, so a release comparing
    ``Path(__file__)``-relative state against the served root would compare a
    directory with itself and report CONVERGED while 59 stores were forked.
    ``DEFAULT_LEGACY_SOURCE`` is the canonical producer checkout that
    ``persistent_state_root`` already names for exactly this reason.
    """
    from lib.persistent_state_root import DEFAULT_LEGACY_SOURCE  # noqa: PLC0415

    return Path(DEFAULT_LEGACY_SOURCE)


def _roots(checkout_root: Path | str | None = None) -> tuple[Path, Path]:
    """Return ``(producer_root, served_root)`` for the shared state directory.

    Resolved through the canonical helpers rather than re-deriving the paths, so
    this report cannot disagree with the writers about where a store lives.
    """
    from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415

    checkout = Path(checkout_root) if checkout_root else producer_checkout_root()
    return checkout / STATE_REL, Path(good_persistent_root()) / STATE_REL


def _stat(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "mtime_utc": None, "bytes": None, "inode": None}
    st = path.stat()
    return {
        "exists": True,
        "mtime_utc": _iso(st.st_mtime),
        "mtime_epoch": st.st_mtime,
        "bytes": st.st_size,
        "inode": st.st_ino,
    }


def compare_store(
    filename: str,
    *,
    checkout_root: Path | str | None = None,
    now: datetime | None = None,
    with_hashes: bool = False,
) -> dict[str, Any]:
    """Compare one state file across the producer and served roots.

    ``with_hashes`` is opt-in because hashing every store on every request would
    make a status endpoint expensive; mtime and inode already answer "did these
    fork" for the operational question, and the byte-exact answer is available
    on demand.
    """
    now = now or _now()
    prod_dir, served_dir = _roots(checkout_root)
    prod, served = prod_dir / filename, served_dir / filename
    p, s = _stat(prod), _stat(served)

    if not p["exists"] and not s["exists"]:
        verdict, direction = ABSENT, NEITHER
    elif p["exists"] and not s["exists"]:
        verdict, direction = PRODUCER_ONLY, PRODUCER_AHEAD
    elif s["exists"] and not p["exists"]:
        verdict, direction = SERVED_ONLY, SERVED_AHEAD
    elif p["inode"] == s["inode"]:
        verdict, direction = SAME_INODE, NEITHER
    elif p["mtime_epoch"] == s["mtime_epoch"] and p["bytes"] == s["bytes"]:
        verdict, direction = IDENTICAL, NEITHER
    else:
        verdict = DIVERGENT
        direction = PRODUCER_AHEAD if p["mtime_epoch"] > s["mtime_epoch"] else SERVED_AHEAD

    row: dict[str, Any] = {
        "store": filename,
        "producer_path": str(prod),
        "served_path": str(served),
        "producer": {k: v for k, v in p.items() if k != "mtime_epoch"},
        "served": {k: v for k, v in s.items() if k != "mtime_epoch"},
        "verdict": verdict,
        "direction": direction,
        "skew_seconds": None,
        "served_age_hours": None,
        "auto_remediate": False,
    }
    if p["exists"] and s["exists"]:
        row["skew_seconds"] = round(abs(p["mtime_epoch"] - s["mtime_epoch"]), 1)
    if s["exists"]:
        row["served_age_hours"] = round((now.timestamp() - s["mtime_epoch"]) / 3600.0, 2)

    if with_hashes:
        from lib.persistent_state_root import report_authoritative_divergence  # noqa: PLC0415

        rep = report_authoritative_divergence(prod, served, label=f"state:{filename}")
        row["byte_identical"] = rep["identical"]
        row["byte_diverged"] = rep["diverged"]
        row["hashes"] = {c["path"]: (c["sha256"] or "")[:16] or None for c in rep["copies"]}
        # mtime can differ while bytes match (a rewrite of identical content).
        # Byte identity is the stronger statement, so let it correct the verdict.
        if row["verdict"] == DIVERGENT and rep["identical"]:
            row["verdict"] = IDENTICAL
            row["direction"] = NEITHER
            row["note"] = "mtime differs but bytes are identical"
    return row


def scan(
    *,
    checkout_root: Path | str | None = None,
    now: datetime | None = None,
    with_hashes: bool = False,
    only: list[str] | None = None,
) -> dict[str, Any]:
    """Report divergence across every ``*.json`` store in either root.

    Fail-closed: a root that cannot be listed yields an explicit
    ``roots_readable`` of False and an ``UNKNOWN`` summary rather than an
    empty, healthy-looking result. A zero on an unlisted directory is not a
    zero divergence.
    """
    now = now or _now()
    prod_dir, served_dir = _roots(checkout_root)

    names: set[str] = set()
    readable = {"producer": prod_dir.is_dir(), "served": served_dir.is_dir()}
    for d in (prod_dir, served_dir):
        if d.is_dir():
            names |= {p.name for p in d.glob("*.json")}
    if only:
        names &= set(only)

    rows = [compare_store(n, checkout_root=checkout_root, now=now, with_hashes=with_hashes) for n in sorted(names)]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    diverged = [r for r in rows if r["verdict"] == DIVERGENT]
    producer_ahead = [r for r in diverged if r["direction"] == PRODUCER_AHEAD]
    served_ahead = [r for r in diverged if r["direction"] == SERVED_AHEAD]
    worst = max((r["skew_seconds"] or 0) for r in diverged) if diverged else 0

    if not (readable["producer"] and readable["served"]):
        status = "UNKNOWN"
        reason = "one or both state roots are not readable; divergence cannot be determined"
    elif diverged:
        status = "DIVERGENT"
        reason = (
            f"{len(diverged)} of {len(rows)} stores have forked "
            f"({len(producer_ahead)} producer-ahead, {len(served_ahead)} served-ahead)"
        )
    else:
        status = "CONVERGED"
        reason = f"all {len(rows)} stores agree across both roots"

    return {
        "schema": SCHEMA,
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "producer_root": str(prod_dir),
        "served_root": str(served_dir),
        "roots_readable": readable,
        "roots_are_same_directory": (prod_dir.resolve() == served_dir.resolve() if all(readable.values()) else None),
        "status": status,
        "reason": reason,
        "hashes_computed": bool(with_hashes),
        "store_count": len(rows),
        "counts": counts,
        "diverged_count": len(diverged),
        "producer_ahead_count": len(producer_ahead),
        "served_ahead_count": len(served_ahead),
        "worst_skew_seconds": worst,
        "auto_remediate": False,
        "action": "REPORT_AND_ESCALATE" if diverged else "NONE",
        "note": (
            "Divergent authoritative copies are reported, never merged "
            "(AGENTS.md 9.4 / WAVE G1). A producer-ahead fork means the served "
            "surface is rendering stale truth; a served-ahead fork means the "
            "running service is the only writer."
        ),
        "stores": rows,
    }


__all__ = [
    "ABSENT",
    "CALCULATION_VERSION",
    "DIVERGENT",
    "IDENTICAL",
    "NEITHER",
    "PRODUCER_AHEAD",
    "PRODUCER_ONLY",
    "SAME_INODE",
    "SCHEMA",
    "SERVED_AHEAD",
    "SERVED_ONLY",
    "STATE_REL",
    "compare_store",
    "scan",
]
