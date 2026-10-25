#!/usr/bin/env python3
"""jsonl_archive_rotate.py — move the closed history of an append-only JSONL store to a gzip archive.

Operator 2026-10-23 ~11:05 ET, "approved": rotate (archive, never delete) aif_memory_retrievals.jsonl (~574 MB),
research_call_accounting.jsonl (~1.7 GB) and cio_workflow_lineage.jsonl (~157 MB). Operator ~11:10 ET, verbatim:
"You have my authority to delete them. And the N8N agent needs to delete these on a regular. We cannot have this
junk piling up on the" — deletion of archive segments is rule J of scripts/disk_hygiene.py, not this script.

The stores and every threshold are in ``config/disk_hygiene_rules.json`` ``jsonl_retention.stores``. A store with
``rotate: false`` is never touched (cio_workflow_lineage: its writer dedups over, and merges envelopes from, the
whole history; see ``rotate_blocked_reason``).

WHAT MOVES. The hot tail starts at the first row whose timestamp (``ts_fields``) is at or after now − ``hot_days``;
everything after that row stays, in order, even an older-stamped row. At least ``min_tail_rows`` rows always stay.
Everything before the tail goes, byte for byte, to
``<state>/archive/file_prune/<id>/<id>.<UTC stamp>.jsonl.gz`` with a ``RetentionArchiveManifest@v1`` sidecar
(sha256 and line counts before and after; archived + kept == before) and one ``RetentionArchiveTripwire@v1`` line
in that directory's ``TRIPWIRE.jsonl`` (scripts/lib/retention_archive.write_manifest; the reader is
scripts/lib/retention_tripwire.py, nightly via report_db_hygiene.py → incident fan-in: any live reference to
``archive/file_prune`` is an ARCHIVE_TRIPWIRE P1).

WHY RENAME, NOT COPY-TRUNCATE. Every writer of these stores opens the file per write with O_APPEND and takes no
lock the rotation could share (agent_durable_memory._append_receipt, research_call_accounting.append_event,
cio_lineage.append, notification_broker._append_jsonl, autonomy_watchdog append_jsonl, the health-inspect
remediation runner). Copy-then-truncate without the writer's lock loses every row appended between the copy and the
truncate. So, per store:
  1. refuse if any process holds the live file open across two samples (a long-lived fd holder would keep writing
     into the renamed inode; that store then needs its writer's lock or a reopen signal instead);
  2. rename the live file aside (``.<name>.rotating-<stamp>``, same directory): writers that open after this
     create a fresh live file; a writer already inside its open→write→close finishes into the renamed inode;
  3. wait until no process has the renamed inode open (``/proc/*/fd``; bounded by ``quiesce_timeout_s``);
  4. stream it once: head → ``.gz.part`` (fsync), tail → ``.<name>.tail-<stamp>`` (fsync), one sha256 over all;
     re-read the archive (line count and sha256 of the decompressed bytes must match), then rename it into place;
  5. install the tail with ``renameat2(RENAME_NOREPLACE)``; if writers created a new live file meanwhile, the two
     are swapped with ``renameat2(RENAME_EXCHANGE)`` and the swapped-out rows (written since step 2) are appended
     to the live file once it is quiescent — a file is never overwritten, and one exchange always terminates (rows
     written in that sub-second window may land a few rows out of order; none is lost);
  6. after a short grace, any bytes that reached a renamed-aside inode late are appended to the live file
     (O_APPEND, exactly as a writer would);
  7. write the manifest + tripwire, then remove the two renamed-aside intermediates, whose every byte is now
     verified to be in the archive and the live file (archive-then-unlink, as scripts/lib/retention_archive.py).
A crash before step 5 leaves the rows in ``.<name>.rotating-<stamp>``; ``--recover`` merges any such file back in
front of the live rows. Nothing is ever lost and no row is deleted.

MODES
  python3 scripts/ops/jsonl_archive_rotate.py --dry-run          # the plan: sizes, lines, split; writes NOTHING
  python3 scripts/ops/jsonl_archive_rotate.py --plan             # the plan + plan report + LaneRunReceipt
  python3 scripts/ops/jsonl_archive_rotate.py --apply --confirm APPLY [--store ID ...]
  python3 scripts/ops/jsonl_archive_rotate.py --recover --confirm APPLY
--apply refuses Mon–Fri 04:00–16:15 America/New_York (``refuse_window_et``), and without ``--confirm APPLY``.

Exit: 0 ok; 1 a store failed or a refusal; 2 usage; 75 another rotation holds the lock.
MBI_BEHAVIOR = 0. No broker, no network, no send, no DB.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import gzip
import hashlib
import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_last_receipt as R  # noqa: E402
from scripts.lib import retention_archive as RA  # noqa: E402

LANE_ID = "jsonl-archive-rotate"
SCRIPT = "scripts/ops/jsonl_archive_rotate.py"
WRITER = "jsonl_archive_rotate"
RULES_PATH = ROOT / "config" / "disk_hygiene_rules.json"
PLAN_SCHEMA = "JsonlArchiveRotatePlan@v1"
REPORT_SCHEMA = "JsonlArchiveRotateReport@v1"
CONFIRM_WORD = "APPLY"
ET = ZoneInfo("America/New_York")
CHUNK = 1 << 20
EXIT_LOCKED = 75
RENAME_NOREPLACE = 1
RENAME_EXCHANGE = 2
AT_FDCWD = -100


class RotateError(RuntimeError):
    """A check failed; the live store is left as it was (or merged back), nothing is lost."""


# ── config ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    doc = json.loads(Path(path or RULES_PATH).read_text(encoding="utf-8"))
    cfg = doc.get("jsonl_retention")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("stores"), list):
        raise RotateError("rules_missing:jsonl_retention.stores")
    ids = [s.get("id") for s in cfg["stores"]]
    if len(ids) != len(set(ids)) or not all(ids):
        raise RotateError("rules_bad:jsonl_retention.stores ids")
    for s in cfg["stores"]:
        if s.get("rotate"):
            for k in ("path", "ts_fields", "hot_days", "min_tail_rows"):
                if k not in s:
                    raise RotateError(f"rules_missing:jsonl_retention.stores[{s['id']}].{k}")
    return cfg


def state_root(explicit: Optional[str] = None) -> Path:
    return Path(explicit) if explicit else RA.state_root()


def archive_dir(cfg: Mapping[str, Any], root: Path, store_id: str) -> Path:
    """<root>/archive/file_prune/<store id> — the same root as retention_archive.file_archive_root()."""
    return root / "archive" / "file_prune" / store_id


# ── time window ────────────────────────────────────────────────────────────────────────────────────────────────────

_DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def in_refuse_window(cfg: Mapping[str, Any], now: datetime) -> bool:
    w = cfg.get("refuse_window_et") or {}
    if not w:
        return False
    a, b = str(w.get("days") or "Mon-Fri").split("-")
    local = now.astimezone(ET)
    if not (_DAYS[a] <= local.weekday() <= _DAYS[b]):
        return False
    hm = local.strftime("%H:%M")
    return str(w["start"]) <= hm < str(w["end"])


# ── parsing ────────────────────────────────────────────────────────────────────────────────────────────────────────


def row_ts(raw: bytes, fields: Iterable[str]) -> Optional[datetime]:
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    for f in fields:
        v = obj.get(f)
        if isinstance(v, str) and v:
            try:
                ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def find_split(path: Path, *, fields: Iterable[str], cutoff: datetime, min_tail_rows: int,
               limit: Optional[int] = None) -> dict[str, Any]:
    """One streaming pass over the first ``limit`` bytes: the byte offset where the hot tail starts, line counts,
    the sha256 of the whole span and the first/last parseable timestamps. Reads only; holds at most
    ``min_tail_rows`` offsets."""
    fields = tuple(fields)
    split = split_line = None
    lines = 0
    offset = 0
    recent: deque[tuple[int, int]] = deque(maxlen=max(1, int(min_tail_rows)))
    h = hashlib.sha256()
    first_ts = last_ts = None
    unparsed = 0
    size = path.stat().st_size if limit is None else int(limit)
    with open(path, "rb") as fh:
        while offset < size:
            raw = fh.readline()
            if not raw:
                break
            if offset + len(raw) > size:
                raw = raw[: size - offset]
            h.update(raw)
            recent.append((offset, lines))
            ts = row_ts(raw, fields)
            if ts is None:
                unparsed += 1
            else:
                first_ts = first_ts or ts
                last_ts = ts
                if split is None and ts >= cutoff:
                    split, split_line = offset, lines
            offset += len(raw)
            lines += 1
    if split is None:
        split, split_line = offset, lines
    if lines <= int(min_tail_rows):
        split, split_line = 0, 0
    elif recent[0][0] < split:
        split, split_line = recent[0]
    return {"bytes": offset, "lines": lines, "sha256": h.hexdigest(), "split": split, "head_lines": split_line,
            "unparsed": unparsed, "first_ts": first_ts.isoformat() if first_ts else None,
            "last_ts": last_ts.isoformat() if last_ts else None}


def count_lines(path: Path, start: int = 0, end: Optional[int] = None) -> int:
    n = 0
    with open(path, "rb") as fh:
        fh.seek(start)
        left = (end - start) if end is not None else None
        while True:
            chunk = fh.read(CHUNK if left is None else min(CHUNK, left))
            if not chunk:
                break
            n += chunk.count(b"\n")
            if left is not None:
                left -= len(chunk)
                if left <= 0:
                    break
    return n


# ── host facts ─────────────────────────────────────────────────────────────────────────────────────────────────────


def fd_holders(path: Path, proc_root: Path = Path("/proc")) -> list[tuple[int, str]]:
    """(pid, fd) of every visible process with ``path``'s inode open. Unreadable entries are skipped."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (st.st_dev, st.st_ino)
    out = []
    try:
        pids = [e.name for e in os.scandir(proc_root) if e.name.isdigit()]
    except OSError:
        return []
    me = os.getpid()
    for pid in pids:
        if int(pid) == me:
            continue
        fd_dir = proc_root / pid / "fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                s = os.stat(fd_dir / fd)
            except OSError:
                continue
            if (s.st_dev, s.st_ino) == key:
                out.append((int(pid), fd))
    return out


