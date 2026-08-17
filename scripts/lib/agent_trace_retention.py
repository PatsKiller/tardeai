"""agent_trace_retention.py — bounded JSONL trace retention/rotation (AIF hardening).

READ_ONLY_ADVISORY. Deterministic, safe retention for the governed agent/tool
trace JSONL files. The original trace-storage minimum required bounded
retention; this module provides it.

Guarantees:
  * configured max age and/or max bytes/rows;
  * atomic rotation (write a temp file in the same directory, then os.replace);
  * newest VALID records preserved (invalid JSON lines are dropped, never
    silently corrupt the file);
  * never deletes outside the governed trace paths (fail-closed unless the
    caller explicitly opts in with ``allow_unlisted=True``);
  * dry-run option (default) — no write happens unless ``dry_run=False``.

This remediation session performs NO production purge: callers must opt in.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The only trace paths retention may touch, absent an explicit opt-in.
GOVERNED_TRACE_PATHS: frozenset[Path] = frozenset({
    PROJECT_ROOT / "data" / "cio" / "agent_run_traces.jsonl",
    PROJECT_ROOT / "data" / "cio" / "agent_tool_traces.jsonl",
})

# Timestamp fields used to order rows newest-first.
_TS_KEYS = ("ended_at", "started_at", "timestamp", "created_at", "at")


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_ts(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _row_ts(record: dict[str, Any]) -> float:
    for key in _TS_KEYS:
        ts = _parse_ts(record.get(key))
        if ts > 0.0:
            return ts
    return 0.0


def _read_rows(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return (raw_line, parsed_dict) pairs for every VALID JSON line, in file
    order. Invalid lines are dropped (never silently preserved as corrupt)."""
    out: list[tuple[str, dict[str, Any]]] = []
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append((line, rec))
    except OSError:
        return out
    return out


def _is_governed(path: Path) -> bool:
    return path in GOVERNED_TRACE_PATHS


def _write_atomic(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line.rstrip("\n") + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _select_newest(
    rows: list[tuple[str, dict[str, Any]]],
    *,
    max_age_days: Optional[float],
    max_bytes: Optional[int],
    max_rows: Optional[int],
) -> list[tuple[str, dict[str, Any]]]:
    """Select the newest VALID rows subject to age/byte/row budgets.

    Rows are ordered newest-first (by embedded timestamp when present, else by
    file order — later lines are treated as newer). Age is measured relative to
    the NEWEST row so a fully-stale corpus still retains its most recent rows.
    """
    # Newest-first: higher timestamp wins; ties keep later file position first.
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda e: (_row_ts(e[1][1]), e[0]), reverse=True)

    newest_ts = _row_ts(indexed[0][1][1]) if indexed else 0.0
    cutoff = 0.0
    if max_age_days is not None and max_age_days > 0 and newest_ts > 0.0:
        cutoff = newest_ts - (max_age_days * 86400.0)

    kept: list[tuple[str, dict[str, Any]]] = []
    used_bytes = 0
    for _, (raw, rec) in indexed:
        if max_age_days is not None and max_age_days > 0:
            ts = _row_ts(rec)
            if ts > 0.0 and ts < cutoff:
                continue
        if max_rows is not None and len(kept) >= max_rows:
            break
        line_bytes = len(raw.encode("utf-8")) + 1
        if max_bytes is not None and used_bytes + line_bytes > max_bytes:
            continue
        kept.append((raw, rec))
        used_bytes += line_bytes
    return kept


def enforce_trace_retention(
    path: Path | str,
    *,
    max_age_days: Optional[float] = None,
    max_bytes: Optional[int] = None,
    max_rows: Optional[int] = None,
    dry_run: bool = True,
    allow_unlisted: bool = False,
) -> dict[str, Any]:
    """Enforce bounded retention on one governed trace path.

    Returns a report. Defaults to dry-run (no write). Fails closed (``ok=False``)
    when the path is not a governed trace path and ``allow_unlisted`` is False,
    so this can never delete an arbitrary file. Invalid JSON lines are dropped;
    the newest valid rows are preserved.
    """
    p = Path(path)
    if not allow_unlisted and not _is_governed(p):
        return {
            "ok": False,
            "reason": "not a governed trace path",
            "path": str(p),
            "dry_run": dry_run,
            "removed": 0,
        }

    rows = _read_rows(p)
    if not rows:
        return {
            "ok": True,
            "path": str(p),
            "dry_run": dry_run,
            "removed": 0,
            "rotated": False,
            "kept": 0,
            "bytes_before": p.stat().st_size if p.exists() else 0,
            "bytes_after": p.stat().st_size if p.exists() else 0,
        }

    bytes_before = p.stat().st_size if p.exists() else 0
    kept = _select_newest(
        rows, max_age_days=max_age_days, max_bytes=max_bytes, max_rows=max_rows
    )
    removed = len(rows) - len(kept)
    rotated = False
    if removed > 0 and not dry_run:
        _write_atomic(p, [raw for raw, _ in kept])
        rotated = True

    return {
        "ok": True,
        "path": str(p),
        "dry_run": dry_run,
        "removed": removed,
        "rotated": rotated,
        "kept": len(kept),
        "bytes_before": bytes_before,
        "bytes_after": p.stat().st_size if p.exists() else 0,
    }
