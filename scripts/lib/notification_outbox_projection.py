"""notification_outbox_projection.py — read-only projection of send state (roadmap Phase 2 PR-A, 2026-10-08).

One view of what the senders did: `communication_outbox` (status: sent / suppressed / recorded / unknown /
withdrawn, with `last_error` as the reason) and `telegram_outbox` (ok true/false per delivery). n8n never sends;
this module never writes. Pure over a `db_query(sql, params) -> rows` callable so tests stub rows.

    project_outbox(db_query, hours=24)            -> NotificationOutboxProjection@v1
    anomalies(model)                               -> incident fan-in findings (WITHDRAWN, stuck pending, suppression spike)
    load_outbox(hours=24, timeout_s=3.0)           -> project_outbox over the live DB with a statement timeout

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

SCHEMA = "NotificationOutboxProjection@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
# `recorded` is TERMINAL for communication_outbox (65k rows, attempt_count 0, since 2026-09-05): a send that was
# logged and never attempted. Only queue-like states can be "stuck".
PENDING_STATES = frozenset({"pending", "queued", "scheduled"})
STUCK_PENDING_MIN = 30
# Suppression is this system's steady state (dedupe), not an anomaly: ~90% of rows. The anomaly is silence:
# rows arriving but nothing sent at all.
SILENT_SENDERS_MIN_ROWS = 20
MAX_ITEMS = 500

COMM_SQL = (
    "SELECT outbox_id, event_id, channel, status, attempt_count, last_error, created_at, updated_at "
    "FROM communication_outbox WHERE created_at > now() - make_interval(hours => %s) "
    "ORDER BY created_at DESC LIMIT %s"
)
TG_SQL = (
    "SELECT id, sent_at, report_type, title, char_len, ok, channel "
    "FROM telegram_outbox WHERE sent_at > now() - make_interval(hours => %s) "
    "ORDER BY sent_at DESC LIMIT %s"
)

DbQuery = Callable[[str, tuple], list]


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v)


def _age_min(v: Any, now: datetime) -> Optional[float]:
    if v is None:
        return None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return round((now - d).total_seconds() / 60.0, 1)
    except (TypeError, ValueError):
        return None


def project_outbox(db_query: DbQuery, *, hours: int = 24, now: Optional[datetime] = None,
                   state: Optional[str] = None, limit: int = MAX_ITEMS) -> dict[str, Any]:
    """Rows + counts per (outbox, state) for the window. `state` filters the items, never the counts."""
    now = now or datetime.now(timezone.utc)
    hours = max(1, int(hours))
    items: list[dict[str, Any]] = []
    for r in db_query(COMM_SQL, (hours, limit)):
        outbox_id, event_id, channel, status, attempts, last_error, created_at, updated_at = r
        st = str(status or "unknown").lower()
        items.append({"outbox": "communication_outbox", "id": str(outbox_id), "state": st,
                      "reason": (str(last_error)[:160] if last_error else ""), "channel": str(channel or ""),
                      "subject": str(event_id or ""), "attempts": int(attempts or 0),
                      "created_at": _iso(created_at), "updated_at": _iso(updated_at), "age_min": _age_min(created_at, now)})
    for r in db_query(TG_SQL, (hours, limit)):
        tid, sent_at, report_type, title, char_len, ok, channel = r
        st = "sent" if ok else "failed"
        items.append({"outbox": "telegram_outbox", "id": str(tid), "state": st,
                      "reason": "" if ok else f"ok=false char_len={char_len}", "channel": str(channel or ""),
                      "subject": str(report_type or title or "")[:120], "attempts": 1,
                      "created_at": _iso(sent_at), "updated_at": _iso(sent_at), "age_min": _age_min(sent_at, now)})
    counts: dict[str, dict[str, int]] = {}
    for it in items:
        c = counts.setdefault(it["outbox"], {})
        c[it["state"]] = c.get(it["state"], 0) + 1
    shown = [it for it in items if not state or it["state"] == state.lower()]
    shown.sort(key=lambda it: it["created_at"] or "", reverse=True)
    return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "window_hours": hours,
            "status": "OK", "counts": counts, "count": len(shown), "total": len(items), "items": shown,
            "note": "sent state as the senders recorded it; n8n never sends"}


def anomalies(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Fan-in findings. Each is open while the condition holds in the window."""
    out: list[dict[str, Any]] = []
    items = model.get("items") or []
    withdrawn = [it for it in items if it["state"] == "withdrawn"]
    for it in withdrawn:
        out.append({"source": "outbox", "item": f"withdrawn:{it['outbox']}:{it['id']}", "severity": "P2",
                    "detail": f"{it['channel']} {it['subject']} {it['reason']}"[:160], "detected_at": it["created_at"]})
    for it in items:
        if it["state"] in PENDING_STATES and (it["age_min"] or 0) > STUCK_PENDING_MIN:
            out.append({"source": "outbox", "item": f"stuck_pending:{it['outbox']}:{it['id']}", "severity": "P2",
                        "detail": f"{it['state']} for {it['age_min']} min {it['channel']} {it['subject']}"[:160],
                        "detected_at": it["created_at"]})
    sent = sum(1 for it in items if it["state"] == "sent")
    if len(items) >= SILENT_SENDERS_MIN_ROWS and sent == 0:
        out.append({"source": "outbox", "item": "silent_senders", "severity": "P2",
                    "detail": f"{len(items)} outbox rows in the last {model.get('window_hours')} h and none sent",
                    "detected_at": model.get("as_of")})
    return out


def db_query_with_timeout(timeout_s: float = 3.0) -> DbQuery:
    """A read-only query callable over the shared adapter connection with a statement timeout; rolls back."""
    import sys
    from pathlib import Path
    scripts = str(Path(__file__).resolve().parents[1])
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from db_adapter import _get_conn  # type: ignore

    def q(sql: str, params: tuple) -> list:
        conn = _get_conn()
        if conn is None:
            raise RuntimeError("no_db_connection")
        cur = conn.cursor()
        try:
            cur.execute("SET LOCAL statement_timeout = %s", (int(timeout_s * 1000),))
            cur.execute(sql, params)
            return list(cur.fetchall())
        finally:
            try:
                conn.rollback()
            except Exception:
                pass
    return q


def load_outbox(hours: int = 24, timeout_s: float = 3.0, *, state: Optional[str] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """Live projection; a missing DB is an honest UNAVAILABLE model, never an exception."""
    if os.environ.get("TRADEAI_OUTBOX_PROJECTION", "1") == "0":
        return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": (now or datetime.now(timezone.utc)).isoformat(),
                "status": "DISABLED", "counts": {}, "count": 0, "total": 0, "items": [], "note": "TRADEAI_OUTBOX_PROJECTION=0"}
    if not os.environ.get("DB_PASSWORD"):
        # No rendered DB env (tests, CI, a shell without `. /run/user/$UID/tradeai/env`): never try to connect.
        return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": (now or datetime.now(timezone.utc)).isoformat(),
                "window_hours": hours, "status": "UNAVAILABLE", "counts": {}, "count": 0, "total": 0, "items": [],
                "note": "no_db_env: DB_PASSWORD not in the environment"}
    try:
        return project_outbox(db_query_with_timeout(timeout_s), hours=hours, now=now, state=state)
    except Exception as exc:  # noqa: BLE001 — the reason is the payload
        return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": (now or datetime.now(timezone.utc)).isoformat(),
                "window_hours": hours, "status": "UNAVAILABLE", "counts": {}, "count": 0, "total": 0, "items": [],
                "note": f"{type(exc).__name__}: {str(exc)[:120]}"}
