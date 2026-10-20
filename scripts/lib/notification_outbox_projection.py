"""notification_outbox_projection.py — read-only projection of send state (roadmap Phase 2 PR-A, 2026-10-08).

One view of what the senders did: `communication_outbox` (status: sent / suppressed / recorded / unknown /
withdrawn, with `last_error` as the reason) and `telegram_outbox` (ok true/false per delivery). n8n never sends;
this module never writes. Pure over a `db_query(sql, params) -> rows` callable so tests stub rows.

    project_outbox(db_query, hours=24)            -> NotificationOutboxProjection@v2
    anomalies(model)                               -> incident fan-in findings (WITHDRAWN, stuck pending, suppression spike)
    load_outbox(hours=24, timeout_s=3.0)           -> project_outbox over the live DB with a statement timeout

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Optional

SCHEMA = "NotificationOutboxProjection@v2"
LEGACY_SCHEMA = "NotificationOutboxProjection@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
# `recorded` is TERMINAL for communication_outbox (65k rows, attempt_count 0, since 2026-09-05): a send that was
# logged and never attempted. Only queue-like states can be "stuck".
PENDING_STATES = frozenset({"pending", "queued", "scheduled"})
STUCK_PENDING_MIN = 30
# Suppression is this system's steady state (dedupe), not an anomaly: ~90% of rows. The anomaly is silence:
# rows arriving but nothing sent at all.
SILENT_SENDERS_MIN_ROWS = 20
MAX_ITEMS = 500

COMM_WHERE = " FROM communication_outbox WHERE created_at >= %s AND created_at <= %s"
TG_WHERE = " FROM telegram_outbox WHERE sent_at >= %s AND sent_at <= %s"
TG_STATE = "CASE WHEN ok IS TRUE THEN 'sent' WHEN ok IS FALSE THEN 'failed' ELSE 'unknown' END"
COMM_SQL = "SELECT outbox_id,event_id,channel,status,attempt_count,last_error,created_at,updated_at"
TG_SQL = "SELECT id,sent_at,report_type,title,char_len,ok,channel"
COUNTS_SQL = ("SELECT 'communication_outbox',LOWER(COALESCE(NULLIF(status,''),'unknown')),COUNT(*)"+COMM_WHERE+
    " GROUP BY LOWER(COALESCE(NULLIF(status,''),'unknown')) UNION ALL SELECT 'telegram_outbox',"+TG_STATE+",COUNT(*)"+TG_WHERE+" GROUP BY "+TG_STATE)
_LAST_GOOD = {}

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
    """One fixed UTC window; full SQL aggregates and independently bounded detail rows.

    Production callable supplies a repeatable-read read-only transaction. Test/adapter
    callers without snapshot() explicitly retain caller-managed read consistency.
    """
    now=now or datetime.now(timezone.utc);hours=max(1,min(int(hours),24*31));limit=max(1,min(int(limit),MAX_ITEMS))
    since=now-timedelta(hours=hours);items=[];counts={}
    snapshot=getattr(db_query,"snapshot",None)
    with snapshot() if snapshot else nullcontext():
        for outbox,st,n in db_query(COUNTS_SQL,(since,now,since,now)):
            if outbox not in ('communication_outbox','telegram_outbox') or type(n) is not int or n<0:
                raise ValueError('invalid full-window outbox aggregate')
            counts.setdefault(outbox,{})[str(st)]=n
        comm_filter=" AND LOWER(COALESCE(NULLIF(status,''),'unknown')) = %s" if state else ""
        tg_filter=" AND "+TG_STATE+" = %s" if state else ""
        params=(since,now,str(state).lower(),limit) if state else (since,now,limit)
        for r in db_query(COMM_SQL+COMM_WHERE+comm_filter+" ORDER BY created_at DESC LIMIT %s",params):
            oid,event,channel,status,attempts,error,created,updated=r
            items.append({"outbox":"communication_outbox","id":str(oid),"state":str(status or 'unknown').lower(),
                "reason":str(error)[:160] if error else "","channel":str(channel or ""),"subject":str(event or ""),
                "attempts":int(attempts) if attempts is not None else None,"created_at":_iso(created),"updated_at":_iso(updated),"age_min":_age_min(created,now)})
        for r in db_query(TG_SQL+TG_WHERE+tg_filter+" ORDER BY sent_at DESC LIMIT %s",params):
            tid,sent,report,title,chars,ok,channel=r
            st='sent' if ok is True else 'failed' if ok is False else 'unknown'
            items.append({"outbox":"telegram_outbox","id":str(tid),"state":st,"reason":"" if ok is True else "delivery status unavailable" if ok is None else f"ok=false char_len={chars}",
                "channel":str(channel or ""),"subject":str(report or title or "")[:120],"attempts":1,
                "created_at":_iso(sent),"updated_at":_iso(sent),"age_min":_age_min(sent,now)})
    total=sum(sum(c.values()) for c in counts.values())
    matched=sum(c.get(str(state).lower(),0) for c in counts.values()) if state else total
    shown=[r for r in items if not state or r['state']==str(state).lower()]
    shown.sort(key=lambda r:r['created_at'] or '',reverse=True)
    if len(shown)>matched:raise ValueError('outbox detail/aggregate snapshot contradiction')
    _LAST_GOOD[hours]=now.isoformat()
    return {"schema":SCHEMA,"authority":AUTHORITY,"as_of":now.isoformat(),"window_hours":hours,"status":"OK",
        "counts":counts,"count":len(shown),"total":total,"matched_total":matched,"items":shown,
        "last_good_at":now.isoformat(),"last_good_age_s":0,
        "coverage":{"since":since.isoformat(),"through":now.isoformat(),"aggregation_complete":True,
                    "detail_limit_per_source":limit,"returned_rows":len(shown),"matched_total":matched,
                    "items_truncated":matched>len(shown),"snapshot_consistent":bool(snapshot),
                    "read_consistency":"repeatable_read_read_only" if snapshot else "caller_managed",
                    "qualification":"Counts cover recorded outbox states in this exact window; item details are bounded. Sent, delivered, acknowledged and business-recovered are separate states."},
        "note":"Sender-recorded state only; no provider delivery/acknowledgement proof is inferred. n8n never sends"}


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
    complete=model.get("schema")==SCHEMA and (model.get("coverage") or {}).get("aggregation_complete") is True
    counts=model.get("counts") or {}
    total=sum(sum(c.values()) for c in counts.values())
    sent=sum(c.get("sent",0) for c in counts.values())
    known_states={"sent","failed","suppressed","withdrawn","recorded",*PENDING_STATES}
    unknown=sum(n for c in counts.values() for st,n in c.items() if st not in known_states)
    if complete and total >= SILENT_SENDERS_MIN_ROWS and sent == 0 and unknown == 0:
        out.append({"source": "outbox", "item": "silent_senders", "severity": "P2",
                    "detail": f"{total} outbox rows in the last {model.get('window_hours')} h; no row recorded sent",
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

    active={"conn":None,"deadline":None}
    @contextmanager
    def snapshot():
        conn=_get_conn()
        if conn is None:raise RuntimeError("no_db_connection")
        active["conn"]=conn
        active["deadline"]=time.monotonic()+timeout_s
        try:
            conn.rollback()
            cur=conn.cursor()
            cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout = %s",(int(timeout_s*1000),))
            cur.close()
            yield
        finally:
            active["conn"]=None
            conn.rollback()
    def q(sql: str, params: tuple) -> list:
        conn=active["conn"]
        if conn is None:raise RuntimeError("read-only snapshot required")
        remaining=active["deadline"]-time.monotonic()
        if remaining<=0:raise TimeoutError("outbox read deadline exceeded")
        cur=conn.cursor()
        try:
            cur.execute("SET LOCAL statement_timeout = %s",(max(1,int(remaining*1000)),))
            cur.execute(sql,params)
            return list(cur.fetchall())
        finally:cur.close()
    q.snapshot=snapshot
    return q


def load_outbox(hours: int = 24, timeout_s: float = 3.0, *, state: Optional[str] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """Live projection; a missing DB is an honest UNAVAILABLE model, never an exception."""
    if os.environ.get("TRADEAI_OUTBOX_PROJECTION", "1") == "0":
        return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": (now or datetime.now(timezone.utc)).isoformat(),
                "status": "DISABLED", "counts": None, "count": None, "total": None, "items": [], "note": "TRADEAI_OUTBOX_PROJECTION=0"}
    if not os.environ.get("DB_PASSWORD"):
        # No rendered DB env (tests, CI, a shell without `. /run/user/$UID/tradeai/env`): never try to connect.
        return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": (now or datetime.now(timezone.utc)).isoformat(),
                "window_hours": hours, "last_good_at":_LAST_GOOD.get(hours),"last_good_age_s":None if hours not in _LAST_GOOD else _age_min(_LAST_GOOD[hours],now or datetime.now(timezone.utc))*60, "status": "UNAVAILABLE", "counts": None, "count": None, "total": None, "items": [],
                "note": "no_db_env: DB_PASSWORD not in the environment"}
    try:
        return project_outbox(db_query_with_timeout(timeout_s), hours=hours, now=now, state=state)
    except Exception as exc:  # noqa: BLE001 — the reason is the payload
        return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": (now or datetime.now(timezone.utc)).isoformat(),
                "window_hours": hours, "last_good_at":_LAST_GOOD.get(hours),"last_good_age_s":None if hours not in _LAST_GOOD else _age_min(_LAST_GOOD[hours],now or datetime.now(timezone.utc))*60, "status": "UNAVAILABLE", "counts": None, "count": None, "total": None, "items": [],
                "note": f"{type(exc).__name__}: {str(exc)[:120]}"}
