#!/usr/bin/env python3
"""One-shot: COPY generated reports stranded in release dirs into the persistent reports root.

Until 2026-10-09 every report writer resolved ``PROJECT_ROOT/data/portfolios/reports``;
cron runs from ``portfolio-server/CURRENT`` where that is a real per-release directory, so
reports piled up inside whichever release was current. Writers now resolve
``lib.portfolio_reports_root.portfolio_reports_root()`` (persistent-state). This script
carries the history across.

Rules (AGENTS.md: never delete — copy/archive):
  * DRY-RUN by default. ``--apply`` is required to write anything.
  * Copies only, each with an exclusive create (O_EXCL). Never moves, never deletes,
    never overwrites; a name taken between plan and apply is counted ``skipped_exists``.
  * Releases are visited CURRENT first, then newest-first by directory mtime, so the copy
    being served today claims the plain filename.
  * A file whose bytes already exist at that relative path (plain name or an earlier
    conflict copy) is skipped as identical.
  * A file whose bytes differ is kept beside it as ``<stem>.release-<release><suffix>``.
  * Symlinks inside a source tree are reported, never followed or copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from lib.portfolio_reports_root import REPORTS_RELPATH, portfolio_reports_root, state_root  # noqa: E402
except ImportError:  # pragma: no cover - imported as scripts.<module>
    from scripts.lib.portfolio_reports_root import REPORTS_RELPATH, portfolio_reports_root, state_root  # noqa: E402

CURRENT_LINK = "CURRENT"
CONFLICT_TAG = ".release-"


def default_releases_root() -> Path:
    """``portfolio-server`` sits beside the persistent-state root."""
    return state_root().parent / "portfolio-server"


def _sha256(path: Path, cache: dict[Path, str]) -> str:
    if path not in cache:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        cache[path] = h.hexdigest()
    return cache[path]


def release_sources(releases_root: Path, dest: Path) -> list[tuple[str, Path]]:
    """(release name, reports dir) in claim order: CURRENT first, then newest-first."""
    dest_resolved = dest.resolve() if dest.exists() else dest
    current = releases_root / CURRENT_LINK
    current_target = current.resolve() if current.is_symlink() or current.is_dir() else None
    dirs = [p for p in releases_root.iterdir()
            if p.is_dir() and not p.is_symlink() and p.name != CURRENT_LINK]
    dirs.sort(key=lambda p: (p.resolve() != current_target, -p.stat().st_mtime, p.name))
    out = []
    for rel_dir in dirs:
        src = rel_dir / REPORTS_RELPATH
        if not src.is_dir():
            continue
        if src.resolve() == dest_resolved:
            continue  # already linked to the persistent root
        out.append((rel_dir.name, src))
    return out


def conflict_name(rel: Path, release: str) -> Path:
    return rel.with_name(f"{rel.stem}{CONFLICT_TAG}{release}{rel.suffix}")


def plan_copy(sources: list[tuple[str, Path]], dest: Path) -> dict:
    cache: dict[Path, str] = {}
    known: dict[Path, set[str]] = {}  # dest-relative path -> hashes already present there
    taken: set[Path] = set()  # dest-relative names already claimed (existing or planned)
    actions: list[dict] = []
    counts = {"files_seen": 0, "copy_new": 0, "copy_conflict": 0, "skip_identical": 0,
              "skip_symlink": 0, "bytes_to_copy": 0}
    per_release: dict[str, dict] = {}

    def present_hashes(rel: Path) -> set[str]:
        if rel not in known:
            hashes: set[str] = set()
            target = dest / rel
            if target.is_file():
                hashes.add(_sha256(target, cache))
                taken.add(rel)
            parent = (dest / rel).parent
            if parent.is_dir():
                for sib in parent.glob(f"{rel.stem}{CONFLICT_TAG}*{rel.suffix}"):
                    if sib.is_file():
                        hashes.add(_sha256(sib, cache))
                        taken.add(sib.relative_to(dest))
            known[rel] = hashes
        return known[rel]

    for release, src in sources:
        rc = per_release.setdefault(release, {"files": 0, "copy_new": 0, "copy_conflict": 0,
                                              "skip_identical": 0, "skip_symlink": 0})
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            base = Path(dirpath)
            for d in list(dirnames):
                if (base / d).is_symlink():
                    counts["skip_symlink"] += 1
                    rc["skip_symlink"] += 1
                    dirnames.remove(d)
            dirnames.sort()
            for name in sorted(filenames):
                f = base / name
                counts["files_seen"] += 1
                rc["files"] += 1
                if f.is_symlink() or not f.is_file():
                    counts["skip_symlink"] += 1
                    rc["skip_symlink"] += 1
                    continue
                rel = f.relative_to(src)
                digest = _sha256(f, cache)
                hashes = present_hashes(rel)
                if digest in hashes:
                    counts["skip_identical"] += 1
                    rc["skip_identical"] += 1
                    continue
                if rel not in taken:
                    target_rel, kind = rel, "copy_new"
                else:
                    target_rel, kind = conflict_name(rel, release), "copy_conflict"
                    n = 2
                    while target_rel in taken or (dest / target_rel).exists():
                        target_rel = conflict_name(rel, f"{release}-{n}")
                        n += 1
                taken.add(target_rel)
                hashes.add(digest)
                size = f.stat().st_size
                counts[kind] += 1
                rc[kind] += 1
                counts["bytes_to_copy"] += size
                actions.append({"kind": kind, "src": str(f), "dest": str(dest / target_rel),
                                "bytes": size})
    return {"counts": counts, "per_release": per_release, "actions": actions}


def _exclusive_copy(src: Path, target: Path) -> bool:
    """Copy ``src`` to ``target`` only if ``target`` does not exist, atomically.

    ``O_CREAT | O_EXCL`` makes the existence check and the create one syscall, so a
    writer that lands the same name between plan and apply is never overwritten (the
    old exists()-then-copy2 left that window open). Metadata is copied after the bytes.
    Returns False when the name was already taken.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
            shutil.copyfileobj(inp, out, 1 << 20)
    except BaseException:
        # Only the partial file WE just created is removed; nothing pre-existing is touched.
        target.unlink(missing_ok=True)
        raise
    shutil.copystat(src, target)
    return True


