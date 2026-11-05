#!/usr/bin/env python3
"""backup_enforcer.py — one DB dump on this host, N+1 on Drive, verified before anything is removed.

AGENTS.md §0 rule 6 exception (d) and §24.15; DSN-20261030-workspace-lifecycle P4-T1/P4-T2.

Host: exactly ``local_pg.keep_on_host`` completed dumps stay (the newest). Every older dump, top level or under
``archive/``, is REMOVED (unlinked; a same-disk move frees nothing) — but only after the newest dump

  (a) passes ``gzip -t`` (result cached by device+inode+size+mtime, so it is not re-run hourly), and
  (b) is verified on Drive: the upload ledger written by ``--verify-upload`` names the Drive object made from
      exactly this file (name, size, mtime, inode, md5), and Drive shows that object with the same name, size
      and md5 (Drive md5 is computed by streaming the object through a FIFO — gog does not expose
      md5Checksum — and cached by Drive id+size+modifiedTime).

If any check fails or cannot be made, nothing is removed, the reason is written to the receipt, and the
operator is alerted once per condition (telegram_alert + lib/alert_condition_state dedupe) until it clears.
Never touched: directories (hold-*, m5_*), symlinks, hardlinked files, *.part, young dumps, the newest
dump, dumps newer than the newest complete dump, anything outside ``dir`` and ``dir/archive``,
``archive/TRIPWIRE.txt``.

Drive: the newest ``drive_db.keep_n + 1`` ``<prefix>_*`` objects stay. Older ones are deleted only after the
newest Drive object is verified against the host's upload ledger (name, size, md5) and the listing is
complete (no further page).

Usage:
  python scripts/backup_enforcer.py                  # enforce (host + Drive per policy), receipt, alerts
  python scripts/backup_enforcer.py --dry-run        # read-only: every check, no removal, no state written
  python scripts/backup_enforcer.py --status         # JSON local status only (no Drive, no gzip)
  python scripts/backup_enforcer.py --drive-db       # also prune Drive even if drive_db.prune_enabled is false
  python scripts/backup_enforcer.py --verify-upload --source DUMP --plaintext COPY --encrypted ENC
                                                     # uploader gate: Drive object must match name/size/md5

Policy: config/backup_policy.yaml (local_pg, drive_db, verification).
"""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_policy() -> dict:
    p = ROOT / "config" / "backup_policy.yaml"
    try:
        import yaml
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        # Legacy minimal fallback for the local cap only. Without the `verification` block nothing is ever
        # removed (enforce refuses with policy_incomplete) — removal needs the reviewed policy file.
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


# A dump pg_dump is still writing is small and young, or still named *.part. D8.2: never touch those.
DEFAULT_SKIP_YOUNGER_S = 2 * 60 * 60
_PART_SUFFIXES = (".part", ".partial")


def _is_in_progress(path: Path, *, now: float, min_bytes: int, skip_younger_s: float) -> bool:
    """A dump still being written, or finished so recently the next hourly pass must not touch it."""
    del min_bytes
    if path.name.endswith(_PART_SUFFIXES):
        return True
    try:
        st = path.stat()
    except OSError:
        return True
    return (now - st.st_mtime) < skip_younger_s


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




# ── N+1 enforcement (DSN-20261030-workspace-lifecycle P4-T1/P4-T2) ──────────────────────────────────────────────

class PolicyError(ValueError):
    """A required policy key is missing: enforcement refuses (removes nothing)."""


class DriveError(RuntimeError):
    """Drive could not be listed, read or changed."""


class RemovalRefused(RuntimeError):
    """A candidate changed between inventory and removal; it is kept."""


_VERIFICATION_KEYS = (
    "gzip_timeout_s", "drive_md5_timeout_s", "drive_unreachable_grace_hours", "newest_unverified_grace_hours",
    "ledger_path", "ledger_max_records", "cache_path", "cache_max_entries", "receipt_path", "removals_log_path",
    "lock_path", "fifo_dir", "alert_realert_minutes",
)
_DRIVE_KEYS = ("folder_id", "prefix", "keep_n", "gog_bin", "keyring_password_file", "list_max",
               "command_timeout_s", "prune_enabled")
#: The Drive account is never in a committed config (public repo): drive_db.account_source names the uploader script
#: whose ACCT="..." line it reads, so the enforcer and backup_secrets_state.sh always use the same account.
_ACCT_LINE = re.compile(r'^ACCT="([^"]+)"\s*$', re.M)
_LOCAL_KEYS = ("dir", "pattern", "keep_on_host", "min_bytes", "max_total_bytes", "skip_younger_than_s")

# Reasons that mean "the newest dump simply has not been offsited yet" (waits out the grace window).
_PENDING_REASONS = frozenset({"no_upload_record", "drive_object_missing"})
# Reasons that point at corruption or a wrong copy: page at P1.
_P1_REASONS = frozenset({"newest_gzip_failed", "local_md5_mismatch", "drive_md5_mismatch", "drive_size_mismatch",
                         "upload_record_source_mismatch", "removal_error", "drive_delete_error"})

CONDITION_HOST = "backup_retention:host"
CONDITION_DRIVE = "backup_retention:drive"
CONDITION_UPLOAD = "backup_retention:upload"


