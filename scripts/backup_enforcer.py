#!/usr/bin/env python3
"""backup_enforcer.py — hard-cap local pg dumps + optional Drive db prune.

Prevents unbounded ~/db_backups growth (Aug 2026 backup storm).

Usage:
  python scripts/backup_enforcer.py                  # enforce local max_count
  python scripts/backup_enforcer.py --status         # JSON status only
  python scripts/backup_enforcer.py --dry-run        # print would-delete
  python scripts/backup_enforcer.py --drive-db       # also prune Drive db_backup_* to max_count

Policy: config/backup_policy.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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


def list_local_dumps(cfg: dict) -> list[Path]:
    d = _expand(cfg.get("dir") or "~/db_backups")
    pat = cfg.get("pattern") or "trade_ai_*.sql.gz"
    if not d.is_dir():
        return []
    files = sorted(d.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def enforce_local(cfg: dict, *, dry_run: bool = False) -> dict:
    min_bytes = int(cfg.get("min_bytes") or 500_000_000)
    max_count = int(cfg.get("max_count") or 1)
    max_total = int(cfg.get("max_total_bytes") or 5_000_000_000)
    files = list_local_dumps(cfg)
    deleted: list[str] = []
    partials: list[str] = []
    kept: list[str] = []

    # Drop partials first
    full: list[Path] = []
    for f in files:
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        if sz < min_bytes:
            partials.append(str(f))
            if not dry_run:
                try:
                    f.unlink()
                    deleted.append(str(f))
                except OSError as e:
                    partials.append(f"{f}:unlink_fail:{e}")
        else:
            full.append(f)

    # Keep newest max_count full dumps
    for i, f in enumerate(full):
        if i < max_count:
            kept.append(str(f))
        else:
            if not dry_run:
                try:
                    f.unlink()
                    deleted.append(str(f))
                except OSError as e:
                    deleted.append(f"{f}:unlink_fail:{e}")
            else:
                deleted.append(str(f))

    remaining = list_local_dumps(cfg)
    total_bytes = 0
    for f in remaining:
        try:
            total_bytes += f.stat().st_size
        except OSError:
            pass

    return {
        "ok": len([p for p in remaining if p.stat().st_size >= min_bytes]) <= max_count
              and total_bytes <= max_total,
        "dry_run": dry_run,
        "kept": kept,
        "deleted": deleted,
        "partials_removed": partials,
        "remaining_count": len(remaining),
        "remaining_full": sum(1 for p in remaining if p.stat().st_size >= min_bytes),
        "total_bytes": total_bytes,
        "max_count": max_count,
        "max_total_bytes": max_total,
        "over_bytes": total_bytes > max_total,
    }


def status_local(cfg: dict) -> dict:
    min_bytes = int(cfg.get("min_bytes") or 500_000_000)
    files = list_local_dumps(cfg)
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
            continue
    return {
        "count": len(items),
        "full_count": sum(1 for i in items if i["full"]),
        "total_bytes": total,
        "newest_age_hours": newest_age_h,
        "files": items[:20],
        "max_count": int(cfg.get("max_count") or 1),
        "max_total_bytes": int(cfg.get("max_total_bytes") or 0),
        "compliant": sum(1 for i in items if i["full"]) <= int(cfg.get("max_count") or 1),
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
