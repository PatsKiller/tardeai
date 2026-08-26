"""Exact-main overlay safety: persistent stores must survive deploy.

Refuse to retarget CURRENT data/{cio,runtime,portfolios/state,health} at an
empty source-tree directory when a prior overlay already held those files.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

OVERLAY_RELS = (
    "data/cio",
    "data/runtime",
    "data/health",
    "data/portfolios/state",
)


def overlay_data_source(*, canonical_source: Path | str | None = None) -> Path:
    """Prefer GOOD_PERSISTENT_ROOT when provisioned; else legacy source tree."""
    env = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    preferred = Path(env) if env else Path.home() / "trade-ai-releases" / "persistent-state"
    if (preferred / "PERSISTENT_STATE_ROOT.json").is_file():
        return preferred
    if canonical_source:
        return Path(canonical_source)
    return Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")

# Files that mean "this persistent store is not empty".
SENTINELS = {
    "data/cio": ("cio_investment_brief.json", "outcome_checkpoints.jsonl", "aif_memory.json"),
    "data/runtime": ("advisory_desk_latest.json",),
    "data/health": (),
    "data/portfolios/state": ("holdings.json",),
}


def _has_sentinel(directory: Path, rel: str) -> bool:
    if not directory.exists():
        return False
    names = SENTINELS.get(rel) or ()
    if not names:
        try:
            return any(directory.iterdir())
        except OSError:
            return False
    return any((directory / n).exists() for n in names)


def overlay_is_safe(
    *,
    canonical_source: Path | str,
    dest: Path | str,
    rels: tuple[str, ...] = OVERLAY_RELS,
) -> dict[str, Any]:
    src_root = Path(canonical_source)
    dest_root = Path(dest)
    blocked = []
    allowed = []
    for rel in rels:
        source = src_root / rel
        target = dest_root / rel
        source_ok = _has_sentinel(source, rel)
        dest_ok = _has_sentinel(target, rel)
        if dest_ok and not source_ok:
            blocked.append({
                "rel": rel,
                "reason": "REFUSE_EMPTY_SOURCE_TREE_OVERLAY",
                "source": str(source),
                "dest": str(target),
                "detail": "Destination already holds persistent files; canonical source is empty.",
            })
        else:
            allowed.append({"rel": rel, "source": str(source), "source_has_data": source_ok})
    ok = not blocked
    return {
        "schema": "PersistentOverlayGuard@v1",
        "ok": ok,
        "blocked": blocked,
        "allowed": allowed,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def apply_overlay_symlinks(
    *,
    canonical_source: Path | str,
    dest: Path | str,
    rels: tuple[str, ...] = OVERLAY_RELS,
) -> dict[str, Any]:
    """Isolated-test overlay. Never used against live CURRENT from tests."""
    guard = overlay_is_safe(canonical_source=canonical_source, dest=dest, rels=rels)
    if not guard["ok"]:
        return {**guard, "applied": False}
    src_root = Path(canonical_source)
    dest_root = Path(dest)
    linked = []
    for rel in rels:
        source = src_root / rel
        target = dest_root / rel
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                # Do not rm -rf a real directory of production data.
                continue
        os.symlink(str(source), str(target))
        linked.append({"rel": rel, "target": str(target), "source": str(source)})
    return {**guard, "applied": True, "linked": linked}
