"""Archive rotation for data/runtime/advisory_kb_lessons.jsonl (never deletes).

The lesson log is an append-only event log of full lesson snapshots; every
reader (kb_lessons.list_lessons, maturity_control.lessons, cio_belief_writer,
lesson_promotion) wants the latest row per lesson id. Rotation therefore:

  * keeps every row newer than ``retain_days`` live;
  * keeps the newest row per lesson id live regardless of age
    (``keep_latest_per_id``), so latest-by-id answers never change;
  * keeps rows whose JSON or timestamp cannot be parsed live;
  * moves the remaining (superseded, old) rows into monthly gzip archives
    ``<state_root>/<archive_subdir>/YYYY-MM.jsonl.gz`` (month of the row's
    timestamp). An existing month archive gets a new gzip member appended;
    rows already present (by sha256 of the line) are skipped so a re-run after
    a crash does not duplicate them.

Order in ``apply``: take the writer lock (sidecar ``<live><lock_suffix>``,
the same lock ``kb_lessons._append_jsonl`` takes), write and fsync every
archive, re-read each archive and confirm every archived line is present,
rewrite ``SHA256SUMS``, then write the kept rows to a temp file, fsync, and
``os.replace`` it over the live file. Any verify failure leaves the live file
untouched. ``plan`` is read-only (no lock file, no writes).

Settings come from config/advisory_kb_lessons_retention.json; when it is
missing the defaults below are used and a warning is logged.
"""
from __future__ import annotations

import contextlib
import fcntl
import gzip
import hashlib
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

LOG = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "advisory_kb_lessons_retention.json"

# Fallbacks used only when the config file is missing or unreadable.
_DEFAULTS: dict[str, Any] = {
    "live_rel": "data/runtime/advisory_kb_lessons.jsonl",
    "archive_subdir": "archive/advisory_kb_lessons",
    "retain_days": 90,
    "keep_latest_per_id": True,
    "id_fields": ["id", "lesson_id"],
    "ts_fields": ["ts", "ratified_at", "retired_at"],
    "lock_suffix": ".lock",
    "manifest_name": "SHA256SUMS",
    "gzip_compresslevel": 6,
    "state_root_env": "TRADEAI_STATE_ROOT",
    "default_state_root": "~/trade-ai-releases/persistent-state",
}

_CONFIG_CACHE: dict[str, Any] = {}


class RotationVerifyError(RuntimeError):
    """An archive re-read did not contain every row moved into it; live file untouched."""

    code = "KB_LESSONS_ARCHIVE_VERIFY_FAILED"


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    key = str(p)
    if key in _CONFIG_CACHE:
        return dict(_CONFIG_CACHE[key])
    cfg = dict(_DEFAULTS)
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            cfg.update({k: v for k, v in loaded.items() if k in _DEFAULTS})
    except Exception as exc:  # missing/corrupt config -> defaults, loudly
        LOG.warning("advisory_kb_lessons_retention config unreadable (%s): %s; using defaults", p, exc)
    _CONFIG_CACHE[key] = cfg
    return dict(cfg)