def _require(cfg: dict, keys: tuple[str, ...], section: str) -> dict:
    missing = [k for k in keys if cfg.get(k) is None]
    if missing:
        raise PolicyError(f"{section}.{','.join(missing)}")
    return cfg


def load_sections(policy: dict) -> tuple[dict, dict, dict]:
    """(local_pg, drive_db, verification) with every key enforcement needs, or PolicyError."""
    local = _require(dict(policy.get("local_pg") or {}), _LOCAL_KEYS, "local_pg")
    drive = _require(dict(policy.get("drive_db") or {}), _DRIVE_KEYS, "drive_db")
    if not drive.get("account"):
        src = drive.get("account_source")
        if not src:
            raise PolicyError("drive_db.account_source")
        try:
            m = _ACCT_LINE.search(_repo_path(str(src)).read_text(encoding="utf-8"))
        except OSError:
            m = None
        if not m:
            raise PolicyError("drive_db.account_source unreadable or has no ACCT line")
        drive["account"] = m.group(1)
    ver = _require(dict(policy.get("verification") or {}), _VERIFICATION_KEYS, "verification")
    if int(local["keep_on_host"]) < 1 or int(drive["keep_n"]) < 0:
        raise PolicyError("keep_on_host>=1 and keep_n>=0 required")
    return local, drive, ver


def _utc_iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, tz=timezone.utc).isoformat()


def _repo_path(p: str) -> Path:
    q = Path(os.path.expanduser(str(p)))
    return q if q.is_absolute() else ROOT / q


def _file_key(st: os.stat_result) -> str:
    return f"{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}"


def _write_json(path: Path, doc: Any) -> None:
    from scripts.lib.atomic_json_store import atomic_write_json  # noqa: PLC0415
    atomic_write_json(path, doc)


class StateCache:
    """gzip -t results, local md5s, Drive md5s and the Drive-unreachable clock. Saved only by live runs."""

    _SECTIONS = ("gzip", "md5", "drive_md5")

    def __init__(self, path: Path, max_entries: int) -> None:
        self.path, self.max_entries = Path(path), int(max_entries)
        doc: dict = {}
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        self.data: dict = {s: dict(doc.get(s) or {}) if isinstance(doc.get(s), dict) else {} for s in self._SECTIONS}
        self.data["drive_unreachable_since"] = doc.get("drive_unreachable_since")

    def get(self, section: str, key: str) -> Any:
        return self.data[section].get(key)

    def put(self, section: str, key: str, value: Any) -> None:
        sec = self.data[section]
        sec.pop(key, None)
        sec[key] = value
        while len(sec) > self.max_entries:
            sec.pop(next(iter(sec)))

    def save(self) -> None:
        _write_json(self.path, self.data)