def persistent_holders(path: Path, *, samples: int = 2, gap_s: float = 1.0, proc_root: Path = Path("/proc"),
                       sleep=time.sleep) -> list[tuple[int, str]]:
    seen = set(fd_holders(path, proc_root))
    for _ in range(max(0, samples - 1)):
        if not seen:
            return []
        sleep(gap_s)
        seen &= set(fd_holders(path, proc_root))
    return sorted(seen)


def quiesce(path: Path, *, timeout_s: float, proc_root: Path = Path("/proc"), sleep=time.sleep) -> bool:
    deadline = time.monotonic() + float(timeout_s)
    sleep(0.2)
    while fd_holders(path, proc_root):
        if time.monotonic() >= deadline:
            return False
        sleep(0.2)
    return True


_libc = None


def rename_noreplace(src: Path, dst: Path) -> None:
    """Atomic rename that fails with FileExistsError when ``dst`` exists (renameat2 RENAME_NOREPLACE)."""
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
    rc = _libc.renameat2(AT_FDCWD, os.fsencode(str(src)), AT_FDCWD, os.fsencode(str(dst)), RENAME_NOREPLACE)
    if rc != 0:
        e = ctypes.get_errno()
        if e == errno.EEXIST:
            raise FileExistsError(e, os.strerror(e), str(dst))
        raise OSError(e, os.strerror(e), str(src))


