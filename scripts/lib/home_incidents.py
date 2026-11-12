"""GET /api/v2/home/incidents -> ``HomeIncidents@v1`` (LQ-20261107-2147, spec HOME-BACKEND-SPEC-20261111).

Reads ``alert_incidents`` (open conditions) + the latest ``alert_occurrences`` payload, and ``alert_events``
with ``alert_type='data_integrity'`` (24 h evidence count). Writes nothing; a GET has no side effect.

* Category / priority / owner / ``ttl_h`` come from the 2149 class map, ``incident_classes`` in
  ``config/home_status_registry.json`` (keyed by ``alert_type``). A class that is not mapped is
  ``priority: "UNCLASSIFIED"`` -- shown and counted, never dropped. A class with ``home_visible: false`` is
  not listed (reported as ``hidden_count``). No registry file -> every item is UNCLASSIFIED, ``registry: absent``.
* ``blocks_trading``: the latest occurrence payload's own declaration wins; else the class's
  ``blocks_trading_default``; else false (Home v010: a P1 blocks only by declaring it).
* ``stale_condition`` is true when ``last_seen_at`` is older than the class ``ttl_h`` (not re-observed);
  shown labelled, never counted as fresh. Unknown ttl -> ``null``.
* Failure: unreadable -> ``state: UNKNOWN`` and counts ``null``; a statement timeout -> ``TIMED_OUT``.
  Never an empty list.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "HomeIncidents@v1"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "home_status_registry.json"
MAX_ROWS = 500
STATEMENT_TIMEOUT_MS = 2000
#: In-process cache of an OK body (spec 1.2: 30-60 s); the route owns the dict.
CACHE_TTL_S = 45
PRIORITY_RANK = {"P0": 0, "P1": 1, "UNCLASSIFIED": 2}
UNKNOWN = "UNKNOWN"
UNREGISTERED = "UNREGISTERED"

SQL = f"""
SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS};
SELECT i.incident_id, i.alert_type, i.digest_bucket, i.severity, i.symbol,
       i.source_system, i.source_producer, i.first_seen_at, i.last_seen_at, i.occurrence_count,
       (SELECT o.payload -> 'blocks_trading' FROM alert_occurrences o
         WHERE o.incident_id = i.incident_id ORDER BY o.occurrence_seq DESC LIMIT 1) AS blocks_trading_declared,
       (SELECT o.payload ->> 'account_label' FROM alert_occurrences o
         WHERE o.incident_id = i.incident_id ORDER BY o.occurrence_seq DESC LIMIT 1) AS account_label,
       (SELECT o.payload ->> 'cause' FROM alert_occurrences o
         WHERE o.incident_id = i.incident_id ORDER BY o.occurrence_seq DESC LIMIT 1) AS payload_cause
  FROM alert_incidents i
 WHERE i.status = 'open' AND NOT i.synthetic AND i.environment = 'production'
 ORDER BY i.first_seen_at ASC
 LIMIT %s
"""
SQL_INTEGRITY = f"""
SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS};
SELECT count(*) AS events FROM alert_events
 WHERE alert_type = 'data_integrity' AND created_at > now() - interval '24 hours'
"""


def load_classes(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    """``incident_classes`` of the HomeStatusRegistry, or ``{}`` when absent / unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        classes = data.get("incident_classes")
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(k): v for k, v in classes.items() if isinstance(v, dict)} if isinstance(classes, dict) else {}


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _age(v: Any, now: datetime) -> Optional[int]:
    if not isinstance(v, datetime):
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return max(0, int((now - v).total_seconds()))


def _declared(v: Any) -> Optional[bool]:
    if v is True or (isinstance(v, str) and v.strip().lower() == "true"):
        return True
    if v is False or (isinstance(v, str) and v.strip().lower() == "false"):
        return False
    return None