def apply_plan(plan: dict) -> dict:
    copied = skipped_exists = 0
    for a in plan["actions"]:
        if _exclusive_copy(Path(a["src"]), Path(a["dest"])):
            copied += 1
        else:  # a racing writer got there first — never overwrite
            skipped_exists += 1
    return {"copied": copied, "skipped_exists": skipped_exists}


def extra_source_label(src: Path) -> str:
    """Name for an --extra-source in conflict suffixes: the tree that owns
    ``data/portfolios/reports`` when the path has that shape, else the dir itself."""
    r = src.resolve()
    parts = r.parts
    if len(parts) >= 4 and Path(*parts[-3:]) == REPORTS_RELPATH:
        owner = parts[-4]
    else:
        owner = r.name or "root"
    return f"extra-{owner}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--releases-root", help="portfolio-server releases dir "
                    "(default: sibling of the persistent-state root)")
    ap.add_argument("--dest", help="persistent reports root (default: portfolio_reports_root())")
    ap.add_argument("--extra-source", action="append", default=[], metavar="DIR",
                    help="another data/portfolios/reports dir to carry (claims AFTER the releases); "
                         "repeatable")
    ap.add_argument("--apply", action="store_true", help="copy files (default is dry-run)")
    ap.add_argument("--show-actions", type=int, default=0, help="print the first N planned actions")
    args = ap.parse_args(argv)

    releases_root = Path(args.releases_root) if args.releases_root else default_releases_root()
    dest = Path(args.dest) if args.dest else portfolio_reports_root()
    if not releases_root.is_dir():
        print(json.dumps({"ok": False, "error": f"releases root not found: {releases_root}"}))
        return 2
    sources = release_sources(releases_root, dest)
    for extra in args.extra_source:
        src = Path(extra)
        if src.is_dir() and src.resolve() != (dest.resolve() if dest.exists() else dest):
            sources.append((extra_source_label(src), src))
    plan = plan_copy(sources, dest)
    summary = {
        "ok": True,
        "mode": "apply" if args.apply else "dry-run",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "releases_root": str(releases_root),
        "dest": str(dest),
        "dest_existed": dest.is_dir(),
        "releases": [name for name, _ in sources],
        "counts": plan["counts"],
        "per_release": plan["per_release"],
    }
    if args.show_actions:
        summary["actions_sample"] = plan["actions"][: args.show_actions]
    if args.apply:
        summary.update(apply_plan(plan))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
