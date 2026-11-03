"""Stale-guidance gates — an advisory or a stop prompt may not render as current when it is not.

Why this exists (operator P0 2026-11-03, Board row 33 piece E):
On 2026-10-30 SPCX stopped out at 137.19. On 2026-11-03 the price was 141.65 — above that stop — yet Home
still showed "SPCX is below its stop" and the CIO home still carried an "Advisory TRIM — SPCX" label whose
narrative dated from 2026-10-07. The operator was looking at guidance that was true when it was written and
false when he read it.

Two rules, both pure and both testable without a live store:

* **Age.** An advisory narrative older than ``max_narrative_age_days`` (default 14) or evidence older than
  ``max_evidence_age_days`` (default 30) is STALE. Stale guidance may be shown as history, never as current.
* **Reality.** A stop prompt renders only while the price is at or below the stop on record. A row that still
  carries ``triggered`` from an event that has since passed (price recovered) is stale, not a live breach.

A missing or unparseable date is "age unknown" and is NOT treated as stale: the gate fires only on guidance
we can prove is old, so a source that carries no narrative clock is not silently dropped.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_MAX_NARRATIVE_AGE_DAYS = 14
DEFAULT_MAX_EVIDENCE_AGE_DAYS = 30
SECONDS_PER_DAY = 86400.0


def _parse_ts(value: Any) -> Optional[datetime]:
    """A tolerant ISO-8601 parser for the date shapes this system stores. None when unusable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_days(value: Any, now: datetime) -> Optional[float]:
    """Age in days of an ISO timestamp, or None when it cannot be read."""
    dt = _parse_ts(value)
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds() / SECONDS_PER_DAY)


def advisory_freshness(opportunity: dict, now: datetime, *, max_narrative_age_days: int = DEFAULT_MAX_NARRATIVE_AGE_DAYS,
                       max_evidence_age_days: int = DEFAULT_MAX_EVIDENCE_AGE_DAYS) -> dict:
    """``{"stale": bool, "reason": str|None, "age_days": float|None}`` for one advisory row.

    ``narrative_at`` is when the analysis behind the label was written; ``evidence_at`` (optional) is the
    freshest underlying fact. A row with no readable narrative date is age-unknown and is treated as stale:
    the cost of hiding a stale advisory is a missed prompt, the cost of showing a stale one as current is
    acting on a thesis the market already invalidated (2026-11-03, SPCX).
    """
    narrative_age = age_days(opportunity.get("narrative_at"), now)
    if narrative_age is None:
        # No readable date is "age unknown", not "stale": a queue row that carries no narrative clock
        # (most staging sources today) must not be silently dropped. The gate below applies only to
        # guidance we can PROVE is old.
        return {"stale": False, "reason": None, "age_days": None, "age_known": False}
    if narrative_age > max_narrative_age_days:
        return {"stale": True, "reason": f"narrative_older_than_{max_narrative_age_days}d",
                "age_days": round(narrative_age, 2), "age_known": True}
    evidence_age = age_days(opportunity.get("evidence_at"), now)
    if evidence_age is not None and evidence_age > max_evidence_age_days:
        return {"stale": True, "reason": f"evidence_older_than_{max_evidence_age_days}d",
                "age_days": round(narrative_age, 2), "age_known": True}
    return {"stale": False, "reason": None, "age_days": round(narrative_age, 2), "age_known": True}


def stop_prompt_is_stale(position: dict) -> bool:
    """True when a position row says its stop triggered but the price is no longer through the stop.

    ``distance_to_stop_pct`` is measured from the stop: > 0 means the price is ABOVE the stop on record, so
    a stored ``triggered`` flag is an event that has passed, not a live breach. An unknown distance is NOT
    treated as stale — a genuinely breached stop with an unmeasured distance must still page.
    """
    if not position.get("triggered"):
        return False
    try:
        distance = float(position.get("distance_to_stop_pct"))
    except (TypeError, ValueError):
        return False
    return distance > 0


def limits_from_env() -> dict:
    """The configured limits, with defaults. Never raises: a broken value falls back to the default."""
    def _int(name: str, default: int) -> int:
        try:
            value = int(os.environ.get(name) or default)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    return {"max_narrative_age_days": _int("TRADEAI_MAX_NARRATIVE_AGE_DAYS", DEFAULT_MAX_NARRATIVE_AGE_DAYS),
            "max_evidence_age_days": _int("TRADEAI_MAX_EVIDENCE_AGE_DAYS", DEFAULT_MAX_EVIDENCE_AGE_DAYS)}


__all__ = ["DEFAULT_MAX_NARRATIVE_AGE_DAYS", "DEFAULT_MAX_EVIDENCE_AGE_DAYS", "age_days",
           "advisory_freshness", "stop_prompt_is_stale", "limits_from_env"]
