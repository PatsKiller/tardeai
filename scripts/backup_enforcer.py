#!/usr/bin/env python3
"""backup_enforcer.py — hard-cap local pg dumps + optional Drive db prune.

Caps top-level dumps by archiving older files; the archive is never expired.
Reports whole-tree local bytes separately so archiving cannot look like reclaim.

Usage:
  python scripts/backup_enforcer.py                  # enforce local max_count
  python scripts/backup_enforcer.py --status         # JSON status only
  python scripts/backup_enforcer.py --dry-run        # print would-delete
  python scripts/backup_enforcer.py --drive-db       # also prune Drive db_backup_* to max_count

Policy: config/backup_policy.yaml
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import stat
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_policy() -> dict:
    p = ROOT / "config" / "backup_policy.yaml"
    try:
        import yaml
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        # minimal fallback matching user requirement
        return {
            "local_pg": {
                "dir": "~/db_backups",
                "pattern": "trade_ai_*.sql.gz",
                "max_count": 1,
                "min_bytes": 500_000_000,
                "max_total_bytes": 5_000_000_000,
            },
            "drive_db": {
                "folder_id": "1GYbZyM8nTfwuh-h2EsWTxbMpXlEUA6Qi",
                "prefix": "db_backup",
                "max_count": 1,
            },
        }


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


# A dump pg_dump is still writing is small and young, or still named *.part.
# D8.2: the hourly enforcer used to unlink any file under min_bytes at any age,
# which deletes a dump that runs past the hour. Skip those. Never unlink a
# finished dump; move it under archive/ (AGENTS.md §0 rail 6).
DEFAULT_SKIP_YOUNGER_S = 2 * 60 * 60
_PART_SUFFIXES = (".part", ".partial")


def _is_in_progress(path: Path, *, now: float, min_bytes: int, skip_younger_s: float) -> bool:
    """A dump still being written, or finished so recently the next hourly pass must not touch it.

    min_bytes is unused for the age test. A file under the size floor is still
    retired once it is older than skip_younger_s (an abandoned partial).
    """
    del min_bytes
    if path.name.endswith(_PART_SUFFIXES):
        return True
    try:
        st = path.stat()
    except OSError:
        return True
    return (now - st.st_mtime) < skip_younger_s


def _archive(path: Path, archive_dir: Path) -> Path:
    """Move a dump out of the live directory. Never unlink it."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    trip = archive_dir / "TRIPWIRE.txt"
    if not trip.exists():
        trip.write_text(
            "Archived pg dumps. If a live dump path is missing, look here before assuming it was deleted.\n"
            "Do not unlink these files.\n",
            encoding="utf-8",
        )
    dest = archive_dir / path.name
    if dest.exists():
        dest = archive_dir / f"{path.stem}.{int(path.stat().st_mtime)}{path.suffix}"
    path.rename(dest)
    return dest


