"""Read data/runtime/maturity_score_latest.json without treating a stale score as current.

The on-disk artifact is left in place. A payload whose generated_at is older than
30 days is stamped STALE and keeps its original generated_at and score. The
archived copy at data/runtime/archive/maturity_score_latest.json is never opened.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LIVE_REL = "data/runtime/maturity_score_latest.json"
ARCHIVE_REL = "data/runtime/archive/maturity_score_latest.json"
BASENAME = "maturity_score_latest.json"
STALE_AFTER = timedelta(days=30)


class ArchivedMaturityScoreRefused(RuntimeError):
    """The archived maturity-score path is not current and must not be read."""


def persistent_maturity_score_path() -> Path:
    return Path("/home/johnclaw/trade-ai-releases/persistent-state") / LIVE_REL


def is_archived_maturity_score_path(path: Path | str) -> bool:
    """True when the path is the archived copy, not the live artifact."""
    parts = Path(str(path)).parts
    if not parts or parts[-1] != BASENAME:
        return False
    return "archive" in parts[:-1]


def parse_generated_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stamp_maturity_score_payload(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Copy payload. Stamp STALE when generated_at is missing or older than 30 days.

    Does not replace the score and does not rewrite generated_at to now.
    """
    if not isinstance(payload, dict):
        raise TypeError("maturity score payload must be an object")
    out = dict(payload)
    original = out.get("generated_at")
    out["original_generated_at"] = original
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    else:
        clock = clock.astimezone(timezone.utc)
    generated = parse_generated_at(original)
    stale = generated is None or (clock - generated) > STALE_AFTER
    if stale:
        out["freshness"] = "STALE"
        out["status"] = "STALE"
        out["current"] = False
        return out
    out["current"] = True
    out["freshness"] = "WITHIN_30D"
    out["status"] = "WITHIN_30D"
    return out


def read_maturity_score_latest(path: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    """Read one live score file. Raises before any read if path is the archive copy."""
    candidate = Path(path)
    if is_archived_maturity_score_path(candidate):
        raise ArchivedMaturityScoreRefused(str(candidate))
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {
            "freshness": "STALE",
            "status": "STALE",
            "current": False,
            "original_generated_at": None,
            "generated_at": None,
        }
    return stamp_maturity_score_payload(data, now=now)


def _age_hours(generated_at: Any, now: datetime) -> float | None:
    parsed = parse_generated_at(generated_at)
    if parsed is None:
        return None
    clock = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return round((clock - parsed).total_seconds() / 3600.0, 3)


def select_live_maturity_score_path(root: Path) -> Path | None:
    """Live artifact only. The archive path is not a candidate and is not opened."""
    for cand in (persistent_maturity_score_path(), Path(root) / LIVE_REL):
        if is_archived_maturity_score_path(cand):
            continue
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def historical_maturity_body(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Metadata for the served maturity surface. Omits the 0–5 score.

    The archived copy is named so callers can see it was refused, and it is not read.
    """
    clock = now or datetime.now(timezone.utc)
    refused_archive = {
        "path": ARCHIVE_REL,
        "disposition": "REFUSED_NOT_CURRENT",
        "read": False,
        "current": False,
    }
    live = select_live_maturity_score_path(root)
    if live is None:
        return {
            "path": LIVE_REL,
            "generated_at": None,
            "original_generated_at": None,
            "freshness": None,
            "status": "ABSENT",
            "current": False,
            "staleness_hours": None,
            "disposition": "SUPERSEDED_NOT_DELETED",
            "archive_copy_path": ARCHIVE_REL,
            "archive_copy_disposition": refused_archive["disposition"],
            "reason": (
                "Live maturity_score_latest.json is absent; "
                "the archived copy is not current and is not read"
            ),
        }
    try:
        stamped = read_maturity_score_latest(live, now=clock)
    except ArchivedMaturityScoreRefused:
        return {
            "path": ARCHIVE_REL,
            "generated_at": None,
            "original_generated_at": None,
            "freshness": "STALE",
            "status": "STALE",
            "current": False,
            "staleness_hours": None,
            "disposition": "REFUSED_NOT_CURRENT",
            "archive_copy_path": ARCHIVE_REL,
            "archive_copy_disposition": "REFUSED_NOT_CURRENT",
            "reason": "Archived maturity score is not current",
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {
            "path": str(live),
            "generated_at": None,
            "original_generated_at": None,
            "freshness": "STALE",
            "status": "STALE",
            "current": False,
            "staleness_hours": None,
            "disposition": "SUPERSEDED_NOT_DELETED",
            "archive_copy_path": ARCHIVE_REL,
            "archive_copy_disposition": refused_archive["disposition"],
            "reason": "Maturity score file was unreadable and is not current",
        }
    original = stamped.get("original_generated_at")
    stale = stamped.get("freshness") == "STALE"
    return {
        "path": str(live),
        "generated_at": original,
        "original_generated_at": original,
        "freshness": stamped.get("freshness"),
        "status": stamped.get("status"),
        "current": False if stale else bool(stamped.get("current")),
        "staleness_hours": _age_hours(original, clock),
        "disposition": "SUPERSEDED_NOT_DELETED",
        "archive_copy_path": ARCHIVE_REL,
        "archive_copy_disposition": refused_archive["disposition"],
        "reason": (
            "generated_at is older than 30 days; the score is not current"
            if stale
            else "Score file is within 30 days and is still not a certification"
        ),
    }
