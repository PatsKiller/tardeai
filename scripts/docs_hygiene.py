#!/usr/bin/env python3
"""docs_hygiene.py — prune generated doc churn; report large non-canonical blobs.

Does NOT delete narrative runbooks. Only generated dryruns / payload dumps and
reports multi-GB ad-hoc archives under $HOME for operator review.

Usage:
  .venv/bin/python scripts/docs_hygiene.py --dry-run
  .venv/bin/python scripts/docs_hygiene.py --apply
  .venv/bin/python scripts/docs_hygiene.py --report-home
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Generated dirs: keep newest N files
GENERATED_KEEP = {
    ROOT / "docs/hermes/librarian_loop_dryruns": 10,
    ROOT / "docs/hermes/phase3b_dryrun": 10,
    ROOT / "docs/hermes/backlog_health": 5,
}

# Patterns under docs/ that may be age-pruned (days)
AGE_PRUNE = [
    (ROOT / "docs/hermes/observations", "latest_*_summary.json", 14),
]


def prune_keep_newest(directory: Path, keep: int, *, apply: bool) -> list[str]:
    if not directory.is_dir():
        return []
    files = sorted(
        [p for p in directory.iterdir() if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for p in files[keep:]:
        removed.append(str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p))
        if apply:
            p.unlink(missing_ok=True)
    return removed


def prune_age(directory: Path, pattern: str, days: int, *, apply: bool) -> list[str]:
    if not directory.is_dir():
        return []
    cutoff = time.time() - days * 86400
    removed = []
    for p in directory.glob(pattern):
        if p.is_file() and p.stat().st_mtime < cutoff:
            removed.append(str(p))
            if apply:
                p.unlink(missing_ok=True)
    return removed


def report_home_archives(min_mb: int = 100) -> list[dict]:
    home = Path.home()
    hits = []
    patterns = [
        "*backup*.tgz", "*backup*.tar.gz", "*Backup*.tgz",
        "doc_hygiene_backup_*", "master_rewrite_backup_*",
        "tradeai_backup_*", "backup_tradeai_*",
    ]
    seen = set()
    for pat in patterns:
        for p in home.glob(pat):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz >= min_mb * 1024 * 1024:
                hits.append({
                    "path": str(p),
                    "mb": round(sz / 1e6, 1),
                    "note": "operator review — not auto-deleted",
                })
    hits.sort(key=lambda x: -x["mb"])
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-home", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    apply = bool(args.apply) and not args.dry_run

    removed = []
    for d, keep in GENERATED_KEEP.items():
        removed.extend(prune_keep_newest(d, keep, apply=apply))
    for d, pat, days in AGE_PRUNE:
        removed.extend(prune_age(d, pat, days, apply=apply))

    out = {
        "mode": "apply" if apply else "dry_run",
        "removed_or_would_remove": removed,
        "count": len(removed),
    }
    if args.report_home:
        out["home_archives_mb"] = report_home_archives()

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"[{out['mode']}] docs hygiene: {out['count']} file(s)")
        for r in removed[:40]:
            print(f"  - {r}")
        if out.get("home_archives_mb"):
            print("\nLarge archives under $HOME (manual review):")
            for h in out["home_archives_mb"][:20]:
                print(f"  {h['mb']:>8.1f} MB  {h['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
