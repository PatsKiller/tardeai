#!/usr/bin/env python3
"""disk_hygiene_enforcer.py — PLAN ONLY: report portfolio-server releases + stale backup piles.

Written after the 2026-09-10 host fill (98% / ~11G free), caused mainly by hundreds of
immutable release directories under ~/trade-ai-releases/portfolio-server.

REMOVES NOTHING (2026-10-27, AGENTS.md §24.12 and §0 rule 6). §24.12 makes `scripts/disk_hygiene.py`
under `config/disk_hygiene_rules.json` -- run by the n8n lane `disk-hygiene` or by the operator from the CLI
-- the only code that may remove a release directory, and puts backups out of scope for any automated
removal. This script predates §24.12 and is not covered by it, so its apply mode refuses: it computes and
prints exactly the plan a dry run prints, adds a `refusal` block naming the governed route, and exits
EXIT_REFUSED (77). It spawns no process, so it never runs disk_hygiene.py's apply mode (lane/operator-only).

Usage:
  python scripts/disk_hygiene_enforcer.py --status
  python scripts/disk_hygiene_enforcer.py --dry-run
  python scripts/disk_hygiene_enforcer.py --apply                  # REFUSED: plan + refusal, exit 77
  python scripts/disk_hygiene_enforcer.py --apply --releases-only  # REFUSED
  python scripts/disk_hygiene_enforcer.py --apply --backups-only   # REFUSED (backups are never in scope)

Exit: 0 = plan printed; 1 = a dry run with the disk at the critical floor, or a planning error;
77 (EX_NOPERM) = --apply refused, status REFUSED_OUTSIDE_24_12. Exit 77 is a refusal, not a crash.

The plan still honours what the old apply honoured: CURRENT / EXPECTED_RELEASE targets, a release that is the
cwd of a live process, and ~/db_backups are never listed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: The status an --apply run reports. Callers (disk_pressure_guard, weekly_disk_cleanup_notify) and the
#: health agent read it; it is a refusal by design, not a failure of the run.
REFUSED_STATUS = "REFUSED_OUTSIDE_24_12"
#: sysexits EX_NOPERM: distinct from 0 (plan printed), 1 (failure) and 2 (argparse usage).
EXIT_REFUSED = 77
REFUSAL_REASON = (
    "disk_hygiene_enforcer.py removes nothing: under AGENTS.md §24.12 only scripts/disk_hygiene.py "
    "(config/disk_hygiene_rules.json), run by the n8n lane disk-hygiene or by the operator from the CLI, may "
    "remove a release directory, and backups are never in scope for automated removal (§24.12 'Not in scope', "
    "§0 rule 6). This run printed the plan only."
)
GOVERNED_ROUTE = {
    "release_dirs": "removal is the disk-hygiene lane's job: python3 scripts/disk_hygiene.py --report "
    "writes the manifest; the lane (or the operator CLI with a grant) applies it",
    "backups": "never removed automatically; deleting a backup is an operator decision (AGENTS.md §17 "
    "'deleting anything'), archive with a tripwire",
}


def refusal_block() -> dict:
    """What an --apply run says instead of removing anything."""
    return {"status": REFUSED_STATUS, "reason": REFUSAL_REASON, "governed_route": dict(GOVERNED_ROUTE)}


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

    cur = root / "CURRENT"
    return {
        "root": str(root),
        "keep_n": keep_n,
        "total": len(dirs),
        "protected": sorted(str(p) for p in protected),
        "keep": keep,
        "delete": delete,
        "would_delete_count": len(delete),
        # 2026-10-21 (D8.3): release-local files are compared against the release CURRENT points at.
        "reference": str(cur.resolve()) if cur.is_symlink() and cur.resolve().is_dir() else None,
    }


# ── Release-local data (2026-10-21, operator D8.3; AGENTS.md §0 rule 6) ──────────────────────────────────
# A release dir is not only code: data/ and state/ hold real directories (data/portfolios/reports ~113 MB,
# data/raw, data/merged, state/hermes.release-local-*). They die with the release. The plan reports, per release,
# the real files under those trees that the reference release (CURRENT) does not hold byte-identically.
# 2026-10-27 (§24.12): this script no longer removes a release, so it no longer archives-then-unlinks those
# files either (that step existed only to precede a removal). D8.3 binds whatever removes a release now.
RELEASE_LOCAL_TREES = ("data", "state")


def release_local_unique_files(release: Path, reference: Path | None) -> list[Path]:
    """Real files under <release>/data and <release>/state (symlinked dirs not followed) that ``reference`` does not
    hold byte-identically at the same relative path."""
    import filecmp

    out: list[Path] = []
    for top in RELEASE_LOCAL_TREES:
        base = release / top
        if base.is_symlink() or not base.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(base, followlinks=False):
            for name in files:
                fp = Path(dirpath) / name
                if fp.is_symlink() or not fp.is_file():
                    continue
                ref = (reference / fp.relative_to(release)) if reference else None
                try:
                    same = (
                        ref is not None
                        and ref.is_file()
                        and ref.stat().st_size == fp.stat().st_size
                        and filecmp.cmp(fp, ref, shallow=False)
                    )
                except OSError:
                    same = False
                if not same:
                    out.append(fp)
    return sorted(out)


def release_local_summary(release: Path, reference: Path | None) -> dict:
    """Count the release-local files CURRENT does not hold (plan only; nothing is archived or unlinked)."""
    uniq = release_local_unique_files(release, reference)
    return {"files": len(uniq), "bytes": sum(f.stat().st_size for f in uniq), "archive": None}


def _refused(entries: list[dict], errors: list[str]) -> dict:
    """The --apply result: the dry-run entries, marked refused; nothing removed, nothing reclaimed."""
    return {
        "dry_run": False,
        "refused": True,
        "status": REFUSED_STATUS,
        "deleted": [],
        "refused_items": [{**e, "action": "refused"} for e in entries],
        "errors": errors,
        "bytes_reclaimed_est": 0,
        "ok": not errors,
    }


def apply_release_deletes(plan: dict, *, dry_run: bool) -> dict:
    """Plan the release removals. ``dry_run=False`` is REFUSED (AGENTS.md §24.12): same plan, nothing removed."""
    deleted: list[dict] = []
    errors: list[str] = []
    reference = Path(plan["reference"]) if plan.get("reference") else None
    for p in plan.get("delete") or []:
        path = Path(p)
        if not path.exists():
            continue
        try:
            local = release_local_summary(path, reference)
        except Exception as e:  # noqa: BLE001 -- unreadable release-local tree: report it, list nothing
            # Message kept byte-identical to the pre-2026-10-27 dry run, which callers may grep.
            errors.append(f"{p}: release-local archive failed, release kept: {str(e)[:200]}")
            continue
        deleted.append({"path": p, "bytes": 0, "action": "would_delete", "release_local": local})
    if not dry_run:
        return _refused(deleted, errors)
    return {
        "dry_run": dry_run,
        "deleted": deleted,
        "errors": errors,
        "bytes_reclaimed_est": 0,
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
        candidates = [p for p in candidates if "db_backups" not in p.parts and p.is_file()]
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
    """Plan the backup-file removals. ``dry_run=False`` is REFUSED: backups are never in §24.12's scope."""
    deleted: list[dict] = []
    bytes_reclaimed = 0
    for item in plan.get("would_delete") or []:
        path = Path(item["path"])
        if not path.is_file():
            continue
        deleted.append({**item, "action": "would_delete"})
        bytes_reclaimed += int(item.get("bytes") or 0)
    if not dry_run:
        return _refused(deleted, [])
    return {
        "dry_run": dry_run,
        "deleted": deleted,
        "errors": [],
        "bytes_reclaimed_est": bytes_reclaimed,
        "ok": True,
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
        out["releases_plan"] = {k: plan[k] for k in ("root", "keep_n", "total", "would_delete_count", "protected")}
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
    # ok for exit code: planning errors
    errs = []
    for key in ("releases_result", "backups_result"):
        if key in out and out[key].get("errors"):
            errs.extend(out[key]["errors"])
    out["ok"] = out.get("ok", True) and not errs

    # 2026-10-27 (AGENTS.md §24.12): --apply is refused. The plan above is the dry run's plan; nothing was
    # removed. The post-apply postgres restart (2026-09-18) went with the removal: there is no reclaim here to
    # follow, and tradeai-postgres-main-watchdog + the postgres_main_down remedy own that restart.
    if not dry_run:
        out["apply_requested"] = True
        out["status"] = REFUSED_STATUS
        out["refused"] = True
        out["removed_count"] = 0
        out["refusal"] = refusal_block()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Plan only (the default)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help=f"REFUSED (AGENTS.md §24.12): prints the plan, removes nothing, exits {EXIT_REFUSED}",
    )
    ap.add_argument("--releases-only", action="store_true")
    ap.add_argument("--backups-only", action="store_true")
    ap.add_argument("--json", action="store_true", default=True)
    args = ap.parse_args(argv)
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
    if out.get("status") == REFUSED_STATUS:
        print(f"REFUSED: {REFUSAL_REASON}", file=sys.stderr)
        return EXIT_REFUSED
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
