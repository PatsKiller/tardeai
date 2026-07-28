"""Persistent shadow observation journal for the Active Trader motion snapshot.

This is an append-only, file-based JSONL journal. It owns NO database, network
transport, broker client, credential, or order action. Each line is one assembled
``active-trader-motion-snapshot-v1`` payload, written by the shadow producer.

The read endpoint (``motion_api.motion_snapshot``) only ever READS the latest line;
it never appends. Keeping the write on the producer side keeps the GET pure.

Design notes:
* One JSON object per line (JSONL) — corrupt/partial trailing lines are tolerated.
* ``append_snapshot`` is a pure append (never rewrites existing lines). It optionally
  prunes to a bounded tail *after* the append when ``max_lines`` is supplied, so the
  file stays rotation-friendly without the read path ever mutating it.
* No inf/nan is written — the shadow producer sanitizes before calling here.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Optional

# scripts/active_trader/motion_journal.py -> repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_JOURNAL = _REPO_ROOT / "data" / "active_trader" / "motion_journal.jsonl"

# Default bound the producer may apply so the file stays rotation-friendly.
DEFAULT_MAX_LINES = 5_000


def resolve_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the journal path. Explicit arg wins, then the env override, then the
    repo default under the (git-ignored) ``data/`` tree."""
    if path is not None:
        return Path(path).expanduser()
    env = os.environ.get("ACTIVE_TRADER_MOTION_JOURNAL", "").strip()
    if env:
        return Path(env).expanduser()
    return _DEFAULT_JOURNAL


def append_snapshot(
    snapshot: Mapping[str, Any],
    *,
    path: str | os.PathLike[str] | None = None,
    max_lines: Optional[int] = None,
) -> Path:
    """Append one snapshot as a single JSONL line (append-only).

    If ``max_lines`` is provided (> 0), the file is pruned to its last ``max_lines``
    lines AFTER the append — rotation without ever rewriting on the read path. When
    ``max_lines`` is None no pruning occurs (pure append).
    """
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(snapshot, separators=(",", ":"), allow_nan=False, sort_keys=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if max_lines is not None and max_lines > 0:
        _prune(target, max_lines)
    return target


def _prune(target: Path, max_lines: int) -> None:
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    if len(lines) <= max_lines:
        return
    tail = lines[-max_lines:]
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("\n".join(tail) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def prune_journal(
    max_lines: int = DEFAULT_MAX_LINES,
    *,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Explicit rotation helper: keep only the last ``max_lines`` lines."""
    _prune(resolve_path(path), max_lines)


def _last_json_line(target: Path) -> Optional[dict[str, Any]]:
    if not target.is_file():
        return None
    last: Optional[dict[str, Any]] = None
    try:
        with target.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except (ValueError, TypeError):
                    # tolerate a corrupt/partial line; keep the last good one
                    continue
                if isinstance(obj, dict):
                    last = obj
    except OSError:
        return None
    return last


def latest_snapshot(
    *,
    path: str | os.PathLike[str] | None = None,
) -> Optional[dict[str, Any]]:
    """Return the most recent well-formed snapshot object, or None if the journal is
    absent/empty/unreadable. Never raises."""
    return _last_json_line(resolve_path(path))


def snapshot_age_seconds(
    *,
    now: Optional[float] = None,
    path: str | os.PathLike[str] | None = None,
) -> Optional[float]:
    """Age (seconds) of the latest snapshot's ``generated_at`` vs ``now``. None when
    there is no usable snapshot or no finite ``generated_at``. Never negative."""
    latest = latest_snapshot(path=path)
    if not latest:
        return None
    gen = latest.get("generated_at")
    if not isinstance(gen, (int, float)) or isinstance(gen, bool):
        return None
    try:
        gen_f = float(gen)
    except (TypeError, ValueError):
        return None
    if gen_f != gen_f or gen_f in (float("inf"), float("-inf")):  # nan/inf guard
        return None
    current = time.time() if now is None else float(now)
    return max(0.0, current - gen_f)
