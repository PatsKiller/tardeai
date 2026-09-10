#!/usr/bin/env python3
"""disk_hygiene_enforcer.py — keep portfolio-server releases + stale backup piles bounded.

Prevents recurrence of the 2026-09-10 host fill (98% / ~11G free) caused mainly by
hundreds of immutable release directories under ~/trade-ai-releases/portfolio-server.

Usage:
  python scripts/disk_hygiene_enforcer.py --status
  python scripts/disk_hygiene_enforcer.py --dry-run
  python scripts/disk_hygiene_enforcer.py --apply          # deletes after filters
  python scripts/disk_hygiene_enforcer.py --apply --releases-only
  python scripts/disk_hygiene_enforcer.py --apply --backups-only

Safety:
  - Never deletes CURRENT / EXPECTED_RELEASE targets
  - Never deletes a release that is cwd of a live process
  - Never touches ~/db_backups (owned by backup_enforcer max_count=1)
  - Default policy dry_run=true; --apply required to mutate
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _load_policy() -> dict:
    p = ROOT / "config" / "disk_hygiene_policy.yaml"
    try:
        import yaml

        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {
            "releases": {
                "root": "~/trade-ai-releases/portfolio-server",
                "glob": "*-main-exact-*",
                "keep_n": 10,
                "protect_symlinks": ["CURRENT", "EXPECTED_RELEASE"],
            },
            "stale_backup_piles": [],
            "disk": {"warn_free_pct": 15, "critical_free_pct": 8, "target_path": "/"},
            "defaults": {"dry_run": True},
        }


def disk_status(cfg: dict) -> dict:
    target = _expand(cfg.get("target_path") or "/")
    st = os.statvfs(target)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used_pct = round(100.0 * (1.0 - (free / total)), 2) if total else 0.0
    free_pct = round(100.0 * free / total, 2) if total else 0.0
    warn = float(cfg.get("warn_free_pct") or 15)
    crit = float(cfg.get("critical_free_pct") or 8)
    level = "ok"
    if free_pct <= crit:
        level = "critical"
    elif free_pct <= warn:
        level = "warn"
    return {
        "path": str(target),
        "total_bytes": total,
        "free_bytes": free,
        "used_pct": used_pct,
        "free_pct": free_pct,
        "level": level,
        "warn_free_pct": warn,
        "critical_free_pct": crit,
    }


def _live_release_cwds(release_root: Path) -> set[Path]:
    """Return release dirs that are cwd of a live process."""
    protected: set[Path] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return protected
    root_s = str(release_root)
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            cwd = (pid_dir / "cwd").resolve()
        except OSError:
            continue
        s = str(cwd)
        if s.startswith(root_s + os.sep) or s == root_s:
            # map to immediate child under release_root when possible
            try:
                rel = cwd.relative_to(release_root)
                top = release_root / rel.parts[0]
                if top.is_dir():
                    protected.add(top.resolve())
            except Exception:
                protected.add(cwd)
    return protected


def _symlink_targets(release_root: Path, names: list[str]) -> set[Path]:
    out: set[Path] = set()
    for name in names:
        link = release_root / name
        try:
            if link.is_symlink() or link.exists():
                out.add(link.resolve())
        except OSError:
            continue
    return out


def list_release_dirs(cfg: dict) -> list[Path]:
    root = _expand(cfg.get("root") or "~/trade-ai-releases/portfolio-server")
    glob = cfg.get("glob") or "*-main-exact-*"
    if not root.is_dir():
        return []
    dirs = [p for p in root.glob(glob) if p.is_dir() and not p.is_symlink()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs


def plan_releases(cfg: dict) -> dict:
    root = _expand(cfg.get("root") or "~/trade-ai-releases/portfolio-server")
    keep_n = int(cfg.get("keep_n") or 10)
    protect_names = list(cfg.get("protect_symlinks") or ["CURRENT", "EXPECTED_RELEASE"])
    dirs = list_release_dirs(cfg)
    protected = _symlink_targets(root, protect_names) | _live_release_cwds(root)

    keep: list[str] = []
    delete: list[str] = []
    kept_newest = 0
    for d in dirs:
        resolved = d.resolve()
        if resolved in protected:
            keep.append(str(d))
            continue
        if kept_newest < keep_n:
            keep.append(str(d))
            kept_newest += 1
            continue
        delete.append(str(d))

    return {
        "root": str(root),
        "keep_n": keep_n,
        "total": len(dirs),
        "protected": sorted(str(p) for p in protected),
        "keep": keep,
        "delete": delete,
        "would_delete_count": len(delete),
    }


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for name in files:
                fp = Path(root) / name
                try:
                    total += fp.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def apply_release_deletes(plan: dict, *, dry_run: bool) -> dict:
    deleted: list[dict] = []
    errors: list[str] = []
    bytes_reclaimed = 0
    for p in plan.get("delete") or []:
        path = Path(p)
        if not path.exists():
            continue
        # Size walks across hundreds of release trees are too slow for dry-run;
        # measure only when actually deleting (or sample is enough for ops).
        size = 0 if dry_run else _dir_size_bytes(path)
        if dry_run:
            deleted.append({"path": p, "bytes": size, "action": "would_delete"})
            continue
        try:
            shutil.rmtree(path)
            deleted.append({"path": p, "bytes": size, "action": "deleted"})
            bytes_reclaimed += size
        except OSError as e:
            errors.append(f"{p}: {e}")
    return {
        "dry_run": dry_run,
        "deleted": deleted,
        "errors": errors,
        "bytes_reclaimed_est": bytes_reclaimed,
        "ok": not errors,
    }


def plan_stale_backups(piles: list[dict]) -> dict:
    """Plan file deletes in explicit stale backup piles (not ~/db_backups)."""
    now = time.time()
    would: list[dict] = []
    for pile in piles or []:
        base = _expand(pile.get("path") or "~")
        max_age_days = float(pile.get("max_age_days") or 45)
        cutoff = now - max_age_days * 86400
        glob = pile.get("glob")
        candidates: list[Path] = []
        if glob:
            candidates = list(base.glob(glob))
        elif base.is_dir():
            # files only at top level + immediate children files (no deep rglob)
            candidates = [p for p in base.iterdir() if p.is_file()]
            for sub in base.iterdir():
                if sub.is_dir() and not sub.is_symlink():
                    try:
                        candidates.extend([p for p in sub.iterdir() if p.is_file()])
                    except OSError:
                        continue
        # never touch db_backups
        candidates = [
            p
            for p in candidates
            if "db_backups" not in p.parts
            and p.is_file()
        ]
        for p in candidates:
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime >= cutoff:
                continue
            would.append(
                {
                    "path": str(p),
                    "bytes": st.st_size,
                    "age_days": round((now - st.st_mtime) / 86400, 1),
                    "pile": str(base),
                }
            )
    would.sort(key=lambda x: x["bytes"], reverse=True)
    return {
        "would_delete": would,
        "would_delete_count": len(would),
        "bytes": sum(x["bytes"] for x in would),
    }


def apply_stale_backup_deletes(plan: dict, *, dry_run: bool) -> dict:
    deleted: list[dict] = []
    errors: list[str] = []
    bytes_reclaimed = 0
    for item in plan.get("would_delete") or []:
        path = Path(item["path"])
        if not path.is_file():
            continue
        if dry_run:
            deleted.append({**item, "action": "would_delete"})
            bytes_reclaimed += int(item.get("bytes") or 0)
            continue
        try:
            path.unlink()
            deleted.append({**item, "action": "deleted"})
            bytes_reclaimed += int(item.get("bytes") or 0)
        except OSError as e:
            errors.append(f"{path}: {e}")
    return {
        "dry_run": dry_run,
        "deleted": deleted,
        "errors": errors,
        "bytes_reclaimed_est": bytes_reclaimed,
        "ok": not errors,
    }


def run(
    *,
    dry_run: bool,
    releases_only: bool = False,
    backups_only: bool = False,
    status_only: bool = False,
) -> dict:
    pol = _load_policy()
    out: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "disk": disk_status(pol.get("disk") or {}),
    }
    if status_only:
        rel_cfg = pol.get("releases") or {}
        dirs = list_release_dirs(rel_cfg)
        out["releases"] = {
            "root": str(_expand(rel_cfg.get("root") or "~/trade-ai-releases/portfolio-server")),
            "count": len(dirs),
            "keep_n": int(rel_cfg.get("keep_n") or 10),
            "newest": [str(p) for p in dirs[:5]],
        }
        return out

    do_releases = not backups_only
    do_backups = not releases_only

    if do_releases:
        plan = plan_releases(pol.get("releases") or {})
        out["releases_plan"] = {
            k: plan[k]
            for k in ("root", "keep_n", "total", "would_delete_count", "protected")
        }
        out["releases_plan"]["delete_sample"] = plan["delete"][:15]
        out["releases_result"] = apply_release_deletes(plan, dry_run=dry_run)

    if do_backups:
        bplan = plan_stale_backups(pol.get("stale_backup_piles") or [])
        out["backups_plan"] = {
            "would_delete_count": bplan["would_delete_count"],
            "bytes": bplan["bytes"],
            "sample": bplan["would_delete"][:15],
        }
        out["backups_result"] = apply_stale_backup_deletes(bplan, dry_run=dry_run)

    out["dry_run"] = dry_run
    out["ok"] = out.get("disk", {}).get("level") != "critical" or not dry_run
    # ok for exit code: failures in apply
    errs = []
    for key in ("releases_result", "backups_result"):
        if key in out and out[key].get("errors"):
            errs.extend(out[key]["errors"])
    out["ok"] = out.get("ok", True) and not errs
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Plan only (default unless --apply)")
    ap.add_argument("--apply", action="store_true", help="Actually delete")
    ap.add_argument("--releases-only", action="store_true")
    ap.add_argument("--backups-only", action="store_true")
    ap.add_argument("--json", action="store_true", default=True)
    args = ap.parse_args()
    dry = True
    if args.apply:
        dry = False
    if args.dry_run:
        dry = True
    out = run(
        dry_run=dry,
        releases_only=args.releases_only,
        backups_only=args.backups_only,
        status_only=args.status,
    )
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