def rename_exchange(a: Path, b: Path) -> None:
    """Atomically swap two existing paths (renameat2 RENAME_EXCHANGE); FileNotFoundError if either is missing."""
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
    rc = _libc.renameat2(AT_FDCWD, os.fsencode(str(a)), AT_FDCWD, os.fsencode(str(b)), RENAME_EXCHANGE)
    if rc != 0:
        e = ctypes.get_errno()
        if e == errno.ENOENT:
            raise FileNotFoundError(e, os.strerror(e), str(b))
        raise OSError(e, os.strerror(e), str(a))


def _fsync_dir(d: Path) -> None:
    fd = os.open(str(d), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_range(src: Path, dst_fh, start: int, end: int, hashers=()) -> int:
    n = 0
    with open(src, "rb") as fh:
        fh.seek(start)
        left = end - start
        while left > 0:
            chunk = fh.read(min(CHUNK, left))
            if not chunk:
                break
            dst_fh.write(chunk)
            for h in hashers:
                h.update(chunk)
            n += len(chunk)
            left -= len(chunk)
    return n


def _sha_lines_range(path: Path, start: int, end: int) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        fh.seek(start)
        left = end - start
        while left > 0:
            chunk = fh.read(min(CHUNK, left))
            if not chunk:
                break
            h.update(chunk)
            n += chunk.count(b"\n")
            left -= len(chunk)
    return h.hexdigest(), n


def _gz_sha_lines(path: Path) -> tuple[str, int, int]:
    h = hashlib.sha256()
    n = b = 0
    with gzip.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
            n += chunk.count(b"\n")
            b += len(chunk)
    return h.hexdigest(), n, b


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ── plan ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def plan_store(store: Mapping[str, Any], cfg: Mapping[str, Any], root: Path, now: datetime) -> dict[str, Any]:
    sid = store["id"]
    out: dict[str, Any] = {"id": sid, "path": str(root / store.get("path", "")), "action": "skip"}
    if not store.get("rotate"):
        out["reason"] = "rotate_false"
        out["why"] = store.get("rotate_blocked_reason")
        return out
    live = root / store["path"]
    if not live.is_file() or live.is_symlink():
        out["reason"] = "missing_or_not_regular_file"
        return out
    size = live.stat().st_size
    out["bytes"] = size
    if size < int(cfg.get("min_rotate_bytes") or 0):
        out["reason"] = "below_min_rotate_bytes"
        return out
    cutoff = now - timedelta(days=float(store["hot_days"]))
    s = find_split(live, fields=store["ts_fields"], cutoff=cutoff, min_tail_rows=int(store["min_tail_rows"]),
                   limit=size)
    if s["first_ts"] is None:
        out.update({"reason": "no_parseable_timestamp", "lines": s["lines"], "ts_fields": list(store["ts_fields"])})
        return out
    head_lines = s["head_lines"]
    out.update({
        "action": "rotate" if s["split"] > 0 else "keep",
        "cutoff": cutoff.isoformat(),
        "hot_days": store["hot_days"],
        "lines": s["lines"],
        "first_ts": s["first_ts"],
        "last_ts": s["last_ts"],
        "unparsed_rows": s["unparsed"],
        "archive_bytes": s["split"],
        "archive_lines": head_lines,
        "keep_bytes": s["bytes"] - s["split"],
        "keep_lines": s["lines"] - head_lines,
        "sha256_before": s["sha256"],
        "archive_to": str(archive_dir(cfg, root, sid) / f"{sid}.{_stamp(now)}.jsonl.gz"),
        "fd_holders_now": len(fd_holders(live)),
    })
    if not s["split"]:
        out["reason"] = "nothing_older_than_hot_tail"
    return out


def build_plan(cfg: Mapping[str, Any], root: Path, now: datetime, only: Optional[set[str]] = None) -> dict[str, Any]:
    stores = [plan_store(s, cfg, root, now) for s in cfg["stores"] if not only or s["id"] in only]
    return {
        "schema": PLAN_SCHEMA,
        "generated_at": now.isoformat(),
        "state_root": str(root),
        "stores": stores,
        "totals": {
            "rotate": sum(1 for s in stores if s["action"] == "rotate"),
            "archive_bytes": sum(int(s.get("archive_bytes") or 0) for s in stores if s["action"] == "rotate"),
            "archive_lines": sum(int(s.get("archive_lines") or 0) for s in stores if s["action"] == "rotate"),
            "keep_bytes": sum(int(s.get("keep_bytes") or 0) for s in stores if s["action"] == "rotate"),
        },
    }


# ── retention preview (read-only) ──────────────────────────────────────────────────────────────────────────────────

_STAMP_RX = re.compile(r"(\d{8}T\d{6}Z)")


def _segment_time(p: Path) -> datetime:
    m = _STAMP_RX.search(p.name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)


def _segment_rows(p: Path, count: bool) -> Optional[int]:
    side = RA.manifest_path(p)
    if side.is_file():
        try:
            return int(json.loads(side.read_text(encoding="utf-8")).get("rows"))
        except (OSError, ValueError, TypeError):
            pass
    if not count:
        return None
    if p.name.endswith(".gz"):
        return _gz_sha_lines(p)[1]
    return count_lines(p)


def retention_preview(cfg: Mapping[str, Any], root: Path, now: datetime, *, retention_days: Optional[float] = None,
                      count_rows: bool = False) -> dict[str, Any]:
    """Which archive segments the retention rules WOULD select (age > retention_days, or beyond max_archive_bytes,
    oldest first). Reads only; selects, never removes. Removal is not implemented in this script: it is the
    operator's decision (AGENTS.md §17; §24.12 keeps stores and archives out of the automated-deletion scope)."""
    stores = []
    for st in cfg["stores"]:
        if "retention_days" not in st:
            continue
        days = float(st["retention_days"] if retention_days is None else retention_days)
        adir = archive_dir(cfg, root, st["id"])
        segs = sorted(p for p in adir.glob(f"{st['id']}.*.jsonl.gz") if p.is_file() and not p.is_symlink())
        for g in st.get("legacy_archive_globs") or []:
            segs += sorted(p for p in root.glob(g) if p.is_file() and not p.is_symlink())
        rows = []
        for p in segs:
            t = _segment_time(p)
            rows.append({"path": str(p), "bytes": p.stat().st_size, "archived_at": t.isoformat(),
                         "age_days": round((now - t).total_seconds() / 86400.0, 2),
                         "rows": _segment_rows(p, count_rows)})
        rows.sort(key=lambda r: r["archived_at"], reverse=True)
        total = 0
        cap = int(st.get("max_archive_bytes") or 0)
        for r in rows:
            total += r["bytes"]
            why = []
            if r["age_days"] > days:
                why.append(f"older_than_{days:g}d")
            if cap and total > cap:
                why.append("over_max_archive_bytes")
            r["would_select"] = bool(why)
            r["why"] = why
        stores.append({"id": st["id"], "retention_days": days, "max_archive_bytes": cap, "segments": rows,
                       "would_select_bytes": sum(r["bytes"] for r in rows if r["would_select"]),
                       "would_select_count": sum(1 for r in rows if r["would_select"])})
    return {"schema": "JsonlRetentionPreview@v1", "generated_at": now.isoformat(), "writes": "nothing",
            "removes": "nothing", "enabled": bool(cfg.get("enabled")), "stores": stores,
            "would_select_bytes": sum(s["would_select_bytes"] for s in stores)}


# ── apply ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _install(tail: Path, live: Path, *, stamp: str, cfg: Mapping[str, Any], proc_root: Path, sleep) -> list[dict]:
    """Install ``tail`` as ``live`` without ever replacing a live file. If writers created a new live file
    meanwhile, ``renameat2(RENAME_EXCHANGE)`` swaps the two atomically (the live name now holds the tail), and the
    swapped-out file — rows written since the rename aside — is quiesced and appended to the live file with
    O_APPEND, exactly as a writer appends. One exchange always terminates, however busy the writers are. Returns the
    fragments merged."""
    frags: list[dict] = []
    for attempt in range(int(cfg.get("max_install_attempts") or 20)):
        try:
            rename_noreplace(tail, live)
            _fsync_dir(live.parent)
            return frags
        except FileExistsError:
            pass
        try:
            rename_exchange(tail, live)
        except FileNotFoundError:
            continue  # the new live file vanished between the two calls: retry the plain install
        _fsync_dir(live.parent)
        frag = live.with_name(f".{live.name}.frag-{stamp}-{attempt}")
        os.rename(tail, frag)
        if not quiesce(frag, timeout_s=float(cfg.get("quiesce_timeout_s") or 30), proc_root=proc_root, sleep=sleep):
            raise RotateError(f"fragment_not_quiescent:{frag}")
        size = frag.stat().st_size
        _append_range(frag, live, 0, size)
        sha, lines = _sha_lines_range(frag, 0, size)
        frags.append({"path": str(frag), "bytes": size, "lines": lines, "sha256": sha})
        return frags
    raise RotateError("install_attempts_exhausted")


def _append_range(src: Path, live: Path, start: int, end: int) -> int:
    """Append src[start:end] to ``live`` with O_APPEND, whole lines per write() (the stores' writer pattern)."""
    fd = os.open(str(live), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    n = 0
    try:
        with open(src, "rb") as fh:
            fh.seek(start)
            left = end - start
            while left > 0:
                chunk = fh.read(min(CHUNK, left))
                if not chunk:
                    break
                if len(chunk) == CHUNK and left > len(chunk):
                    cut = chunk.rfind(b"\n") + 1
                    if cut > 0:
                        fh.seek(cut - len(chunk), os.SEEK_CUR)
                        chunk = chunk[:cut]
                os.write(fd, chunk)
                n += len(chunk)
                left -= len(chunk)
        os.fsync(fd)
    finally:
        os.close(fd)
    return n


def _late_sweep(items: list[dict], live: Path) -> list[dict]:
    """Append any bytes that reached a renamed-aside inode after it was consumed (O_APPEND, like a writer)."""
    late = []
    for it in items:
        p = Path(it["path"])
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > it["bytes"]:
            _sha, lines = _sha_lines_range(p, it["bytes"], size)
            n = _append_range(p, live, it["bytes"], size)
            late.append({"path": str(p), "bytes": n, "lines": lines})
            it["bytes"] = size
    return late


def rotate_store(store: Mapping[str, Any], cfg: Mapping[str, Any], root: Path, now: datetime, *,
                 proc_root: Path = Path("/proc"), sleep=time.sleep, grace_s: float = 1.0) -> dict[str, Any]:
    sid = store["id"]
    p = plan_store(store, cfg, root, now)
    if p["action"] != "rotate":
        return {**p, "ok": True}
    live = root / store["path"]
    holders = persistent_holders(live, proc_root=proc_root, sleep=sleep)
    if holders:
        return {**p, "ok": False, "action": "refused", "reason": "long_lived_fd_holder",
                "holders": [f"{a}/{b}" for a, b in holders]}
    stamp = _stamp(now)
    adir = archive_dir(cfg, root, sid)
    adir.mkdir(parents=True, exist_ok=True)
    gz_final = adir / f"{sid}.{stamp}.jsonl.gz"
    if gz_final.exists():
        return {**p, "ok": False, "action": "refused", "reason": f"archive_exists:{gz_final}"}
    src = live.with_name(f".{live.name}.rotating-{stamp}")
    tail = live.with_name(f".{live.name}.tail-{stamp}")
    os.rename(live, src)
    _fsync_dir(live.parent)
    try:
        if not quiesce(src, timeout_s=float(cfg.get("quiesce_timeout_s") or 30), proc_root=proc_root, sleep=sleep):
            raise RotateError("source_not_quiescent")
        size = src.stat().st_size
        cutoff = now - timedelta(days=float(store["hot_days"]))
        s = find_split(src, fields=store["ts_fields"], cutoff=cutoff, min_tail_rows=int(store["min_tail_rows"]),
                       limit=size)
        if s["first_ts"] is None:
            raise RotateError("no_parseable_timestamp")
        split = s["split"]
        # head → archive (.part), tail → temp file; one pass each, sha256 of each half and of the whole
        whole = hashlib.sha256()
        head_h = hashlib.sha256()
        part = gz_final.with_name(gz_final.name + ".part")
        with open(part, "wb") as raw_out:
            with gzip.GzipFile(fileobj=raw_out, mode="wb", compresslevel=RA.COMPRESSLEVEL, mtime=0) as gz:
                _copy_range(src, gz, 0, split, (whole, head_h))
            raw_out.flush()
            os.fsync(raw_out.fileno())
        tail_h = hashlib.sha256()
        with open(tail, "wb") as tout:
            _copy_range(src, tout, split, size, (whole, tail_h))
            tout.flush()
            os.fsync(tout.fileno())
        if whole.hexdigest() != s["sha256"]:
            raise RotateError("source_changed_during_rotation")
        head_lines = s["head_lines"]
        tail_lines = s["lines"] - head_lines
        gsha, glines, gbytes = _gz_sha_lines(part)
        if (gsha, glines, gbytes) != (head_h.hexdigest(), head_lines, split):
            raise RotateError("archive_verify_failed")
        tsha, tlines = _sha_lines_range(tail, 0, size - split)
        if (tsha, tlines) != (tail_h.hexdigest(), tail_lines):
            raise RotateError("tail_verify_failed")
        os.rename(part, gz_final)
        _fsync_dir(adir)
    except BaseException:
        # merge the renamed-aside source back in front of any rows written meanwhile; never lose a row. A partial
        # archive (.part) and the temp tail are left in place for inspection (their bytes are all in the source).
        recover_one(live, src, cfg=cfg, proc_root=proc_root, sleep=sleep, stamp=stamp)
        raise
    frags = _install(tail, live, stamp=stamp, cfg=cfg, proc_root=proc_root, sleep=sleep)
    sleep(grace_s)
    consumed = [{"path": str(src), "bytes": size}] + [{"path": f["path"], "bytes": f["bytes"]} for f in frags]
    late = _late_sweep(consumed, live)
    frag_lines = sum(f["lines"] for f in frags) + sum(x["lines"] for x in late)
    after_live = live.stat().st_size if live.exists() else 0
    before = {"path": str(live), "bytes": size, "lines": s["lines"], "sha256": s["sha256"],
              "first_ts": s["first_ts"], "last_ts": s["last_ts"]}
    after = {"archive": {"path": str(gz_final), "bytes_uncompressed": split, "bytes_gz": gz_final.stat().st_size,
                         "lines": head_lines, "sha256_uncompressed": head_h.hexdigest()},
             "live_tail": {"bytes": size - split, "lines": tail_lines, "sha256": tail_h.hexdigest()},
             "merged_fragments": frags, "late_bytes": late, "live_bytes_after": after_live}
    if head_lines + tail_lines != s["lines"]:
        raise RotateError("line_accounting_mismatch")
    RA.write_manifest(gz_final, writer=WRITER, label=sid, kind="jsonl_head", table=None, rows=head_lines,
                      sha256=RA._sha256_file(gz_final), sha256_uncompressed=head_h.hexdigest(),
                      store=store["path"], hot_days=store["hot_days"], cutoff=cutoff.isoformat(),
                      before=before, after=after,
                      line_accounting={"before": s["lines"], "archived": head_lines, "kept": tail_lines,
                                       "equal": head_lines + tail_lines == s["lines"],
                                       "rows_appended_during_rotation": frag_lines},
                      approval=store.get("approval"))
    # archive-then-unlink: every byte of these intermediates is verified in the archive or the live file
    removed = []
    for it in consumed:
        ip = Path(it["path"])
        if ip.exists():
            ip.unlink()
            removed.append(str(ip))
    _fsync_dir(live.parent)
    return {**p, "ok": True, "action": "rotated", "archive": str(gz_final), "archive_lines": head_lines,
            "keep_lines": tail_lines, "before": before, "after": after, "intermediates_removed": removed}


def recover_one(live: Path, src: Path, *, cfg: Mapping[str, Any], proc_root: Path, sleep, stamp: str) -> dict:
    """Put ``src`` (the renamed-aside store) back as the live file, with any rows written meanwhile after it."""
    frags = _install(src, live, stamp=stamp + "-recover", cfg=cfg, proc_root=proc_root, sleep=sleep)
    removed = []
    for f in frags:
        fp = Path(f["path"])
        if fp.exists() and fp.stat().st_size == f["bytes"]:
            fp.unlink()
            removed.append(str(fp))
    return {"recovered": str(src), "merged_fragments": frags, "fragments_removed": removed}


def recover(cfg: Mapping[str, Any], root: Path, now: datetime, *, proc_root: Path = Path("/proc"),
            sleep=time.sleep) -> list[dict]:
    out = []
    for store in cfg["stores"]:
        if not store.get("path"):
            continue
        live = root / store["path"]
        for src in sorted(live.parent.glob(f".{live.name}.rotating-*")):
            if not quiesce(src, timeout_s=float(cfg.get("quiesce_timeout_s") or 30), proc_root=proc_root,
                           sleep=sleep):
                out.append({"id": store["id"], "src": str(src), "ok": False, "reason": "not_quiescent"})
                continue
            out.append({"id": store["id"], "ok": True,
                        **recover_one(live, src, cfg=cfg, proc_root=proc_root, sleep=sleep, stamp=_stamp(now))})
        for t in sorted(live.parent.glob(f".{live.name}.tail-*")):
            out.append({"id": store["id"], "orphan_tail": str(t), "note": "kept; its rows are also in the source"})
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="print the plan; writes nothing at all")
    g.add_argument("--plan", action="store_true", help="the plan + plan report + LaneRunReceipt; moves nothing")
    g.add_argument("--apply", action="store_true", help="rotate (needs --confirm APPLY; refused in the ET window)")
    g.add_argument("--recover", action="store_true", help="merge a crashed rotation's source back (--confirm APPLY)")
    g.add_argument("--retention-preview", action="store_true",
                   help="list the archive segments the retention rules WOULD select; reads only, removes nothing")
    ap.add_argument("--retention-days", type=float, default=None, help="--retention-preview: override every store")
    ap.add_argument("--count-rows", action="store_true", help="--retention-preview: count rows of unmanifested files")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--store", action="append", default=[], help="limit to these store ids")
    ap.add_argument("--rules", help=argparse.SUPPRESS)
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / ~/trade-ai-releases/...)")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    now = _parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    wall = datetime.now(timezone.utc)
    root = state_root(a.state_root)
    try:
        cfg = load_config(Path(a.rules) if a.rules else None)
    except (OSError, ValueError, RotateError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    only = set(a.store) or None
    if a.retention_preview:
        print(json.dumps(retention_preview(cfg, root, now, retention_days=a.retention_days, count_rows=a.count_rows),
                         indent=1, default=str))
        return 0
    if a.dry_run:
        m = build_plan(cfg, root, now, only)
        print(json.dumps({"dry_run": True, "writes": "nothing", **m}, indent=1, default=str))
        return 0
    rdir = R.runtime_dir(root) / "jsonl_archive_rotate"
    if a.plan:
        m = build_plan(cfg, root, now, only)
        from scripts.lib.atomic_json_store import atomic_write_json

        rdir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(rdir / "plan_latest.json", m, indent=1)
        n = int(m["totals"]["rotate"])
        R.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=wall, script=SCRIPT,
                             summary={"mode": "plan", **m["totals"]}, path=R.receipt_path(LANE_ID, root),
                             produced_count=n, attempted_count=len(m["stores"]),
                             empty_reason=None if n else "nothing_due")
        print(json.dumps({"mode": "plan", **m["totals"]}))
        return 0
    if a.confirm != CONFIRM_WORD:
        print(json.dumps({"ok": False, "refused": f"needs --confirm {CONFIRM_WORD}"}))
        return 1
    if in_refuse_window(cfg, now):
        print(json.dumps({"ok": False, "refused": "market_hours_window", "window": cfg.get("refuse_window_et"),
                          "now_et": now.astimezone(ET).isoformat()}))
        return 1
    lock_dir = R.runtime_dir(root)
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / "jsonl_archive_rotate.lock", "a+") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"ok": False, "refused": "locked"}))
            return EXIT_LOCKED
        if a.recover:
            res = recover(cfg, root, now)
            print(json.dumps({"mode": "recover", "results": res}, indent=1, default=str))
            return 0 if all(r.get("ok", True) for r in res) else 1
        results = []
        for store in cfg["stores"]:
            if only and store["id"] not in only:
                continue
            try:
                results.append(rotate_store(store, cfg, root, now))
            except (OSError, RotateError) as exc:
                results.append({"id": store["id"], "ok": False, "action": "failed", "error": str(exc)})
        rep = {"schema": REPORT_SCHEMA, "generated_at": now.isoformat(), "state_root": str(root), "results": results}
        from scripts.lib.atomic_json_store import atomic_write_json

        rdir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(rdir / f"rotate_{_stamp(now)}.json", rep, indent=1)
        ok = all(r.get("ok") for r in results)
        n = sum(r.get("action") == "rotated" for r in results)
        R.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=wall, script=SCRIPT,
                             summary={"mode": "apply", "rotated": n, "failed": sum(not r.get("ok") for r in results)},
                             path=R.receipt_path(LANE_ID, root), produced_count=n, attempted_count=len(results),
                             empty_reason=None if n else "nothing_due")
        print(json.dumps(rep, indent=1, default=str))
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