def list_local_dumps(cfg: dict) -> list[Path]:
    d = _expand(cfg.get("dir") or "~/db_backups")
    pat = cfg.get("pattern") or "trade_ai_*.sql.gz"
    if not d.is_dir():
        return []
    files = sorted(d.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def local_storage_usage(
    cfg: dict, *, max_entries: int = 100_000, max_seconds: float = 2.0, max_depth: int = 32
) -> dict:
    """Metadata only: disjoint path buckets, never dump contents or symlink targets.

    The existing total_bytes is a TOP-LEVEL dump total consumed as a dump-size
    baseline by backup_verify.py. Archives/holds are outside that cap, not freed
    space. Incomplete scans expose partial observations, never a complete total.
    """
    root = Path(os.path.expanduser(cfg.get("dir") or "~/db_backups")).absolute()
    totals = dict.fromkeys(("live_dump_bytes", "archive_bytes", "held_bytes", "other_bytes"), 0)
    unknown = set()
    scanned = 0
    started = time.monotonic()
    # Every component is opened relative to an anchored descriptor. O_NOFOLLOW
    # also fences a directory swapped to a symlink after its observed stat.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    stack = []
    opening = None
    try:
        opening = os.open(root.anchor, flags)
        for part in root.parts[1:]:
            child = os.open(part, flags, dir_fd=opening)
            os.close(opening)
            opening = child
        root_info = os.fstat(opening)
        stack.append((opening, os.scandir(opening), ()))
        opening = None
        scanned = 1
        while stack:
            if scanned >= max_entries or time.monotonic() - started >= max_seconds:
                unknown.add("scan_limit")
                break
            parent_fd, entries, parent_parts = stack[-1]
            try:
                entry = next(entries)
            except StopIteration:
                entries.close()
                os.close(parent_fd)
                stack.pop()
                continue
            scanned += 1
            parts = parent_parts + (entry.name,)
            try:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    unknown.add("symlink_not_followed")
                elif stat.S_ISDIR(info.st_mode):
                    if len(parts) > max_depth:
                        unknown.add("depth_limit")
                        continue
                    opening = os.open(entry.name, flags, dir_fd=parent_fd)
                    opened = os.fstat(opening)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        unknown.add("directory_changed")
                        os.close(opening)
                        opening = None
                        continue
                    stack.append((opening, os.scandir(opening), parts))
                    opening = None
                elif stat.S_ISREG(info.st_mode):
                    if any(p.lower() == "hold" or p.lower().startswith(("hold-", "hold_")) for p in parts[:-1]):
                        bucket = "held_bytes"
                    elif parts[0] == "archive":
                        bucket = "archive_bytes"
                    elif len(parts) == 1 and fnmatch.fnmatch(entry.name, cfg.get("pattern") or "trade_ai_*.sql.gz"):
                        bucket = "live_dump_bytes"
                    else:
                        bucket = "other_bytes"
                    totals[bucket] += info.st_size
                else:
                    unknown.add("unsupported_entry")
            except OSError:
                unknown.add("entry_unavailable")
                if opening is not None:
                    os.close(opening)
                    opening = None
        # A renamed/replaced root no longer describes the configured location.
        opening = os.open(root.anchor, flags)
        for part in root.parts[1:]:
            child = os.open(part, flags, dir_fd=opening)
            os.close(opening)
            opening = child
        current = os.fstat(opening)
        if (current.st_dev, current.st_ino) != (root_info.st_dev, root_info.st_ino):
            unknown.add("directory_changed")
    except OSError:
        unknown.add("entry_unavailable")
    finally:
        if opening is not None:
            os.close(opening)
        for descriptor, entries, _ in reversed(stack):
            entries.close()
            os.close(descriptor)
    complete = not unknown
    return {
        "byte_basis": "logical_regular_file_bytes_by_path_not_reclaimable_disk_bytes",
        "cap_scope": "top_level_dump_pattern_only",
        "archive_and_holds_outside_cap": True,
        "measurement_complete": complete,
        "unknown_reasons": sorted(unknown),
        "entries_scanned": scanned,
        "scan_max_entries": max_entries,
        "scan_max_seconds": max_seconds,
        "scan_max_depth": max_depth,
        **{key: value if complete else None for key, value in totals.items()},
        "local_backup_total_bytes": sum(totals.values()) if complete else None,
        "observed_bytes": totals,
    }


def enforce_local(cfg: dict, *, dry_run: bool = False, now: float | None = None) -> dict:
    min_bytes = int(cfg.get("min_bytes") or 500_000_000)
    max_count = int(cfg.get("max_count") or 1)
    max_total = int(cfg.get("max_total_bytes") or 5_000_000_000)
    skip_younger_s = float(cfg.get("skip_younger_than_s") or DEFAULT_SKIP_YOUNGER_S)
    now = time.time() if now is None else now
    live_dir = _expand(cfg.get("dir") or "~/db_backups")
    archive_dir = live_dir / "archive"
    files = list_local_dumps(cfg)
    archived: list[str] = []
    skipped_in_progress: list[str] = []
    partials: list[str] = []
    kept: list[str] = []

    def _retire(path: Path) -> None:
        if dry_run:
            archived.append(f"would_archive:{path}")
            return
        try:
            dest = _archive(path, archive_dir)
            archived.append(str(dest))
        except OSError as e:
            archived.append(f"{path}:archive_fail:{e}")

    full: list[Path] = []
    for f in files:
        if _is_in_progress(f, now=now, min_bytes=min_bytes, skip_younger_s=skip_younger_s):
            skipped_in_progress.append(str(f))
            continue
        try:
            sz = f.stat().st_size
        except OSError:
            skipped_in_progress.append(str(f))
            continue
        if sz < min_bytes:
            partials.append(str(f))
            _retire(f)
        else:
            full.append(f)

    for i, f in enumerate(full):
        if i < max_count:
            kept.append(str(f))
        else:
            _retire(f)

    remaining = list_local_dumps(cfg)
    total_bytes = 0
    for f in remaining:
        try:
            total_bytes += f.stat().st_size
        except OSError:
            pass

    storage = local_storage_usage(cfg)
    return {
        "ok": len([p for p in remaining if p.stat().st_size >= min_bytes]) <= max_count
              and total_bytes <= max_total and storage["measurement_complete"],
        "dry_run": dry_run,
        "kept": kept,
        "deleted": archived,
        "archived": archived,
        "skipped_in_progress": skipped_in_progress,
        "partials_removed": partials,
        "remaining_count": len(remaining),
        "remaining_full": sum(1 for p in remaining if p.stat().st_size >= min_bytes),
        "total_bytes": total_bytes,
        "max_count": max_count,
        "max_total_bytes": max_total,
        "over_bytes": total_bytes > max_total,
        "storage": storage,
    }


def status_local(cfg: dict) -> dict:
    min_bytes = int(cfg.get("min_bytes") or 500_000_000)
    live_complete = True
    try:
        files = list_local_dumps(cfg)
    except OSError:
        files = []
        live_complete = False
    items = []
    total = 0
    newest_age_h = None
    import time
    now = time.time()
    for f in files:
        try:
            st = f.stat()
            total += st.st_size
            age_h = (now - st.st_mtime) / 3600
            if newest_age_h is None:
                newest_age_h = age_h
            items.append({
                "path": str(f),
                "bytes": st.st_size,
                "full": st.st_size >= min_bytes,
                "age_hours": round(age_h, 2),
            })
        except OSError:
            live_complete = False
    storage = local_storage_usage(cfg)
    max_total = int(cfg.get("max_total_bytes") or 5_000_000_000)
    return {
        "count": len(items),
        "full_count": sum(1 for i in items if i["full"]),
        "total_bytes": total if live_complete else None,
        "live_measurement_complete": live_complete,
        "newest_age_hours": newest_age_h,
        "files": items[:20],
        "max_count": int(cfg.get("max_count") or 1),
        "max_total_bytes": max_total,
        "over_bytes": total > max_total if live_complete else None,
        "compliant": live_complete and storage["measurement_complete"] and total <= max_total
                     and sum(1 for i in items if i["full"]) <= int(cfg.get("max_count") or 1),
        "storage": storage,
    }


def enforce_drive_db(cfg: dict, *, dry_run: bool = False) -> dict:
    """Prune Drive Trade_AI_Backups db_backup_* to max_count (newest by name)."""
    folder = cfg.get("folder_id") or "1GYbZyM8nTfwuh-h2EsWTxbMpXlEUA6Qi"
    prefix = cfg.get("prefix") or "db_backup"
    max_count = int(cfg.get("max_count") or 1)
    gog = Path.home() / ".local" / "bin" / "gog"
    if not gog.exists():
        return {"ok": False, "error": "gog CLI not found", "deleted": []}
    env = os.environ.copy()
    pw_file = Path.home() / ".openclaw" / "credentials" / "gog_keyring_password"
    if pw_file.exists() and "GOG_KEYRING_PASSWORD" not in env:
        env["GOG_KEYRING_PASSWORD"] = pw_file.read_text().strip()
    import subprocess
    r = subprocess.run(
        [str(gog), "drive", "ls", "-a", "john@jwwhiting.com", "--parent", folder, "-p"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout)[:300], "deleted": []}
    # lines: id \t name \t ...
    rows = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        fid, name = parts[0].strip(), parts[1].strip()
        if name.startswith(prefix + "_"):
            rows.append((name, fid))
    rows.sort(key=lambda x: x[0], reverse=True)  # name embeds timestamp
    keep = rows[:max_count]
    drop = rows[max_count:]
    deleted = []
    for name, fid in drop:
        if dry_run:
            deleted.append({"id": fid, "name": name, "action": "would_delete"})
            continue
        rr = subprocess.run(
            [str(gog), "drive", "rm", fid, "-a", "john@jwwhiting.com", "-y", "--permanent"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        deleted.append({
            "id": fid, "name": name,
            "action": "deleted" if rr.returncode == 0 else f"fail:{rr.returncode}",
        })
    return {
        "ok": True,
        "dry_run": dry_run,
        "kept": [{"name": n, "id": i} for n, i in keep],
        "deleted": deleted,
        "remaining": len(keep),
        "max_count": max_count,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--drive-db", action="store_true", help="Also enforce Drive db_backup max_count")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    pol = _load_policy()
    local_cfg = pol.get("local_pg") or {}
    drive_cfg = pol.get("drive_db") or {}

    if args.status:
        out = {"local": status_local(local_cfg)}
        print(json.dumps(out, indent=2))
        return 0 if out["local"].get("compliant") else 1

    result = {"local": enforce_local(local_cfg, dry_run=args.dry_run)}
    if args.drive_db:
        result["drive_db"] = enforce_drive_db(drive_cfg, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    ok = result["local"].get("ok", False)
    if args.drive_db:
        ok = ok and result.get("drive_db", {}).get("ok", False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
