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


def entry_for(path: Path | str, *, today: Optional[date] = None, data: Any = None) -> Optional[dict[str, Any]]:
    """The ``disabled_until`` entry of one config file, or None. A malformed block is reported, never skipped."""
    p = Path(path)
    today = today or date.today()
    if data is None:
        try:
            data = _load(p)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return {"name": p.stem, "file": p.name, "error": f"unreadable: {type(exc).__name__}", "overdue": True}
    if not isinstance(data, dict) or "disabled_until" not in data:
        return None
    blk = data.get("disabled_until")
    name = p.stem
    if not isinstance(blk, dict):
        return {"name": name, "file": p.name, "error": "disabled_until is not a mapping", "overdue": True}
    missing = [k for k in REQUIRED if not blk.get(k)]
    review = _as_date(blk.get("review_by"))
    out = {
        "name": str(blk.get("name") or name),
        "file": p.name,
        "reason": blk.get("reason"),
        "disabled_at": str(blk.get("disabled_at") or ""),
        "review_by": review.isoformat() if review else None,
        "owner": blk.get("owner"),
        "reenable_plan": blk.get("reenable_plan"),
        "days_left": (review - today).days if review else None,
        "overdue": review is None or review < today,
    }
    if missing or review is None:
        out["error"] = "missing " + ", ".join(missing or ["review_by date"])
    return out


def scan(config_dir: Path | str = CONFIG_DIR, *, today: Optional[date] = None) -> list[dict[str, Any]]:
    """Every ``disabled_until`` block under ``config_dir`` (top level and one directory down), sorted by due date."""
    root = Path(config_dir)
    files: Iterable[Path] = sorted(
        [
            *root.glob("*.yaml"),
            *root.glob("*.yml"),
            *root.glob("*.json"),
            *root.glob("*/*.yaml"),
            *root.glob("*/*.json"),
        ]
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