def gzip_test(path: Path, st: os.stat_result, cache: StateCache, timeout_s: float) -> tuple[str, str]:
    """('ok'|'failed'|'unavailable', detail). Cached by device+inode+size+mtime."""
    key = _file_key(st)
    hit = cache.get("gzip", key)
    if isinstance(hit, dict) and "ok" in hit:
        return ("ok" if hit["ok"] else "failed"), "cached"
    try:
        proc = subprocess.run(["gzip", "-t", "--", str(path)], capture_output=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unavailable", type(exc).__name__
    try:
        if _file_key(os.lstat(path)) != key:
            return "unavailable", "changed_during_test"
    except OSError:
        return "unavailable", "vanished_during_test"
    ok = proc.returncode == 0
    cache.put("gzip", key, {"ok": ok, "at": _utc_iso()})
    return ("ok" if ok else "failed"), f"rc={proc.returncode}"


def _md5_of(path: Path, expect_key: Optional[str] = None) -> Optional[str]:
    """md5 of a regular file read without following a symlink; None if it changed or is unreadable."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        before = os.fstat(fh.fileno())
        if expect_key is not None and _file_key(before) != expect_key:
            return None
        h = hashlib.md5()  # noqa: S324 - integrity comparison with Drive, not security
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
        if _file_key(os.fstat(fh.fileno())) != _file_key(before):
            return None
    return h.hexdigest()


def file_md5(path: Path, st: os.stat_result, cache: StateCache) -> Optional[str]:
    key = _file_key(st)
    hit = cache.get("md5", key)
    if isinstance(hit, str):
        return hit
    md5 = _md5_of(path, key)
    if md5:
        cache.put("md5", key, md5)
    return md5


class GogDrive:
    """``gog drive`` as scripts/backup_secrets_state.sh uses it (same account, folder, binary). The keyring
    password reaches gog through a bash wrapper that reads the file in the child; it is never in this process,
    an argv, a log or a receipt. gog exposes no md5Checksum, so md5 is computed by streaming the object
    through a FIFO (no bytes land on disk)."""

    def __init__(self, dcfg: dict, vcfg: dict) -> None:
        self.gog = Path(os.path.expanduser(str(dcfg["gog_bin"])))
        self.account = str(dcfg["account"])
        self.folder = str(dcfg["folder_id"])
        self.keyring_pw_file = Path(os.path.expanduser(str(dcfg["keyring_password_file"])))
        self.list_max = int(dcfg["list_max"])
        self.cmd_timeout = float(dcfg["command_timeout_s"])
        self.md5_timeout = float(vcfg["drive_md5_timeout_s"])
        self.fifo_dir = Path(os.path.expanduser(str(vcfg["fifo_dir"])))

    def _cmd(self, *args: str) -> list[str]:
        wrapper = 'GOG_KEYRING_PASSWORD="$(cat "$1")"; export GOG_KEYRING_PASSWORD; shift; exec "$@"'
        return ["bash", "-c", wrapper, "gog-wrapper", str(self.keyring_pw_file), str(self.gog), "drive", *args,
                "-a", self.account, "-j", "--no-input"]

    def _run(self, *args: str, timeout: float) -> subprocess.CompletedProcess:
        if not self.gog.exists():
            raise DriveError("gog CLI not found")
        try:
            return subprocess.run(self._cmd(*args), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise DriveError(f"gog drive {args[0]} timeout") from exc
        except OSError as exc:
            raise DriveError(f"gog drive {args[0]} {type(exc).__name__}") from exc

    def list(self, prefix: str) -> dict:
        q = f"name contains '{prefix}_' and trashed = false"
        proc = self._run("ls", "--parent", self.folder, "--query", q, "--max", str(self.list_max),
                         timeout=self.cmd_timeout)
        if proc.returncode != 0:
            raise DriveError(f"gog drive ls rc={proc.returncode}")
        try:
            doc = json.loads(proc.stdout or "null")
        except ValueError as exc:
            raise DriveError("gog drive ls returned non-JSON") from exc
        files = doc.get("files") if isinstance(doc, dict) else None
        if not isinstance(files, list):
            raise DriveError("gog drive ls returned no file list")
        out = []
        for f in files:
            if not isinstance(f, dict) or not f.get("id") or not f.get("name"):
                continue
            size = f.get("size")
            out.append({"id": str(f["id"]), "name": str(f["name"]),
                        "size": int(size) if str(size or "").isdigit() else None,
                        "modifiedTime": f.get("modifiedTime")})
        return {"files": out, "complete": not (isinstance(doc, dict) and doc.get("nextPageToken"))}

    def md5(self, file_id: str) -> tuple[str, int]:
        self.fifo_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.fifo_dir) as td:
            fifo = Path(td) / "stream"
            os.mkfifo(fifo, 0o600)
            got: dict = {}

            def _reader() -> None:
                h = hashlib.md5()  # noqa: S324 - integrity comparison
                n = 0
                try:
                    with open(fifo, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 22), b""):
                            h.update(chunk)
                            n += len(chunk)
                    got["md5"], got["bytes"] = h.hexdigest(), n
                except OSError as exc:
                    got["error"] = type(exc).__name__

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()
            rc: Any = None
            try:
                rc = self._run("download", file_id, "--out", str(fifo), timeout=self.md5_timeout).returncode
            finally:
                if reader.is_alive():  # gog never opened the FIFO: release the reader's open()
                    with contextlib.suppress(OSError):
                        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
                reader.join(timeout=60)
            if rc != 0 or "md5" not in got:
                raise DriveError(f"gog drive download rc={rc} {got.get('error', '')}".strip())
            return got["md5"], int(got["bytes"])

    def delete(self, file_id: str) -> None:
        proc = self._run("rm", file_id, "-y", "--permanent", timeout=self.cmd_timeout)
        if proc.returncode != 0:
            raise DriveError(f"gog drive rm rc={proc.returncode}")


# ── upload ledger: what this host encrypted and uploaded, and what Drive was verified to hold ──────────────────

def load_ledger(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("records"), list):
            return doc
    except (OSError, ValueError):
        pass
    return {"records": []}


def ledger_for_source(ledger: dict, name: str) -> Optional[dict]:
    hits = [r for r in ledger.get("records", []) if (r.get("source") or {}).get("name") == name]
    return hits[-1] if hits else None


def ledger_for_drive(ledger: dict, drive_name: str) -> Optional[dict]:
    hits = [r for r in ledger.get("records", []) if (r.get("drive") or {}).get("name") == drive_name]
    return hits[-1] if hits else None


def drive_md5_cached(drive: Any, obj: dict, cache: StateCache) -> str:
    key = f"{obj['id']}:{obj.get('size')}:{obj.get('modifiedTime')}"
    hit = cache.get("drive_md5", key)
    if isinstance(hit, str):
        return hit
    md5, nbytes = drive.md5(obj["id"])
    if obj.get("size") is not None and nbytes != obj["size"]:
        raise DriveError(f"stream bytes {nbytes} != listed size {obj['size']}")
    cache.put("drive_md5", key, md5)
    return md5


def verify_drive_object(obj: dict, ledger: dict, drive: Any, cache: StateCache) -> dict:
    """A Drive object is verified when the host's upload ledger names it and its size and md5 match."""
    out: dict = {"drive_name": obj["name"], "drive_id": obj["id"], "drive_size": obj.get("size")}
    rec = ledger_for_drive(ledger, obj["name"])
    if rec is None:
        return {**out, "verified": False, "reason": "no_upload_record"}
    want = rec["drive"]
    if obj.get("size") is None or int(obj["size"]) != int(want["size"]):
        return {**out, "verified": False, "reason": "drive_size_mismatch", "expected_size": want["size"]}
    try:
        md5 = drive_md5_cached(drive, obj, cache)
    except (DriveError, OSError) as exc:
        return {**out, "verified": False, "reason": "drive_md5_unavailable", "detail": str(exc)[:200]}
    if md5 != want["md5"]:
        return {**out, "verified": False, "reason": "drive_md5_mismatch"}
    return {**out, "verified": True, "reason": "verified", "md5": md5, "source_name": rec["source"]["name"]}


def verify_newest_offsite(path: Path, st: os.stat_result, *, ledger: dict, listing: Optional[dict], drive: Any,
                          cache: StateCache, vcfg: dict) -> dict:
    """The newest host dump may succeed older copies only if it is intact and its Drive copy is proven."""
    out: dict = {"path": str(path), "bytes": st.st_size}
    g, detail = gzip_test(path, st, cache, float(vcfg["gzip_timeout_s"]))
    out["gzip"] = {"result": g, "detail": detail}
    if g == "failed":
        return {**out, "verified": False, "reason": "newest_gzip_failed"}
    if g != "ok":
        return {**out, "verified": False, "reason": "gzip_unavailable"}
    rec = ledger_for_source(ledger, path.name)
    if rec is None:
        return {**out, "verified": False, "reason": "no_upload_record"}
    src = rec["source"]
    if (int(src["size"]), int(src["mtime_ns"]), int(src["ino"])) != (st.st_size, st.st_mtime_ns, st.st_ino):
        return {**out, "verified": False, "reason": "upload_record_source_mismatch"}
    md5 = file_md5(path, st, cache)
    if md5 is None:
        return {**out, "verified": False, "reason": "local_md5_unavailable"}
    if md5 != src["md5"]:
        return {**out, "verified": False, "reason": "local_md5_mismatch"}
    if listing is None:
        return {**out, "verified": False, "reason": "drive_unreachable"}
    matches = [f for f in listing["files"] if f["name"] == rec["drive"]["name"]]
    if not matches:
        reason = "drive_object_missing" if listing.get("complete") else "drive_listing_incomplete"
        return {**out, "verified": False, "reason": reason, "drive_name": rec["drive"]["name"]}
    if len(matches) > 1:
        return {**out, "verified": False, "reason": "drive_object_ambiguous", "drive_name": rec["drive"]["name"]}
    dv = verify_drive_object(matches[0], ledger, drive, cache)
    return {**out, **{k: v for k, v in dv.items() if k != "source_name"}}


# ── host inventory and removal ────────────────────────────────────────────────────────────────────────────────

def inventory_host(cfg: dict, *, now: float) -> dict:
    """Direct entries of dir and dir/archive that match the dump pattern, classified. Never descends further."""
    pattern = str(cfg["pattern"])
    min_bytes = int(cfg["min_bytes"])
    skip_younger_s = float(cfg["skip_younger_than_s"])
    raw = Path(os.path.expanduser(str(cfg["dir"])))
    inv: dict = {"complete": [], "undersized": [], "protected": [], "skipped_in_progress": [], "errors": [],
                 "dirs": []}
    if raw.is_symlink() or not raw.is_dir():
        inv["errors"].append(f"live_dir_unavailable:{raw}")
        return inv
    live = raw.resolve()
    dirs = [live]
    archive = live / "archive"
    if archive.is_symlink():
        inv["protected"].append({"path": str(archive), "reason": "archive_is_symlink"})
    elif archive.is_dir():
        dirs.append(archive)
    inv["dirs"] = [str(d) for d in dirs]
    for d in dirs:
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError as exc:
            inv["errors"].append(f"scan_failed:{d}:{type(exc).__name__}")
            continue
        for e in entries:
            if not fnmatch.fnmatch(e.name, pattern):
                continue
            p = d / e.name
            try:
                st = os.lstat(p)
            except OSError:
                inv["protected"].append({"path": str(p), "reason": "stat_failed"})
                continue
            item = {"path": str(p), "name": e.name, "bytes": st.st_size, "mtime": st.st_mtime,
                    "key": _file_key(st), "location": "archive" if d == archive else "top"}
            if stat.S_ISLNK(st.st_mode):
                reason = "symlink"
            elif stat.S_ISDIR(st.st_mode):
                reason = "directory"
            elif not stat.S_ISREG(st.st_mode):
                reason = "not_regular_file"
            elif st.st_nlink > 1:
                reason = "hardlinked"
            elif e.name.endswith(_PART_SUFFIXES):
                reason = "partial_name"
                inv["skipped_in_progress"].append(str(p))
            elif (now - st.st_mtime) < skip_younger_s:
                reason = "young"
                inv["skipped_in_progress"].append(str(p))
            elif st.st_size < min_bytes:
                inv["undersized"].append(item)
                continue
            else:
                inv["complete"].append(item)
                continue
            inv["protected"].append({**item, "reason": reason})
    inv["complete"].sort(key=lambda i: i["mtime"], reverse=True)
    return inv


def _remove_dump(path: Path, key: str, allowed_dirs: list[str]) -> None:
    """Unlink one dump only if it is still the exact regular, single-link file the inventory saw."""
    if str(path.parent) not in allowed_dirs or path.parent.is_symlink():
        raise RemovalRefused("outside_allowed_dirs")
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or _file_key(st) != key:
        raise RemovalRefused("changed_since_inventory")
    os.unlink(path)


def enforce_local(cfg: dict, *, dry_run: bool = False, now: Optional[float] = None,
                  verify: Optional[Callable[[Path, os.stat_result], dict]] = None,
                  removals_log: Optional[Path] = None) -> dict:
    """Keep the newest ``keep_on_host`` complete dumps; remove older ones only if ``verify`` proves the newest."""
    cfg = dict(cfg)
    cfg.setdefault("skip_younger_than_s", DEFAULT_SKIP_YOUNGER_S)
    cfg.setdefault("keep_on_host", cfg.get("max_count") or 1)
    keep_on_host = int(cfg["keep_on_host"])
    min_bytes = int(cfg.get("min_bytes") or 0)
    max_total = int(cfg.get("max_total_bytes") or 0)
    now = time.time() if now is None else now
    inv = inventory_host(cfg, now=now)
    kept = inv["complete"][:keep_on_host]
    candidates: list[dict] = []
    protected = list(inv["protected"])
    if kept:
        cutoff = kept[-1]["mtime"]
        candidates = inv["complete"][keep_on_host:]
        for u in inv["undersized"]:
            if u["mtime"] < cutoff:
                candidates.append(u)
            else:
                protected.append({**u, "reason": "undersized_not_older_than_newest"})
    else:
        protected.extend({**u, "reason": "no_complete_dump"} for u in inv["undersized"])
    newest = kept[0] if kept else None

    if inv["errors"]:
        verification = {"verified": False, "reason": "host_inventory_error"}
    elif newest is None:
        verification = {"verified": False, "reason": "no_complete_dump"}
    elif verify is None:
        verification = {"verified": False, "reason": "drive_verification_unavailable"}
    else:
        try:
            st = os.lstat(newest["path"])
            if _file_key(st) != newest["key"]:
                verification = {"verified": False, "reason": "newest_changed_during_run"}
            else:
                verification = verify(Path(newest["path"]), st)
        except OSError as exc:
            verification = {"verified": False, "reason": "newest_unreadable", "detail": type(exc).__name__}

    removed: list[dict] = []
    errors: list[dict] = []
    refused = None
    if candidates and not verification.get("verified"):
        refused = verification.get("reason")
    elif candidates:
        for c in candidates:
            row = {"path": c["path"], "bytes": c["bytes"], "mtime": _utc_iso(c["mtime"]),
                   "successor": newest["path"], "successor_drive": verification.get("drive_name")}
            if dry_run:
                removed.append({**row, "action": "would_remove"})
                continue
            try:
                _remove_dump(Path(c["path"]), c["key"], inv["dirs"])
            except (OSError, RemovalRefused) as exc:
                errors.append({**row, "error": f"{type(exc).__name__}:{exc}"[:200]})
                continue
            row = {**row, "action": "removed", "at": _utc_iso()}
            removed.append(row)
            if removals_log is not None:
                with contextlib.suppress(OSError):
                    from scripts.lib.atomic_json_store import append_jsonl  # noqa: PLC0415
                    append_jsonl(removals_log, row)

    gone = {r["path"] for r in removed if r["action"] == "removed"}
    if dry_run:
        gone = {r["path"] for r in removed}
    remaining_full = [i for i in inv["complete"] if i["path"] not in gone]
    top_total = 0
    for f in list_local_dumps(cfg) if not inv["errors"] else []:
        with contextlib.suppress(OSError):
            top_total += f.stat().st_size
    storage = local_storage_usage(cfg)
    return {
        "ok": (not errors and not inv["errors"] and len(remaining_full) <= keep_on_host
               and (not max_total or top_total <= max_total) and storage["measurement_complete"]),
        "dry_run": dry_run,
        "keep_on_host": keep_on_host,
        "newest": newest and {k: newest[k] for k in ("path", "bytes")},
        "kept": [k["path"] for k in kept],
        "verification": verification,
        "candidates": [{"path": c["path"], "bytes": c["bytes"], "location": c["location"]} for c in candidates],
        "removed": removed,
        "removal_errors": errors,
        "refused": refused,
        "protected": [{"path": p["path"], "reason": p["reason"]} for p in protected],
        "skipped_in_progress": inv["skipped_in_progress"],
        "inventory_errors": inv["errors"],
        "remaining_full": len(remaining_full),
        "remaining_count": len(inv["complete"]) + len(inv["undersized"]) - len(gone),
        "total_bytes": top_total,
        "max_total_bytes": max_total,
        "over_bytes": bool(max_total) and top_total > max_total,
        "min_bytes": min_bytes,
        "storage": storage,
    }


def status_drive_newest(listing: dict, prefix: str) -> list[dict]:
    objs = [f for f in listing["files"] if f["name"].startswith(prefix + "_")]
    return sorted(objs, key=lambda f: f["name"], reverse=True)  # name embeds YYYYMMDD_HHMMSS


def enforce_drive_db(dcfg: dict, *, dry_run: bool = False, listing: Optional[dict] = None, drive: Any = None,
                     ledger: Optional[dict] = None, cache: Optional[StateCache] = None, prune: bool = True) -> dict:
    """Keep the newest keep_n+1 Drive dumps; delete older ones only after the newest is verified."""
    prefix = str(dcfg["prefix"])
    keep_total = int(dcfg["keep_n"]) + 1
    if listing is None or drive is None or ledger is None or cache is None:
        return {"ok": False, "refused": "drive_unreachable", "deleted": [], "kept": []}
    objs = status_drive_newest(listing, prefix)
    keep, drop = objs[:keep_total], objs[keep_total:]
    out: dict = {"dry_run": dry_run, "keep_n_plus_one": keep_total, "listing_complete": bool(listing["complete"]),
                 "kept": [{"name": o["name"], "size": o["size"]} for o in keep],
                 "candidates": [{"name": o["name"], "size": o["size"]} for o in drop],
                 "deleted": [], "delete_errors": [], "refused": None, "newest": None}
    if not objs:
        out.update(ok=False, refused="no_drive_objects")
        return out
    newest = verify_drive_object(objs[0], ledger, drive, cache)
    out["newest"] = newest
    if not listing["complete"]:
        out["refused"] = "drive_listing_incomplete"
    elif not newest["verified"]:
        out["refused"] = f"newest_drive_unverified:{newest['reason']}"
    elif not prune:
        out["refused"] = "prune_disabled" if drop else None
    elif drop:
        for o in drop:
            if dry_run:
                out["deleted"].append({"name": o["name"], "size": o["size"], "action": "would_delete"})
                continue
            try:
                drive.delete(o["id"])
                out["deleted"].append({"name": o["name"], "size": o["size"], "action": "deleted", "at": _utc_iso()})
            except (DriveError, OSError) as exc:
                out["delete_errors"].append({"name": o["name"], "error": str(exc)[:200]})
    remaining = len(objs) - len([d for d in out["deleted"] if d["action"] == "deleted"])
    out["remaining"] = remaining
    out["ok"] = (not out["delete_errors"] and newest["verified"]
                 and (remaining <= keep_total or (dry_run and len(out["deleted"]) == len(drop))))
    return out


# ── alerting ──────────────────────────────────────────────────────────────────────────────────────────────────

def default_notify(text: str, priority: str) -> str:
    try:
        from telegram_alert import send_telegram  # noqa: PLC0415 (host-only lane)
        ok = send_telegram(text, message_class="operator_alert", priority=priority, producer="backup_enforcer")
        return "accepted" if ok else "send_returned_false"
    except Exception as exc:  # noqa: BLE001 - alerting never raises past enforcement
        return f"error:{type(exc).__name__}"


def _hours_since_iso(stamp: Any, now: float) -> Optional[float]:
    try:
        return (now - datetime.fromisoformat(str(stamp)).timestamp()) / 3600.0
    except (TypeError, ValueError):
        return None


def classify(result: dict, *, now: float, vcfg: dict, unreachable_since: Optional[str]) -> dict:
    """Condition key -> (state, alertable, detail). Pending offsite and short Drive outages wait out their grace."""
    conds: dict = {}
    unreachable_h = _hours_since_iso(unreachable_since, now) if unreachable_since else None
    drive_down_alert = unreachable_h is not None and unreachable_h > float(vcfg["drive_unreachable_grace_hours"])

    local = result.get("local") or {}
    v = local.get("verification") or {}
    reason = v.get("reason")
    if local.get("removal_errors"):
        conds[CONDITION_HOST] = ("removal_error", True, f"{len(local['removal_errors'])} removal(s) failed")
    elif local.get("inventory_errors"):
        conds[CONDITION_HOST] = ("host_inventory_error", True, ";".join(local["inventory_errors"])[:200])
    elif v.get("verified"):
        conds[CONDITION_HOST] = ("ok", False, "newest dump verified on Drive")
    elif reason == "no_complete_dump":
        alert = not local.get("skipped_in_progress")
        conds[CONDITION_HOST] = ("no_complete_dump" if alert else "dump_in_progress", alert, "no complete dump")
    elif reason == "drive_unreachable":
        conds[CONDITION_HOST] = ("drive_unreachable" if drive_down_alert else "drive_unreachable_within_grace",
                                 drive_down_alert, f"Drive unreachable {unreachable_h or 0:.1f}h")
    elif reason in _PENDING_REASONS:
        newest = local.get("newest") or {}
        age_h = None
        with contextlib.suppress(OSError, TypeError):
            age_h = (now - os.lstat(newest["path"]).st_mtime) / 3600.0
        within = age_h is not None and age_h <= float(vcfg["newest_unverified_grace_hours"])
        conds[CONDITION_HOST] = ("pending_offsite" if within else reason, not within,
                                 f"newest dump {Path(str(newest.get('path'))).name} not verified on Drive"
                                 f" ({reason}, age {age_h or 0:.1f}h)")
    else:
        conds[CONDITION_HOST] = (str(reason), True, f"newest dump not verified: {reason}")

    drive = result.get("drive_db") or {}
    dreason = drive.get("refused")
    if result.get("drive_error"):
        conds[CONDITION_DRIVE] = ("drive_unreachable" if drive_down_alert else "drive_unreachable_within_grace",
                                  drive_down_alert, str(result["drive_error"])[:200])
    elif drive.get("delete_errors"):
        conds[CONDITION_DRIVE] = ("drive_delete_error", True, f"{len(drive['delete_errors'])} Drive delete(s) failed")
    elif dreason and drive.get("candidates") and dreason != "prune_disabled":
        conds[CONDITION_DRIVE] = (dreason.split(":")[0], True,
                                  f"{len(drive['candidates'])} older Drive dump(s) kept: {dreason}")
    else:
        conds[CONDITION_DRIVE] = ("ok", False, "Drive holds keep_n+1 or fewer, newest verified or nothing to prune")
    return conds


def raise_alerts(conds: dict, *, notify: Callable[[str, str], str], state_path: Optional[Path],
                 realert_minutes: Optional[int], receipt: str) -> dict:
    out: dict = {}
    try:
        from scripts.lib.alert_condition_state import observe  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}
    for key, (state, alertable, detail) in conds.items():
        try:
            obs = observe(key, state, alertable=alertable, path=state_path, min_realert_minutes=realert_minutes,
                          extra={"detail": detail})
        except Exception as exc:  # noqa: BLE001
            out[key] = {"state": state, "error": type(exc).__name__}
            continue
        rec: dict = {"state": state, "alertable": alertable, "action": obs.get("action"),
                     "notify": bool(obs.get("notify"))}
        if rec["notify"]:
            if alertable:
                prio = "P1" if state in _P1_REASONS else "P2"
                text = f"Backup retention {key.split(':')[1]}: {state} — {detail}. Nothing was removed. Receipt: {receipt}"
            else:
                prio = "P2"
                text = f"Backup retention {key.split(':')[1]} recovered ({state}): {detail}"
            rec["priority"] = prio
            rec["sent"] = notify(text, prio)
        out[key] = rec
    return out


