"""Features switched off on purpose carry a due date, and the due date is checked.

Operator 2026-10-31, verbatim: "Okay, you switched the LLM off, but there needs to be a reminder to switch it back on.
We just don't want to leave it off; we got to get it working correctly."

Any config file under ``config/`` (``*.yaml``, ``*.yml``, ``*.json``) may carry a top-level ``disabled_until`` block:

    disabled_until:
      reason: why it is off
      disabled_at: 2026-10-31
      review_by: 2026-11-07
      owner: coordinator
      reenable_plan: what has to be true to switch it back on

``scan()`` lists every such block; an entry whose ``review_by`` is in the past is ``overdue``. The block is removed
(or its dates moved, with a reason) by the PR that re-enables the feature. Read-only: nothing here writes or sends.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
REQUIRED = ("reason", "disabled_at", "review_by", "owner", "reenable_plan")


def _as_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except (TypeError, ValueError):
        return None


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _error(name: str, file: str, error: str, review: Optional[date] = None) -> dict[str, Any]:
    """An error entry carries only the name, the file and the due date: never the block's other text (review #2399
    F13 — a malformed block may hold anything)."""
    return {
        "name": name,
        "file": file,
        "review_by": review.isoformat() if review else None,
        "error": error,
        "overdue": True,
    }


def entry_for(path: Path | str, *, today: Optional[date] = None, data: Any = None) -> Optional[dict[str, Any]]:
    """The ``disabled_until`` entry of one config file, or None. A malformed block is reported, never skipped, and no
    exception from one file ever escapes (review #2399 F12: binary, deep nesting, tags, directories, broken links)."""
    p = Path(path)
    today = today or date.today()
    try:
        if data is None:
            if not p.is_file():
                return None
            data = _load(p)
        if not isinstance(data, dict) or "disabled_until" not in data:
            return None
        blk = data.get("disabled_until")
        raw_name = blk.get("name") if isinstance(blk, dict) else None
        name = raw_name if isinstance(raw_name, str) and raw_name.strip() else p.stem
        if not isinstance(blk, dict):
            return _error(name, p.name, "disabled_until is not a mapping")
        review = _as_date(blk.get("review_by"))
        missing = [k for k in REQUIRED if not blk.get(k)]
        if missing or review is None:
            return _error(name, p.name, "missing or invalid " + ", ".join(missing or ["review_by"]), review)
        return {
            "name": name,
            "file": p.name,
            "reason": str(blk.get("reason")),
            "disabled_at": str(blk.get("disabled_at") or ""),
            "review_by": review.isoformat(),
            "owner": str(blk.get("owner")),
            "reenable_plan": str(blk.get("reenable_plan")),
            "days_left": (review - today).days,
            "overdue": review < today,
        }
    except Exception as exc:  # noqa: BLE001 — one bad file must never stop the scan (F12)
        return _error(p.stem, p.name, f"unreadable: {type(exc).__name__}")


def scan(config_dir: Path | str = CONFIG_DIR, *, today: Optional[date] = None) -> list[dict[str, Any]]:
    """Every ``disabled_until`` block under ``config_dir`` (top level and one directory down), sorted by due date.
    Dotfiles (``.env`` and friends) are never read (F13)."""
    root = Path(config_dir)
    pats = ("*.yaml", "*.yml", "*.json", "*/*.yaml", "*/*.json")
    files = sorted(
        {
            f
            for pat in pats
            for f in root.glob(pat)
            if not any(part.startswith(".") for part in f.relative_to(root).parts)
        }
    )
    found = [e for e in (entry_for(f, today=today) for f in files) if e]
    return sorted(found, key=lambda e: (e.get("review_by") or "0000", e["name"]))


def note(entry: Optional[dict[str, Any]], label: str) -> str:
    """Phone-length status, e.g. ``curation: OFF — pending review, due 2026-11-07``."""
    if not entry:
        return f"{label}: ON"
    due = entry.get("review_by") or "date missing"
    word = "OVERDUE since" if entry.get("overdue") else "pending review, due"
    return f"{label}: OFF — {word} {due}"
