#!/usr/bin/env python3
"""tmp_scratch_cleanup.py — keep pytest scratch from exhausting /tmp inodes.

WHY THIS EXISTS
---------------
2026-10-13: /tmp (tmpfs) reached 1,048,574 of 1,048,576 inodes. 495k of them were empty
`tradeai_*_tests_*` dirs that tests/conftest.py created at import in every pytest process
and never removed. Live cron jobs then failed to create their /tmp lock files
("flock: cannot open lock file /tmp/tradeai_finviz_momentum_scalp.lock: No space left on
device"). The conftest leak is fixed at source; this weekly sweep removes what older
checkouts, killed processes and other worktrees still leave behind.

WHAT IT TOUCHES — nothing else
------------------------------
Only TOP-LEVEL entries of --root (default: tempfile.gettempdir()) whose name matches
SCRATCH_RE, that are real directories (never symlinks) owned by the current uid:

  * EMPTY and older than 1 day       -> rmdir
  * NON-EMPTY and older than 7 days  -> archived to --archive-dir/<YYYYMMDD>/ as a tar.gz
                                         with a MANIFEST.json; the archive is re-read and must
                                         list every entry before the dir is removed
  * anything younger                 -> kept

Every other top-level entry (lock files, claude-*, emergency-*, other agents' dirs) is only
COUNTED, as unmanaged_top_level. Default is a dry run; --apply acts.

ALARM
-----
After the sweep, inode use of --root is read with os.statvfs. Above INODE_ALARM_PCT the run
prints an INCIDENT line, records ok=false in its receipt and exits 3, so the condition is
loud long before 100% again.

Receipt: <state-root>/data/runtime/tmp_scratch_cleanup_last.json
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (--apply). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "tmp-scratch-cleanup"
    _dr_would = (
        "rmdir empty tradeai_*_tests_* scratch dirs older than 1 day and archive-then-remove non-empty ones "
        "older than 7 days under --root (with --apply), check /tmp inode use and write its receipt"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="scratch_dir"))
    raise SystemExit(0)

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

SCHEMA = "TmpScratchCleanupReceipt@v1"
SCRATCH_RE = re.compile(
    r"^tradeai_(audit_ledger|comms_mode|comms_fail_mode|operator_artifacts|portfolio_reports)_tests_"
    r"|^tradeai_no_pgpass_|^tradeai_hermetic_env_|^tradeai_pytest_scratch_"
)
EMPTY_MIN_AGE = timedelta(days=1)
NONEMPTY_MIN_AGE = timedelta(days=7)
INODE_ALARM_PCT = 80.0
EXIT_INODE_ALARM = 3
RECEIPT_REL = Path("data/runtime/tmp_scratch_cleanup_last.json")
SCHEDULED_ENTRYPOINT = "cron: 30 3 * * 0 -- weekly Sun 03:30 ET, packets/tmp-scratch-cleanup (operator-approved 2026-10-13)"


def _default_state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    return Path(env) if env else Path.home() / "trade-ai-releases" / "persistent-state"


def inode_use_pct(root: Path, statvfs: Callable[[str], os.statvfs_result] = os.statvfs) -> float | None:
    st = statvfs(str(root))
    if not st.f_files:
        return None
    return round(100.0 * (st.f_files - st.f_ffree) / st.f_files, 2)


def _managed(entry: os.DirEntry, uid: int) -> bool:
    if not SCRATCH_RE.match(entry.name):
        return False
    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
        return False
    return entry.stat(follow_symlinks=False).st_uid == uid


def _is_empty(path: Path) -> bool:
    with os.scandir(path) as it:
        return next(it, None) is None


def _archive(paths: list[Path], archive_dir: Path, now: datetime) -> dict:
    day = archive_dir / now.strftime("%Y%m%d")
    day.mkdir(parents=True, exist_ok=True)
    tar_path = day / f"tmp-scratch-{now.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    members: list[str] = []
    with tarfile.open(tar_path, "w:gz") as tar:
        for path in paths:
            tar.add(str(path), arcname=path.name, recursive=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        listed = set(tar.getnames())
    for path in paths:
        for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
            rel = Path(dirpath).relative_to(path.parent)
            members.append(rel.as_posix())
            members.extend((rel / name).as_posix() for name in filenames)
    missing = sorted(set(members) - listed)
    if missing:
        raise RuntimeError(f"archive {tar_path} is missing {len(missing)} entries, e.g. {missing[:3]}")
    digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    manifest = {
        "schema": "TmpScratchArchiveManifest@v1",
        "archive": str(tar_path),
        "sha256": digest,
        "created_at": now.isoformat(),
        "dirs": [{"path": str(p), "entries": sum(1 for _ in os.walk(p))} for p in paths],
        "note": "Archived by scripts/tmp_scratch_cleanup.py before removal from /tmp (never deleted unarchived).",
    }
    (day / f"{tar_path.stem}.MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return {"archive": str(tar_path), "sha256": digest, "dirs": len(paths)}


def sweep(
    root: Path,
    *,
    apply: bool,
    now: datetime,
    archive_dir: Path,
    statvfs: Callable[[str], os.statvfs_result] = os.statvfs,
) -> dict:
    uid = os.getuid()
    report: dict = {
        "root": str(root),
        "mode": "apply" if apply else "dry-run",
        "inode_use_pct_before": inode_use_pct(root, statvfs),
        "empty_removed": 0,
        "empty_would_remove": 0,
        "archived_dirs": 0,
        "archive_would_take": 0,
        "kept_young": 0,
        "unmanaged_top_level": 0,
        "archives": [],
        "errors": [],
    }
    to_archive: list[Path] = []
    with os.scandir(root) as it:
        entries = list(it)
    for entry in entries:
        if not _managed(entry, uid):
            report["unmanaged_top_level"] += 1
            continue
        path = Path(entry.path)
        age = now - datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime, tz=timezone.utc)
        try:
            empty = _is_empty(path)
        except OSError as exc:
            report["errors"].append(f"{entry.name}: {exc}")
            continue
        if empty and age >= EMPTY_MIN_AGE:
            if apply:
                try:
                    path.rmdir()
                    report["empty_removed"] += 1
                except OSError as exc:  # raced with a writer: keep it, record it
                    report["errors"].append(f"{entry.name}: {exc}")
            else:
                report["empty_would_remove"] += 1
        elif not empty and age >= NONEMPTY_MIN_AGE:
            if apply:
                to_archive.append(path)
            else:
                report["archive_would_take"] += 1
        else:
            report["kept_young"] += 1
    if to_archive:
        report["archives"].append(_archive(to_archive, archive_dir, now))
        for path in to_archive:
            shutil.rmtree(path)
        report["archived_dirs"] = len(to_archive)
    report["inode_use_pct_after"] = inode_use_pct(root, statvfs)
    return report


def write_receipt(state_root: Path, doc: dict) -> Path:
    path = state_root / RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: list[str] | None = None, *, statvfs: Callable[[str], os.statvfs_result] = os.statvfs) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="act (default: dry run, nothing removed)")
    ap.add_argument("--root", type=Path, default=Path(tempfile.gettempdir()))
    ap.add_argument("--archive-dir", type=Path, default=Path.home() / "archive" / "tmp-scratch")
    ap.add_argument("--state-root", type=Path, default=None)
    ap.add_argument("--now", default=None, help="ISO time (tests)")
    args = ap.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    started = datetime.now(timezone.utc)
    report = sweep(args.root, apply=args.apply, now=now, archive_dir=args.archive_dir, statvfs=statvfs)
    after = report["inode_use_pct_after"]
    alarm = after is not None and after > INODE_ALARM_PCT
    doc = {
        "schema": SCHEMA,
        "lane_id": "tmp-scratch-cleanup",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ok": not alarm and not report["errors"],
        "inode_alarm_pct": INODE_ALARM_PCT,
        "inode_alarm": alarm,
        **report,
    }
    receipt = write_receipt(args.state_root or _default_state_root(), doc)
    print(json.dumps({k: doc[k] for k in doc if k != "archives"} | {"receipt": str(receipt)}))
    if alarm:
        print(
            f"INCIDENT tmp-scratch-cleanup: {args.root} inode use {after}% > {INODE_ALARM_PCT}% after sweep "
            f"(unmanaged_top_level={report['unmanaged_top_level']}); find what fills it before jobs lose their locks",
            file=sys.stderr,
        )
        return EXIT_INODE_ALARM
    return 0


if __name__ == "__main__":
    sys.exit(main())