# ── orchestration ─────────────────────────────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _lock(path: Path, *, blocking: bool):
    import fcntl  # noqa: PLC0415
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a")  # noqa: SIM115
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        fh.close()


def run(policy: dict, *, dry_run: bool = False, now: Optional[float] = None, drive: Any = None,
        notify: Optional[Callable[[str, str], str]] = None, alert_state_path: Optional[Path] = None,
        force_drive_prune: bool = False) -> dict:
    """One enforcement pass. Dry-run performs every read-only check and writes nothing (no cache, receipt, alert)."""
    now = time.time() if now is None else now
    started = _utc_iso(now)
    try:
        lcfg, dcfg, vcfg = load_sections(policy)
    except PolicyError as exc:
        res = {"ok": False, "dry_run": dry_run, "started_at": started, "refused": f"policy_incomplete:{exc}",
               "local": status_local(policy.get("local_pg") or {}), "alertable": True}
        if not dry_run:
            res["alerts"] = raise_alerts({CONDITION_HOST: ("policy_incomplete", True, str(exc))},
                                         notify=notify or default_notify, state_path=alert_state_path,
                                         realert_minutes=None, receipt="(none: policy incomplete)")
        return res
    cache = StateCache(_repo_path(vcfg["cache_path"]), int(vcfg["cache_max_entries"]))
    ledger = load_ledger(_repo_path(vcfg["ledger_path"]))
    drive = drive if drive is not None else GogDrive(dcfg, vcfg)
    listing: Optional[dict] = None
    drive_error = None
    try:
        listing = drive.list(str(dcfg["prefix"]))
        cache.data["drive_unreachable_since"] = None
    except (DriveError, OSError) as exc:
        drive_error = str(exc)[:300]
        cache.data["drive_unreachable_since"] = cache.data.get("drive_unreachable_since") or _utc_iso(now)

    def _verify(path: Path, st: os.stat_result) -> dict:
        return verify_newest_offsite(path, st, ledger=ledger, listing=listing, drive=drive, cache=cache, vcfg=vcfg)

    local = enforce_local(lcfg, dry_run=dry_run, now=now, verify=_verify,
                          removals_log=None if dry_run else _repo_path(vcfg["removals_log_path"]))
    prune = bool(dcfg.get("prune_enabled")) or force_drive_prune
    drive_res = enforce_drive_db(dcfg, dry_run=dry_run, listing=listing, drive=drive, ledger=ledger, cache=cache,
                                 prune=prune) if listing is not None else {
        "ok": False, "refused": "drive_unreachable", "deleted": [], "candidates": []}
    result: dict = {
        "schema": "backup_enforcer_receipt@v2",
        "started_at": started,
        "finished_at": _utc_iso(),
        "dry_run": dry_run,
        "policy": {"keep_on_host": int(lcfg["keep_on_host"]), "drive_keep_n_plus_one": int(dcfg["keep_n"]) + 1},
        "local": local,
        "drive_db": drive_res,
        "drive_error": drive_error,
        "drive_unreachable_since": cache.data.get("drive_unreachable_since"),
    }
    conds = classify(result, now=now, vcfg=vcfg, unreachable_since=cache.data.get("drive_unreachable_since"))
    result["conditions"] = {k: {"state": s, "alertable": a, "detail": d} for k, (s, a, d) in conds.items()}
    result["alertable"] = any(a for (_, a, _) in conds.values())
    result["ok"] = bool(local.get("ok")) and bool(drive_res.get("ok")) and not result["alertable"]
    if not dry_run:
        receipt = _repo_path(vcfg["receipt_path"])
        result["alerts"] = raise_alerts(conds, notify=notify or default_notify, state_path=alert_state_path,
                                        realert_minutes=int(vcfg["alert_realert_minutes"]), receipt=str(receipt))
        with contextlib.suppress(OSError):
            cache.save()
        try:
            _write_json(receipt, result)
            result["receipt"] = str(receipt)
        except OSError as exc:
            result["receipt_error"] = type(exc).__name__
    return result


