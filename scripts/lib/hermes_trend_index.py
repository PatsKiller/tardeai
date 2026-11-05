"""Compact, incrementally built daily trend index for the Hermes snapshot stores.

The outcome-bus and governed-universe trends used to parse every snapshot file on every request: 134 outcome files of
up to 22 MB (1.7 GB total) and 1,100 universe files (967 MB), so ``GET /api/v2/hermes/outcome-bus/history`` took
75-95 s and the client timed out (route sweep, 2026-11-01). A trend needs one point per UTC day, taken from the newest
snapshot of that day, so this module parses each file at most once and keeps only that point in a small JSON index.

Selection is by the snapshot's own UTC day (the point's ``day``), with the filename's ``_YYYY-MM-DDTHHMM_`` timestamp
used only to pick which files are worth parsing: the newest file per filename-day inside the window, plus the current
snapshot. A file is re-parsed only when its size or mtime changes; the index is refreshed atomically under a lock.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

SCHEMA = "HermesTrendIndex@v1"
_NAME_TS = re.compile(r"_(?P<day>\d{4}-\d{2}-\d{2})T(?P<hhmm>\d{4})")
_LOCK = threading.Lock()


def day_from_name(name: str) -> Optional[str]:
    """``outcome_bus_2026-09-26T1525_ofb_ab12.json`` → ``2026-09-26``."""
    m = _NAME_TS.search(name)
    return m.group("day") if m else None


def load_index(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "files": {}}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("files"), dict):
        return {"schema": SCHEMA, "files": {}}
    return doc


def _save_index(path: Path, files: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, "files": files}, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _parse(path: Path) -> dict[str, Any]:
    """The one parse seam (tests count calls through it)."""
    return json.loads(path.read_text(encoding="utf-8"))


def _record(key: str, path: Path, point: Callable[[dict[str, Any], datetime], dict[str, Any]],
            index: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        st = path.stat()
    except OSError:
        return None
    rec = index.get(key)
    stamp = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    if isinstance(rec, dict) and rec.get("size") == stamp["size"] and rec.get("mtime_ns") == stamp["mtime_ns"]:
        return rec.get("point")
    try:
        snap = _parse(path)
        ts = _generated_at(snap)
        if ts is None:
            return None
        point = point(snap, ts)
    except (OSError, ValueError, TypeError, KeyError):
        return None
    index[key] = {**stamp, "point": point}
    return point


def _generated_at(snap: dict[str, Any]) -> Optional[datetime]:
    raw = snap.get("generated_at") or snap.get("at")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def daily_points(
    *,
    history_dir: Path,
    prefix: str,
    days: int,
    point: Callable[[dict[str, Any], datetime], dict[str, Any]],
    index_path: Path,
    current: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """One trend point per UTC day, newest snapshot of that day, over ``days`` days.

    Files more than one day outside the window by filename are never opened (the one-day slack covers a snapshot
    written just after midnight). The result is byte-for-byte what the old full scan produced, because the grouping
    and the newest-per-day pick still use the snapshot's own ``generated_at``.
    """
    days = max(1, min(int(days), 90))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    floor_day = (cutoff - timedelta(days=1)).date().isoformat()

    # The newest file per filename-day inside the window: filenames sort by their UTC timestamp. A file whose name
    # carries no timestamp cannot be windowed cheaply; it is still considered (parsed once, then cached), so a writer
    # that ever names a snapshot differently is not silently dropped.
    newest: dict[str, Path] = {}
    undated: list[Path] = []
    try:
        for path in history_dir.glob(prefix + "*.json"):
            day = day_from_name(path.name)
            if day is None:
                undated.append(path)
                continue
            if day < floor_day:
                continue
            cur = newest.get(day)
            if cur is None or path.name > cur.name:
                newest[day] = path
    except OSError:
        newest, undated = {}, []

    with _LOCK:
        index = load_index(index_path)
        files = index["files"]
        candidates: list[tuple[str, Path]] = sorted((p.name, p) for p in [*newest.values(), *undated])
        if current is not None and current.exists():
            candidates.append(("__current__", current))
        points: list[dict[str, Any]] = []
        changed = False
        for key, path in candidates:
            before = files.get(key)
            pt = _record(key, path, point, files)
            if files.get(key) is not before:
                changed = True
            if pt is not None:
                points.append(pt)
        by_day: dict[str, dict[str, Any]] = {}
        for pt in points:
            day = str(pt.get("day") or "")
            if not day or day < cutoff.date().isoformat():
                continue
            prev = by_day.get(day)
            if prev is None or str(pt.get("at") or "") > str(prev.get("at") or ""):
                by_day[day] = pt
        keep = {key for key, _ in candidates}
        pruned = {k: v for k, v in files.items() if k in keep}
        if changed or pruned != files:
            _save_index(index_path, pruned)
        return [by_day[day] for day in sorted(by_day)]