def shape(row: dict, classes: dict[str, dict], now: datetime) -> dict:
    atype = str(row.get("alert_type"))
    cls = classes.get(atype)
    seen_age = _age(row.get("last_seen_at"), now)
    first_age = _age(row.get("first_seen_at"), now)
    declared = _declared(row.get("blocks_trading_declared"))
    default = bool(cls.get("blocks_trading_default")) if cls else False
    ttl_h = cls.get("ttl_h") if cls else None
    ttl_ok = isinstance(ttl_h, (int, float)) and not isinstance(ttl_h, bool) and ttl_h > 0
    return {
        "incident_id": row.get("incident_id"),
        "alert_type": atype,
        "category": (cls.get("category") if cls else None) or atype,
        "priority": (cls.get("priority") if cls else None) or "UNCLASSIFIED",
        "blocks_trading": declared if declared is not None else default,
        "symbol": row.get("symbol"),
        "account_label": row.get("account_label"),
        "first_seen_at": _iso(row.get("first_seen_at")),
        "last_seen_at": _iso(row.get("last_seen_at")),
        "failed_checks": row.get("occurrence_count"),
        "failing_for_s": first_age,
        "owner": (cls.get("owner") if cls else None) or UNREGISTERED,
        "cause": (cls.get("cause") if cls else None) or row.get("payload_cause") or UNKNOWN,
        "ttl_h": ttl_h if ttl_ok else None,
        "last_seen_age_s": seen_age,
        "stale_condition": (seen_age is None or seen_age > ttl_h * 3600) if ttl_ok else None,
    }


def _is_timeout(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "statement timeout" in text or "querycanceled" in text or "timed out" in text or "timeout" in text


def _failed(base: dict, state: str, reason: str) -> dict:
    return {**base, "state": state, "reason": reason, "counts": None, "items": None, "data_integrity_24h": None,
            "source_id": "alert_incidents", "owner": UNREGISTERED}


def restamp(body: dict, held_s: int, *, now: Optional[datetime] = None) -> dict:
    """A cached body re-served ``held_s`` seconds after it was computed: ages are computed at serve time, never frozen."""
    now = now or datetime.now(timezone.utc)
    out = {**body, "served_at": now.isoformat(), "snapshot": {**(body.get("snapshot") or {}), "age_s": max(0, held_s)}}
    di = body.get("data_integrity_24h")
    if isinstance(di, dict) and di.get("age_s") is not None:
        out["data_integrity_24h"] = {**di, "age_s": di["age_s"] + max(0, held_s)}
    return out


def build(db_query: Callable[..., Any], *, now: Optional[datetime] = None, classes: Optional[dict] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cl = load_classes() if classes is None else classes
    base = {"schema": SCHEMA, "served_at": now.isoformat(), "registry": "present" if cl else "absent",
            "snapshot": {"computed_at": now.isoformat(), "age_s": 0}}
    try:
        rows = db_query(SQL, (MAX_ROWS,), fetch="all")
    except Exception as exc:  # noqa: BLE001 -- named in the body, never an empty list
        if _is_timeout(exc):
            return _failed(base, "TIMED_OUT", f"alert_incidents read exceeded {STATEMENT_TIMEOUT_MS} ms")
        return _failed(base, UNKNOWN, f"alert_incidents could not be read ({type(exc).__name__})")
    if rows is None:
        return _failed(base, UNKNOWN, "alert_incidents read returned no result")

    items, hidden = [], 0
    for r in rows:
        r = dict(r)
        cls = cl.get(str(r.get("alert_type")))
        if cls is not None and cls.get("home_visible") is False:
            hidden += 1
            continue
        items.append(shape(r, cl, now))
    items.sort(key=lambda i: (PRIORITY_RANK.get(i["priority"], 3), not i["blocks_trading"], i["first_seen_at"] or ""))
    counts = {"P0": sum(1 for i in items if i["priority"] == "P0"),
              "P1": sum(1 for i in items if i["priority"] == "P1"),
              "UNCLASSIFIED": sum(1 for i in items if i["priority"] == "UNCLASSIFIED"),
              "blocks_trading": sum(1 for i in items if i["blocks_trading"])}

    # data-integrity evidence: a separate read; its failure is its own UNKNOWN field, not an OK 0
    di = {"state": UNKNOWN, "value": None, "as_of": None, "age_s": None, "threshold_s": 86400,
          "threshold_basis": "fixed", "source_id": "alert_events:data_integrity", "owner": UNREGISTERED}
    try:
        r2 = db_query(SQL_INTEGRITY, None, fetch="one")
        if r2 is None:
            di["reason"] = "alert_events read returned no result"
        else:
            di.update(state="OK", value={"events": int(dict(r2).get("events") or 0), "invalid": None},
                      as_of=now.isoformat(), age_s=0)
    except Exception as exc:  # noqa: BLE001
        di["state"] = "TIMED_OUT" if _is_timeout(exc) else UNKNOWN
        di["reason"] = f"alert_events could not be read ({type(exc).__name__})"
    return {**base, "state": "OK", "reason": None, "counts": counts, "items": items,
            "hidden_count": hidden, "truncated": len(rows) >= MAX_ROWS, "data_integrity_24h": di}