def verify_upload(policy: dict, *, source: Path, plaintext: Path, encrypted: Path, drive: Any = None,
                  notify: Optional[Callable[[str, str], str]] = None,
                  alert_state_path: Optional[Path] = None) -> dict:
    """P4-T2 uploader gate: success only if Drive holds exactly one object named like the encrypted file with
    its size and md5, and the encrypted plaintext is byte-identical to the host dump. Records the ledger entry
    backup_enforcer later requires before removing anything."""
    _, dcfg, vcfg = load_sections(policy)
    cache = StateCache(_repo_path(vcfg["cache_path"]), int(vcfg["cache_max_entries"]))
    drive = drive if drive is not None else GogDrive(dcfg, vcfg)
    out: dict = {"source": str(source), "drive_name": encrypted.name, "ok": False}

    def _finish(reason: str) -> dict:
        out["reason"] = reason
        out["alerts"] = raise_alerts(
            {CONDITION_UPLOAD: ("ok" if out["ok"] else reason, not out["ok"],
                                f"{encrypted.name}: {reason}")},
            notify=notify or default_notify, state_path=alert_state_path,
            realert_minutes=int(vcfg["alert_realert_minutes"]), receipt=str(_repo_path(vcfg["ledger_path"])))
        with contextlib.suppress(OSError):
            cache.save()
        return out

    if not encrypted.name.startswith(str(dcfg["prefix"]) + "_"):
        return _finish("drive_name_prefix_mismatch")
    try:
        st = os.lstat(source)
        enc_st = os.lstat(encrypted)
    except OSError:
        return _finish("local_file_missing")
    if not stat.S_ISREG(st.st_mode) or not stat.S_ISREG(enc_st.st_mode):
        return _finish("local_not_regular_file")
    src_md5 = file_md5(source, st, cache)
    if src_md5 is None or _md5_of(plaintext) != src_md5:
        return _finish("plaintext_copy_mismatch")
    enc_md5 = _md5_of(encrypted, _file_key(enc_st))
    if enc_md5 is None:
        return _finish("encrypted_unreadable")
    try:
        listing = drive.list(str(dcfg["prefix"]))
    except (DriveError, OSError) as exc:
        out["detail"] = str(exc)[:200]
        return _finish("drive_unreachable")
    matches = [f for f in listing["files"] if f["name"] == encrypted.name]
    if len(matches) != 1:
        return _finish("drive_object_missing" if not matches else "drive_object_ambiguous")
    obj = matches[0]
    if obj.get("size") != enc_st.st_size:
        out["drive_size"], out["local_size"] = obj.get("size"), enc_st.st_size
        return _finish("drive_size_mismatch")
    try:
        drive_md5 = drive_md5_cached(drive, obj, cache)
    except (DriveError, OSError) as exc:
        out["detail"] = str(exc)[:200]
        return _finish("drive_md5_unavailable")
    if drive_md5 != enc_md5:
        return _finish("drive_md5_mismatch")
    record = {
        "uploaded_at": _utc_iso(),
        "source": {"name": source.name, "path": str(source), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                   "ino": st.st_ino, "md5": src_md5},
        "drive": {"id": obj["id"], "name": obj["name"], "size": obj["size"], "md5": drive_md5,
                  "modifiedTime": obj.get("modifiedTime")},
    }
    ledger_path = _repo_path(vcfg["ledger_path"])
    with _lock(_repo_path(vcfg["lock_path"]), blocking=True):
        ledger = load_ledger(ledger_path)
        ledger["records"] = (ledger["records"] + [record])[-int(vcfg["ledger_max_records"]):]
        _write_json(ledger_path, ledger)
    out.update(ok=True, record=record)
    return _finish("verified")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--drive-db", action="store_true", help="Prune Drive even if drive_db.prune_enabled is false")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify-upload", action="store_true")
    ap.add_argument("--source")
    ap.add_argument("--plaintext")
    ap.add_argument("--encrypted")
    args = ap.parse_args(argv)
    pol = _load_policy()

    if args.status:
        out = {"local": status_local(pol.get("local_pg") or {})}
        print(json.dumps(out, indent=2))
        return 0 if out["local"].get("compliant") else 1

    if args.verify_upload:
        if not (args.source and args.plaintext and args.encrypted):
            ap.error("--verify-upload needs --source, --plaintext and --encrypted")
        try:
            res = verify_upload(pol, source=Path(args.source), plaintext=Path(args.plaintext),
                                encrypted=Path(args.encrypted))
        except PolicyError as exc:
            res = {"ok": False, "reason": f"policy_incomplete:{exc}"}
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("ok") else 1

    if args.dry_run:
        res = run(pol, dry_run=True, force_drive_prune=args.drive_db)
        print(json.dumps(res, indent=2, default=str))
        return 0 if not res.get("alertable") else 1

    try:
        _, _, vcfg = load_sections(pol)
        lock_path = _repo_path(vcfg["lock_path"])
    except PolicyError:
        res = run(pol, dry_run=False)
        print(json.dumps(res, indent=2, default=str))
        return 1
    with _lock(lock_path, blocking=False) as held:
        if not held:
            print(json.dumps({"skipped": "another backup_enforcer run holds the lock", "lock": str(lock_path)}))
            return 0
        res = run(pol, dry_run=False, force_drive_prune=args.drive_db)
    print(json.dumps(res, indent=2, default=str))
    return 0 if not res.get("alertable") else 1


if __name__ == "__main__":
    sys.exit(main())
