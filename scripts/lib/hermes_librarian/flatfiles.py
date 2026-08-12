"""Flat-file retention — policy-driven TTL for generated/artifact directories.

Supersedes the ad-hoc keep-newest-N logic in scripts/docs_retention.sh and
scripts/docs_hygiene.py. Declares targets in config/hermes_librarian_policy.yaml
under the ``flatfiles`` key so there is a single retention owner.

Safety:
  - dry-run by default (never deletes unless apply=True)
  - only touches paths explicitly listed in policy (no recursive globbing)
  - never touches narrative runbooks or canonical state — targets are
    generated dryrun/log/observation artifact directories only
"""
from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "config" / "hermes_librarian_policy.yaml"


def _load_targets() -> list[dict]:
    """Load flatfiles targets from policy. Returns [] if missing."""
    import yaml
    if not POLICY_PATH.exists():
        return []
    policy = yaml.safe_load(POLICY_PATH.read_text()) or {}
    return list(policy.get("flatfiles", {}).get("targets", []) or [])


def _prune_keep_newest(directory: Path, keep: int, *, apply: bool) -> list[dict]:
    """Remove all but the newest `keep` files (by mtime) in `directory`."""
    if not directory.is_dir():
        return []
    files = sorted(
        [p for p in directory.iterdir() if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[dict] = []
    for p in files[keep:]:
        size = p.stat().st_size
        removed.append({"path": str(p), "bytes": size})
        if apply:
            p.unlink(missing_ok=True)
    return removed


def _prune_age(directory: Path, pattern: str, days: int, *, apply: bool) -> list[dict]:
    """Remove files matching `pattern` older than `days` (by mtime)."""
    if not directory.is_dir():
        return []
    cutoff = time.time() - days * 86400
    removed: list[dict] = []
    for p in directory.glob(pattern):
        if not p.is_file():
            continue
        if p.stat().st_mtime < cutoff:
            removed.append({"path": str(p), "bytes": p.stat().st_size})
            if apply:
                p.unlink(missing_ok=True)
    return removed


def apply_flatfile_retention(*, dry_run: bool = False) -> dict:
    """Apply flat-file retention per policy. Returns summary of actions.

    Args:
        dry_run: if True (default), compute but do not delete.
    """
    targets = _load_targets()
    actions: list[dict] = []
    removed_all: list[dict] = []

    for t in targets:
        rel = t.get("path")
        if not rel:
            continue
        directory = ROOT / rel
        removed: list[dict] = []
        mode = None

        if "max_age_days" in t:
            removed = _prune_age(
                directory, t.get("pattern", "*"), int(t["max_age_days"]),
                apply=not dry_run,
            )
            mode = "max_age_days"
        elif "keep_newest" in t:
            removed = _prune_keep_newest(
                directory, int(t["keep_newest"]), apply=not dry_run,
            )
            mode = "keep_newest"
        else:
            continue

        removed_all.extend(removed)
        actions.append({
            "target": rel,
            "mode": mode,
            "would_remove": len(removed),
            "bytes_freed": sum(r["bytes"] for r in removed),
        })

    return {
        "mode": "dry-run" if dry_run else "apply",
        "targets": actions,
        "removed_count": len(removed_all),
        "bytes_freed": sum(r["bytes"] for r in removed_all),
        "removed": removed_all,
    }
