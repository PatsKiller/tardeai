"""Render-time agent gate status, read from the measurement store.

Why this exists (governance truth repair, 2026-09-25): the maturity catalog
carried "11/12 gates passing" as prose from 2026-08-09 while the hourly
measurement (scripts/cio_gate_measurement_bridge.py --write-measurements)
said 0/12. A committed file cannot hold a runtime measurement without going
stale, so gate status is read here, at render time, from the store the bridge
writes, and every answer carries its as_of, denominator, source and the served
release it was read under.

Semantics
---------
* ``MEASURED``        store row exists and is younger than ``max_age_hours``.
* ``STALE``           store row exists but is older — counts are shown, labelled
                      stale, never presented as current.
* ``NOT_YET_MEASURED`` no store, no row for the agent, or unreadable store.
  Never a passing value.

AUTHORITY: READ_ONLY_ADVISORY. Reads one JSON file; writes nothing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "AgentGateStatus@v1"
MEASUREMENT_SCHEMA = "AgentGateMeasurement@v1"
MEASUREMENTS_RELPATH = ("data", "cio", "agent_gate_measurements.json")
# The bridge runs hourly; a few missed runs are tolerated before the status is
# labelled STALE. Overridable without a code change.
DEFAULT_MAX_AGE_HOURS = float(os.environ.get("AGENT_GATE_STATUS_MAX_AGE_HOURS", "6"))
SERVED_RELEASE_LINK = Path(
    os.environ.get(
        "TRADEAI_SERVED_RELEASE_LINK",
        str(Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"),
    )
)


def served_release_sha(link: Path | None = None) -> str | None:
    """Short SHA of the served release (``<sha>-main-exact-…`` dir name), or None."""
    try:
        name = Path(os.path.realpath(link or SERVED_RELEASE_LINK)).name
    except OSError:
        return None
    head = name.split("-", 1)[0]
    return head if head and all(c in "0123456789abcdef" for c in head) and len(head) >= 7 else None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def gate_status(
    root: Path,
    agent_id: str,
    *,
    now: datetime | None = None,
    max_age_hours: float | None = None,
    served_sha: str | None = None,
    measurements_path: Path | None = None,
) -> dict[str, Any]:
    """Return the current gate status for ``agent_id`` from the measurement store."""
    path = measurements_path or Path(root).joinpath(*MEASUREMENTS_RELPATH)
    limit = DEFAULT_MAX_AGE_HOURS if max_age_hours is None else float(max_age_hours)
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "agent_id": agent_id,
        "source": str(path),
        "source_schema": MEASUREMENT_SCHEMA,
        "served_release_sha": served_sha if served_sha is not None else served_release_sha(),
        "max_age_hours": limit,
        "status": "NOT_YET_MEASURED",
        "as_of": None,
        "age_hours": None,
        "denominator": None,
        "passing": None,
        "failing": None,
        "not_measured": None,
        "promotable": False,
    }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {**base, "reason": "measurement store absent"}
    except (OSError, ValueError) as exc:
        return {**base, "reason": f"measurement store unreadable ({type(exc).__name__})"}
    agent = ((doc.get("agents") or {}).get(agent_id) or {}) if isinstance(doc, Mapping) else {}
    gates = agent.get("gates") if isinstance(agent, Mapping) else None
    if not isinstance(gates, Mapping) or not gates:
        return {**base, "reason": f"no gate rows for {agent_id!r} in the store"}
    as_of = _parse_ts(doc.get("measured_at"))
    statuses = [str((g or {}).get("status") or "NOT_YET_MEASURED") for g in gates.values()]
    passing = sum(1 for s in statuses if s == "PASS")
    not_measured = sum(1 for s in statuses if s == "NOT_YET_MEASURED")
    failing = len(statuses) - passing - not_measured
    age = None
    if as_of is not None:
        age = round(((now or datetime.now(timezone.utc)) - as_of).total_seconds() / 3600.0, 2)
    status = "MEASURED" if age is not None and age <= limit else "STALE"
    return {
        **base,
        "status": status,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": age,
        "denominator": len(statuses),
        "passing": passing,
        "failing": failing,
        "not_measured": not_measured,
        # Promotion stays HUMAN_ONLY; this only reports the measured precondition.
        "promotable": status == "MEASURED" and passing == len(statuses),
        "reason": None if status == "MEASURED" else f"measurement older than {limit}h",
    }