def state_root(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    env = os.environ.get(str(cfg["state_root_env"]))
    return Path(env) if env else Path(os.path.expanduser(str(cfg["default_state_root"])))


def default_live_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return state_root(cfg) / str(cfg["live_rel"])


def default_archive_dir(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return state_root(cfg) / str(cfg["archive_subdir"])


def lock_path_for(live: Path, cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(str(live) + str(cfg["lock_suffix"]))


@contextlib.contextmanager
def writer_lock(live: Path, cfg: dict[str, Any] | None = None) -> Iterator[None]:
    """Exclusive lock shared by the lesson writer and the rotator.

    A sidecar file is locked (not the live file) because rotation replaces the
    live inode; a writer that locked the old inode could append to a file that
    is no longer the live one.
    """
    lp = lock_path_for(live, cfg)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ── parsing ──────────────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _classify_line(raw: bytes, cfg: dict[str, Any]) -> tuple[str | None, datetime | None]:
    """(lesson id, row timestamp) for one line; (None, None) when unparseable."""
    try:
        obj = json.loads(raw)
    except Exception:
        return None, None
    if not isinstance(obj, dict):
        return None, None
    lid = None
    for f in cfg["id_fields"]:
        if obj.get(f):
            lid = str(obj[f])
            break
    ts = None
    for f in cfg["ts_fields"]:
        ts = _parse_ts(obj.get(f))
        if ts is not None:
            break
    return lid, ts


def _norm(raw: bytes) -> bytes:
    return raw if raw.endswith(b"\n") else raw + b"\n"


def _line_hash(raw: bytes) -> str:
    return hashlib.sha256(_norm(raw)).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# ── plan (read-only) ─────────────────────────────────────────────────────────

def _scan(live: Path, cfg: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Stream the live file once; decide keep/archive per line index."""
    cutoff = now - timedelta(days=int(cfg["retain_days"]))
    meta: list[tuple[str | None, datetime | None]] = []
    last_idx: dict[str, int] = {}
    sizes: list[int] = []
    blank = 0
    with open(live, "rb") as fh:
        for raw in fh:
            if not raw.strip():
                meta.append((None, None))
                sizes.append(-len(raw))  # negative marks a blank line
                blank += 1
                continue
            lid, ts = _classify_line(raw, cfg)
            if lid:
                last_idx[lid] = len(meta)
            meta.append((lid, ts))
            sizes.append(len(_norm(raw)))
    decisions: list[str | None] = []  # None = keep, "YYYY-MM" = archive month, "" = blank
    for i, (lid, ts) in enumerate(meta):
        if sizes[i] < 0:
            decisions.append("")
            continue
        if ts is None or ts >= cutoff:
            decisions.append(None)
            continue
        if cfg["keep_latest_per_id"] and lid and last_idx.get(lid) == i:
            decisions.append(None)
            continue
        decisions.append(ts.strftime("%Y-%m"))
    return {"cutoff": cutoff, "meta": meta, "sizes": sizes, "decisions": decisions,
            "last_idx": last_idx, "blank": blank}


def plan(live: Path | None = None, *, cfg: dict[str, Any] | None = None,
         now: datetime | None = None, retain_days: int | None = None) -> dict[str, Any]:
    """Read-only report of what ``apply`` would move. Takes no lock, writes nothing."""
    cfg = dict(cfg or load_config())
    if retain_days is not None:
        cfg["retain_days"] = int(retain_days)
    live = Path(live) if live else default_live_path(cfg)
    now = now or datetime.now(timezone.utc)
    if not live.is_file():
        return {"ok": False, "reason": "live file missing", "live": str(live)}
    s = _scan(live, cfg, now)
    meta, sizes, decisions = s["meta"], s["sizes"], s["decisions"]
    by_month_rows: Counter[str] = Counter()
    by_month_bytes: Counter[str] = Counter()
    keep_rows = keep_bytes = 0
    unparseable = 0
    old_kept_latest = 0
    newest: datetime | None = None
    oldest: datetime | None = None
    for i, d in enumerate(decisions):
        if d == "":
            continue
        lid, ts = meta[i]
        if ts is None:
            unparseable += 1
        else:
            newest = ts if newest is None or ts > newest else newest
            oldest = ts if oldest is None or ts < oldest else oldest
        if d is None:
            keep_rows += 1
            keep_bytes += sizes[i]
            if ts is not None and ts < s["cutoff"]:
                old_kept_latest += 1
        else:
            by_month_rows[d] += 1
            by_month_bytes[d] += sizes[i]
    return {
        "ok": True,
        "mode": "plan",
        "live": str(live),
        "archive_dir": str(default_archive_dir(cfg)),
        "now": now.isoformat(),
        "retain_days": int(cfg["retain_days"]),
        "cutoff": s["cutoff"].isoformat(),
        "live_bytes": live.stat().st_size,
        "rows": sum(1 for d in decisions if d != ""),
        "blank_lines": s["blank"],
        "distinct_ids": len(s["last_idx"]),
        "unparseable_ts_rows_kept": unparseable,
        "oldest_ts": oldest.isoformat() if oldest else None,
        "newest_ts": newest.isoformat() if newest else None,
        "keep_rows": keep_rows,
        "keep_bytes": keep_bytes,
        "old_rows_kept_as_latest_per_id": old_kept_latest,
        "archive_rows": sum(by_month_rows.values()),
        "archive_bytes_uncompressed": sum(by_month_bytes.values()),
        "archive_by_month": {m: {"rows": by_month_rows[m], "bytes": by_month_bytes[m]}
                             for m in sorted(by_month_rows)},
    }


# ── archives ─────────────────────────────────────────────────────────────────

def archive_path(archive_dir: Path, month: str) -> Path:
    return archive_dir / f"{month}.jsonl.gz"


def _archive_line_hashes(path: Path) -> Counter[str]:
    out: Counter[str] = Counter()
    if not path.is_file():
        return out
    with gzip.open(path, "rb") as gz:
        for raw in gz:
            if raw.strip():
                out[_line_hash(raw)] += 1
    return out


def _append_member(path: Path, lines: list[bytes], level: int) -> None:
    """Existing bytes + one new gzip member -> temp -> fsync -> replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as out:
        if path.is_file():
            with open(path, "rb") as src:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    out.write(chunk)
        with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=level) as gz:
            for raw in lines:
                gz.write(_norm(raw))
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def write_manifest(archive_dir: Path, cfg: dict[str, Any]) -> Path:
    mp = archive_dir / str(cfg["manifest_name"])
    rows = [f"{_sha256_file(p)}  {p.name}\n" for p in sorted(archive_dir.glob("*.jsonl.gz"))]
    tmp = mp.with_name(mp.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(rows)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, mp)
    _fsync_dir(archive_dir)
    return mp


def verify_manifest(archive_dir: Path, cfg: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    cfg = cfg or load_config()
    mp = archive_dir / str(cfg["manifest_name"])
    if not mp.is_file():
        return False, ["manifest missing"]
    bad = []
    for line in mp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        p = archive_dir / name
        if not p.is_file() or _sha256_file(p) != digest:
            bad.append(name)
    return not bad, bad


def iter_archived_rows(archive_dir: Path | None = None) -> Iterator[dict[str, Any]]:
    """Every archived row, oldest month first (for any reader that needs history)."""
    d = Path(archive_dir) if archive_dir else default_archive_dir()
    for p in sorted(d.glob("*.jsonl.gz")):
        with gzip.open(p, "rb") as gz:
            for raw in gz:
                if not raw.strip():
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    yield obj


# ── apply ────────────────────────────────────────────────────────────────────

def apply(live: Path | None = None, *, archive_dir: Path | None = None,
          cfg: dict[str, Any] | None = None, now: datetime | None = None,
          retain_days: int | None = None) -> dict[str, Any]:
    cfg = dict(cfg or load_config())
    if retain_days is not None:
        cfg["retain_days"] = int(retain_days)
    live = Path(live) if live else default_live_path(cfg)
    archive_dir = Path(archive_dir) if archive_dir else default_archive_dir(cfg)
    now = now or datetime.now(timezone.utc)
    if not live.is_file():
        return {"ok": False, "reason": "live file missing", "live": str(live)}
    level = int(cfg["gzip_compresslevel"])
    with writer_lock(live, cfg):
        s = _scan(live, cfg, now)
        decisions = s["decisions"]
        if not any(d for d in decisions):
            return {"ok": True, "mode": "apply", "action": "noop", "live": str(live),
                    "rows": sum(1 for d in decisions if d != ""), "archive_rows": 0}
        groups: dict[str, list[bytes]] = defaultdict(list)
        kept_hashes: list[str] = []
        tmp_live = live.with_name(live.name + ".rotate.tmp")
        total = 0
        n_read = 0
        with open(live, "rb") as src, open(tmp_live, "wb") as out:
            for raw in src:
                n_read += 1
                if n_read > len(decisions):
                    break
                d = decisions[n_read - 1]
                if d == "":
                    continue
                total += 1
                if d is None:
                    out.write(_norm(raw))
                    kept_hashes.append(_line_hash(raw))
                else:
                    groups[d].append(raw)
            out.flush()
            os.fsync(out.fileno())
        if n_read != len(decisions):  # file changed under the lock: refuse
            tmp_live.unlink(missing_ok=True)
            raise RotationVerifyError(f"line count changed during rotation ({n_read} != {len(decisions)})")
        archived = 0
        skipped_dupes = 0
        months: dict[str, dict[str, int]] = {}
        try:
            for month in sorted(groups):
                path = archive_path(archive_dir, month)
                existing = _archive_line_hashes(path)
                pending = Counter(_line_hash(r) for r in groups[month])
                new_lines: list[bytes] = []
                seen: Counter[str] = Counter()
                for raw in groups[month]:
                    h = _line_hash(raw)
                    seen[h] += 1
                    if seen[h] <= existing.get(h, 0):
                        skipped_dupes += 1
                        continue
                    new_lines.append(raw)
                if new_lines:
                    _append_member(path, new_lines, level)
                after = _archive_line_hashes(path)
                missing = [h for h, n in pending.items() if after.get(h, 0) < n]
                if missing or sum(after.values()) != sum(existing.values()) + len(new_lines):
                    raise RotationVerifyError(f"{path.name}: {len(missing)} archived rows not found on re-read")
                archived += len(groups[month])
                months[month] = {"rows": len(groups[month]), "appended": len(new_lines)}
            manifest = write_manifest(archive_dir, cfg)
            ok, bad = verify_manifest(archive_dir, cfg)
            if not ok:
                raise RotationVerifyError(f"manifest mismatch: {bad}")
            if archived + len(kept_hashes) != total:
                raise RotationVerifyError("archived + kept != total rows")
        except Exception:
            tmp_live.unlink(missing_ok=True)
            raise
        mode = live.stat().st_mode & 0o7777
        os.chmod(tmp_live, mode)
        before_bytes = live.stat().st_size
        os.replace(tmp_live, live)
        _fsync_dir(live.parent)
    return {
        "ok": True, "mode": "apply", "action": "rotated", "live": str(live),
        "archive_dir": str(archive_dir), "manifest": str(manifest),
        "cutoff": s["cutoff"].isoformat(), "rows": total, "archive_rows": archived,
        "keep_rows": len(kept_hashes), "skipped_already_archived": skipped_dupes,
        "live_bytes_before": before_bytes, "live_bytes_after": live.stat().st_size,
        "months": months,
    }
