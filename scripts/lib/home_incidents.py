"""GET /api/v2/home/incidents — open incidents for Home's Action-now and Open-risks rows (LQ-20261107-2147).

Reads ``alert_incidents`` (the recurring condition: category, severity, first seen, occurrence count) and the
latest ``alert_occurrences`` payload for an individual incident's ``blocks_trading`` declaration. Writes
nothing. The rules the operator approved on 2026-11-11 (Home v010 DECISION.md):

* Unknown never reads as OK. A failed read is ``status: UNKNOWN`` with the reason and ``open_count: null``;
  it is never an empty list.
* A P1 incident does not block trading by default; it blocks only if its latest occurrence declares
  ``blocks_trading: true``. This module reports the flag, it does not decide trade-readiness.
* Every value carries its age and the threshold it is judged by (``last_seen_age_sec`` against
  ``stale_after_sec``): an incident not re-observed within the threshold is drawn as STALE, not dropped.
* cause / source / owner come from the 2149 registry (``config/incident_registry.json``, keyed by
  ``alert_type``) when it exists and has the type; otherwise each is ``"UNKNOWN"``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "HomeIncidents@v1"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "incident_registry.json"
#: An open incident that has not been observed again within this window is flagged STALE.
STALE_AFTER_SEC = 3600
#: A complete read of the open set, newest-severity first; the page paginates by showing "+N more".
MAX_ROWS = 500
SEVERITY_RANK = {"critical": 0, "urgent": 1, "warning": 2, "info": 3}
UNKNOWN = "UNKNOWN"

SQL = """
SELECT i.incident_id, i.alert_type, i.digest_bucket, i.severity, i.status, i.symbol,
       i.source_system, i.source_producer, i.operator_action_required,
       i.first_seen_at, i.last_seen_at, i.occurrence_count, i.acknowledged_at,
       (SELECT o.payload -> 'blocks_trading'
          FROM alert_occurrences o WHERE o.incident_id = i.incident_id
         ORDER BY o.occurrence_seq DESC LIMIT 1) AS blocks_trading_declared
  FROM alert_incidents i
 WHERE i.status = 'open' AND NOT i.synthetic AND i.environment = 'production'
 ORDER BY i.first_seen_at ASC
 LIMIT %s
"""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    """``{alert_type: {cause, source, owner}}`` or ``{}`` when the registry is absent or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("types") if isinstance(data, dict) and isinstance(data.get("types"), dict) else data
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)} if isinstance(entries, dict) else {}


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _age(v: Any, now: datetime) -> Optional[int]:
    if not isinstance(v, datetime):
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return max(0, int((now - v).total_seconds()))


def _blocks(declared: Any) -> bool:
    return declared is True or (isinstance(declared, str) and declared.strip().lower() == "true")


def shape(row: dict, registry: dict[str, dict], now: datetime) -> dict:
    reg = registry.get(str(row.get("alert_type"))) or {}
    seen_age = _age(row.get("last_seen_at"), now)
    return {
        "incident_id": row.get("incident_id"),
        "category": row.get("alert_type") or UNKNOWN,
        "bucket": row.get("digest_bucket"),
        "severity": row.get("severity") or UNKNOWN,
        "symbol": row.get("symbol"),
        "first_seen_at": _iso(row.get("first_seen_at")),
        "first_seen_age_sec": _age(row.get("first_seen_at"), now),
        "last_seen_at": _iso(row.get("last_seen_at")),
        "last_seen_age_sec": seen_age,
        "stale_after_sec": STALE_AFTER_SEC,
        "stale": seen_age is None or seen_age > STALE_AFTER_SEC,
        "count": row.get("occurrence_count"),
        "blocks_trading": _blocks(row.get("blocks_trading_declared")),
        "operator_action_required": bool(row.get("operator_action_required")),
        "acknowledged": row.get("acknowledged_at") is not None,
        "reported_by": row.get("source_producer") or row.get("source_system") or UNKNOWN,
        "cause": reg.get("cause") or UNKNOWN,
        "source": reg.get("source") or UNKNOWN,
        "owner": reg.get("owner") or UNKNOWN,
    }


def build(db_query: Callable[..., Any], *, now: Optional[datetime] = None, registry: Optional[dict] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    reg = load_registry() if registry is None else registry
    base = {"schema": SCHEMA, "as_of": now.isoformat(), "stale_after_sec": STALE_AFTER_SEC,
            "registry": "present" if reg else "absent"}
    try:
        rows = db_query(SQL, (MAX_ROWS,), fetch="all")
    except Exception as exc:  # noqa: BLE001 -- named in the body, never an empty list
        return {**base, "status": UNKNOWN, "open_count": None, "incidents": None,
                "reason": f"alert_incidents could not be read ({type(exc).__name__})"}
    if rows is None:
        return {**base, "status": UNKNOWN, "open_count": None, "incidents": None,
                "reason": "alert_incidents read returned no result"}
    items = [shape(dict(r), reg, now) for r in rows]
    items.sort(key=lambda i: (SEVERITY_RANK.get(str(i["severity"]).lower(), 9), i["first_seen_at"] or ""))
    return {**base, "status": "OK", "open_count": len(items), "truncated": len(items) >= MAX_ROWS,
            "blocks_trading_count": sum(1 for i in items if i["blocks_trading"]),
            "incidents": items}
