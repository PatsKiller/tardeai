#!/usr/bin/env python3
"""docs_tip_hygiene_enforcer.py — keep docs tip current; git history retains the rest.

Uses ``report_docs_inventory.classify`` statuses. Default is dry-run.
``--apply`` runs ``git rm -f --`` on classified tip-delete candidates only.

Never deletes ``active_keep`` / ``current_phase_keep`` or protected globs.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_policy() -> dict:
    p = ROOT / "config" / "docs_tip_hygiene_policy.yaml"
    try:
        import yaml

        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {
            "delete_statuses": [
                "archive_superseded",
                "archive_session_handoff",
                "archive_legacy_blueprint",
                "delete_candidate_duplicate",
            ],
            "protect_statuses": ["active_keep", "current_phase_keep"],
            "protect_globs": ["docs/INDEX.md", "docs/project/**", "docs/architecture/**"],
            "defaults": {"dry_run": True},
        }


def _protected(path: str, globs: list[str]) -> bool:
    for g in globs or []:
        if fnmatch.fnmatch(path, g):
            return True
    return False


def _has_superseded_banner(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False
    return "SUPERSEDED" in head.upper()[:800]


def plan(pol: dict) -> dict:
    import report_docs_inventory as inv

    inventory, summary = inv.collect_inventory(ROOT / "docs")
    delete_statuses = set(pol.get("delete_statuses") or [])
    protect_statuses = set(pol.get("protect_statuses") or [])
    protect_globs = list(pol.get("protect_globs") or [])

    candidates: list[dict] = []
    protected: list[str] = []

    for e in inventory:
        path = e["path"]
        status = e.get("status_guess") or ""
        if status in protect_statuses or _protected(path, protect_globs):
            protected.append(path)
            continue
        if status in delete_statuses:
            # For byte-identical duplicates, keep the first path in the group.
            if status == "delete_candidate_duplicate":
                group = e.get("duplicate_group") or [path]
                keeper = sorted(group)[0]
                if path == keeper:
                    continue
            candidates.append(
                {
                    "path": path,
                    "status_guess": status,
                    "reason": e.get("reason"),
                    "size": e.get("size"),
                    "source": "inventory_status",
                }
            )

    # Banner-based superseded dated docs
    max_age = int(pol.get("superseded_banner_max_age_days") or 14)
    now = datetime.now(timezone.utc).timestamp()
    for glob in pol.get("superseded_banner_globs") or []:
        for path in ROOT.glob(glob):
            if not path.is_file():
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if _protected(rel, protect_globs):
                continue
            if any(c["path"] == rel for c in candidates):
                continue
            if not _has_superseded_banner(path):
                continue
            age_days = (now - path.stat().st_mtime) / 86400
            if age_days < max_age:
                continue
            candidates.append(
                {
                    "path": rel,
                    "status_guess": "archive_superseded_banner",
                    "reason": f"SUPERSEDED banner + age_days={age_days:.1f}",
                    "size": path.stat().st_size,
                    "source": "superseded_banner",
                }
            )

    candidates.sort(key=lambda x: (-int(x.get("size") or 0), x["path"]))
    return {
        "inventory_summary": summary.get("by_status") if isinstance(summary, dict) else summary,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "protected_count": len(protected),
        "bytes": sum(int(c.get("size") or 0) for c in candidates),
    }


def apply_git_rm(paths: list[str], *, dry_run: bool) -> dict:
    removed: list[str] = []
    missing: list[str] = []
    errors: list[str] = []
    if not paths:
        return {"dry_run": dry_run, "removed": [], "missing": [], "errors": [], "ok": True}
    if dry_run:
        for p in paths:
            if (ROOT / p).exists():
                removed.append(p)
            else:
                missing.append(p)
        return {
            "dry_run": True,
            "removed": removed,
            "missing": missing,
            "errors": [],
            "ok": True,
            "action": "would_git_rm",
        }

    # Batch git rm
    chunk = 80
    for i in range(0, len(paths), chunk):
        batch = paths[i : i + chunk]
        existing = [p for p in batch if (ROOT / p).exists()]
        for p in batch:
            if p not in existing:
                missing.append(p)
        if not existing:
            continue
        try:
            subprocess.run(
                ["git", "-C", str(ROOT), "rm", "-f", "--"] + existing,
                check=True,
                capture_output=True,
                text=True,
            )
            removed.extend(existing)
        except subprocess.CalledProcessError as e:
            errors.append((e.stderr or e.stdout or str(e))[:400])
    return {
        "dry_run": False,
        "removed": removed,
        "missing": missing,
        "errors": errors,
        "ok": not errors,
        "action": "git_rm",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true", help="git rm tip-delete candidates")
    ap.add_argument("--limit", type=int, default=0, help="Optional max files to remove")
    args = ap.parse_args()
    dry = True
    if args.apply:
        dry = False
    if args.dry_run:
        dry = True

    pol = _load_policy()
    planned = plan(pol)
    paths = [c["path"] for c in planned["candidates"]]
    if args.limit and args.limit > 0:
        paths = paths[: args.limit]
        planned["candidates"] = planned["candidates"][: args.limit]
        planned["candidate_count"] = len(paths)
        planned["bytes"] = sum(int(c.get("size") or 0) for c in planned["candidates"])

    result = apply_git_rm(paths, dry_run=dry)
    out = {
        "ok": result.get("ok", True),
        "ts": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry,
        "plan": {
            "candidate_count": planned["candidate_count"],
            "bytes": planned["bytes"],
            "inventory_summary": planned.get("inventory_summary"),
            "sample": planned["candidates"][:30],
        },
        "result": result,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
