"""Read-only Command Center projection of the n8n coordination ledger (plan tranche B, 2026-10-07).

Plain-language job state for the operator: waiting / in progress / artifact / consumed / refused /
failed, with owner, due, age and an evidence link. Reads the SQLite ledger in read-only mode and
never opens n8n; n8n internals are not the operator's status page.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

NO_CONSUMER_REASON = "read by GET /api/v2/coordination/events (?source=runs for the runs table) in scripts/api_v2.py; no scheduled lane"
SCHEMA = "N8nCoordinationProjection@v2"
LEGACY_SCHEMA = "N8nCoordinationProjection@v1"
#: Wave B CC orchestrate lanes — Coordination UI spotlights these receipts first.
WAVE_B_LANES = ("research-intake", "watch-refresh", "incident-fanin")
WAVE_B_RUN_LANES = ("n8n-research-intake-consumer", "n8n-incident-fanin")
STATE_TEXT = {
    "EXPECTED": "waiting for the source to accept",
    "ACCEPTED": "accepted by the gateway, waiting to be claimed",
    "CLAIMED": "claimed by a worker",
    "STARTED": "in progress",
    "ARTIFACT_WRITTEN": "artifact written, waiting for a consumer",
    "CONSUMED": "consumed (receipt on file)",
    "REFUSED": "refused",
    "FAILED": "failed",
    "DEAD_LETTER": "dead letter (gave up)",
    "SUPPRESSED": "suppressed by policy",
    "SUPERSEDED": "superseded by a newer event",
    "CANCELLED": "cancelled",
    "EXPIRED": "expired before it was claimed",
}


def ledger_path(env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    explicit = env.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = env.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def state_root(env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state"))


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        with path.open("rb") as stream:
            raw=stream.read(512*1024+1)
        if len(raw)>512*1024:return None
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def lane_spotlights(env: Optional[dict] = None, *, now: Optional[_dt.datetime] = None) -> list[dict[str, Any]]:
    """Fail-soft spotlights for Wave B lanes + known host last.json receipts (never invent success)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    root = state_root(env)
    out: list[dict[str, Any]] = []
    # Wave B shadow/apply spotlights written by scripts/lib/n8n_cc_wave_b_emit.py
    spot = _read_json(root / "data" / "runtime" / "n8n_cc_wave_b" / "spotlights.json")
    lanes = (spot or {}).get("lanes") if isinstance((spot or {}).get("lanes"), dict) else {}
    for lane_id in WAVE_B_LANES:
        entry = lanes.get(lane_id) if isinstance(lanes.get(lane_id), dict) else None
        if entry:
            out.append({
                "lane_id": lane_id, "source": "wave_b_spotlight",
                "as_of": entry.get("as_of"), "mode": entry.get("mode"),
                "gateway_state": entry.get("gateway_state"),
                "idempotency_key": entry.get("idempotency_key"),
                "event_id": entry.get("event_id"),
                "summary": _spotlight_summary(lane_id, entry),
                "age_s": _age_s(entry.get("as_of"), now),
            })
        else:
            out.append({"lane_id":lane_id,"source":"wave_b_spotlight","status":"UNAVAILABLE", "as_of":None,
                        "mode":None,"age_s":None,"summary":"No readable spotlight record; current state unknown"})
    # Host consumer / fan-in last receipts (prove from files, not n8n execution status — W0 RC8)
    for rel, lane_id in (
        ("data/runtime/n8n_research_intake_last.json", "n8n-research-intake-consumer"),
        ("data/runtime/n8n_incident_fanin_last.json", "n8n-incident-fanin"),
    ):
        doc = _read_json(root / rel)
        if not doc:
            out.append({"lane_id":lane_id,"source":"host_receipt","path":rel,"status":"UNAVAILABLE",
                        "ok":None,"as_of":None,"age_s":None,"last_good_at":None,
                        "summary":"host receipt missing or unreadable"})
            continue
        as_of = doc.get("ok_at") or doc.get("as_of") or doc.get("finished_at") or doc.get("recorded_at")
        age = _age_s(str(as_of) if as_of else None, now)
        cadence = _lane_metadata(lane_id).get("expected_cadence_hours")
        limit_s = int(float(cadence) * 7200) if isinstance(cadence,(int,float)) and cadence > 0 else None
        availability = "UNAVAILABLE" if age is None else "STALE" if limit_s is not None and age > limit_s else "AVAILABLE"
        out.append({
            "lane_id": lane_id, "source": "host_receipt", "status":availability,
            "reported_ok":doc.get("ok"),"last_good_at":as_of if doc.get("ok") is True and age is not None else None,
            "last_good_age_s":age if doc.get("ok") is True else None,
            "freshness_limit_s":limit_s,"freshness_basis":"twice registered cadence; observation age only, not useful-output proof",
            "served_sha":doc.get("code_sha"),"run_id":doc.get("run_id"),"owner":_lane_metadata(lane_id).get("owner"),
            "as_of": as_of, "mode": doc.get("mode"),
            "ok": doc.get("ok") if availability == "AVAILABLE" else None, "summary": ("Last record: " if availability != "AVAILABLE" else "") + _host_receipt_summary(lane_id, doc),
            "age_s": _age_s(str(as_of) if as_of else None, now),
            "path": rel,
        })
    return out


def _spotlight_summary(lane_id: str, entry: dict[str, Any]) -> str:
    if lane_id == "research-intake":
        return f"{entry.get('request_type') or '?'} {entry.get('subject') or ''} · {entry.get('gateway_state') or '—'}"
    if lane_id == "watch-refresh":
        phase = entry.get("phase") or "?"
        rid = entry.get("run_id")
        term = entry.get("terminal_state")
        return f"run {rid} {phase}" + (f" → {term}" if term else "") + f" · {entry.get('gateway_state') or '—'}"
    return str(entry.get("gateway_state") or entry.get("idempotency_key") or lane_id)


def _host_receipt_summary(lane_id: str, doc: dict[str, Any]) -> str:
    if lane_id == "n8n-research-intake-consumer":
        listed = doc.get("listed") if doc.get("listed") is not None else doc.get("count")
        enq = doc.get("enqueued_today")
        return f"ok={doc.get('ok')} listed={listed} enqueued_today={enq}"
    if lane_id == "n8n-incident-fanin":
        return f"ok={doc.get('ok')} mode={doc.get('mode') or '—'}"
    return f"ok={doc.get('ok')}"


def _age_s(iso: Optional[str], now: _dt.datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        ts = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    age = int((now - ts).total_seconds())
    return age if age >= 0 else None


RUNS_SCHEMA = "N8nCoordinationRunsProjection@v2"
LEGACY_RUNS_SCHEMA = "N8nCoordinationRunsProjection@v1"
RUN_STATES = ("REQUESTED", "RUNNING", "RUN_DONE", "RUN_FAILED", "RUN_TIMEOUT", "RUN_SKIPPED_LOCK", "RUN_REFUSED")
RUN_STATE_TEXT = {
    "REQUESTED": "run requested, waiting for the executor",
    "RUNNING": "running",
    "RUN_DONE": "process finished; useful-output verdict is separate",
    "RUN_FAILED": "run failed",
    "RUN_TIMEOUT": "run timed out",
    "RUN_SKIPPED_LOCK": "skipped: the lane's lock was held (no double-run)",
    "RUN_REFUSED": "refused by the gateway",
}
RUNS_RECEIPT_DIR = "data/runtime/n8n_runs"


_LAST_SUCCESS: dict[tuple[str,str], str] = {}


def _lane_metadata(lane):
    try:
        doc=json.loads((Path(__file__).resolve().parents[2]/"config/lane_registry.json").read_text())
        return next((r for r in doc.get("lanes",[]) if r.get("lane_id")==lane),{})
    except (OSError,ValueError,TypeError):
        return {}


def _receipt(raw):
    try:
        doc=json.loads(raw or "{}")
        return doc if isinstance(doc,dict) else None
    except (ValueError,TypeError):
        return None


def project(path: Optional[Path] = None, *, lane_id: Optional[str] = None, state: Optional[str] = None,
            limit: int = 100, now: Optional[_dt.datetime] = None, source: Optional[str] = None) -> dict[str, Any]:
    if source == "runs":
        return project_runs(path,lane_id=lane_id,state=state,limit=limit,now=now)
    return _project(path,lane_id=lane_id,state=state,limit=limit,now=now,source="events")


def project_runs(path: Optional[Path] = None, *, lane_id: Optional[str] = None, state: Optional[str] = None,
                 limit: int = 100, now: Optional[_dt.datetime] = None, mode: Optional[str] = None) -> dict[str, Any]:
    return _project(path,lane_id=lane_id,state=state,limit=limit,now=now,source="runs",mode=mode)


def _project(path, *, lane_id, state, limit, now, source, mode=None):
    now=now or _dt.datetime.now(_dt.timezone.utc)
    p=Path(path or ledger_path())
    page_limit=max(1,min(int(limit),500))
    out={"schema":RUNS_SCHEMA if source=="runs" else SCHEMA,"as_of":now.isoformat(),"ledger":str(p),
         "items":[],"count":None,"total_count":None,"summary":None,"status":"UNAVAILABLE",
         "availability":"UNAVAILABLE","last_good_at":_LAST_SUCCESS.get((str(p),source)),
         "last_good_age_s":_age_s(_LAST_SUCCESS.get((str(p),source)),now),
         "coverage":{"scope":"all_retained_ledger_rows","since":None,"through":None,
                     "captured_at":now.isoformat(),"aggregation_complete":False,"returned_rows":None,
                     "total_rows":None,"items_truncated":None,"detail_limit":page_limit,
                     "filters":{"lane_id":lane_id,"state":state,"mode":mode},
                     "qualification":"All retained rows at one read transaction; not a 24-hour or lifetime business total"}}
    if source=="runs":out["source"]="runs"
    else:out.update(wave_b_lanes=list(WAVE_B_LANES),wave_b_run_lanes=list(WAVE_B_RUN_LANES),spotlights=lane_spotlights(now=now))
    if not p.is_file():
        out["note"]="Ledger unavailable; waiting work and run totals are unknown"
        return out
    conn=None
    try:
        conn=sqlite3.connect(f"file:{p}?mode=ro",uri=True,timeout=2)
        conn.row_factory=sqlite3.Row
        deadline=time.monotonic()+2.0
        conn.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
        conn.execute("PRAGMA query_only=1");conn.execute("BEGIN")
        table="runs" if source=="runs" else "receipts"
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            out["note"]=f"{table} table unavailable; absence does not establish zero work"
            return out
        stamp="COALESCE(finished_at,started_at,requested_at)" if source=="runs" else "updated_at"
        where,args=" WHERE 1=1",[]
        for field,value in (("lane_id",lane_id),("state",state.upper() if state else None),("mode",mode if source=="runs" else None)):
            if value is not None:where+=f" AND {field} = ?";args.append(value)
        total,first,last=conn.execute(f"SELECT COUNT(*),MIN({stamp}),MAX({stamp}) FROM {table}"+where,args).fetchone()
        states={str(r[0]):r[1] for r in conn.execute(f"SELECT state,COUNT(*) FROM {table}"+where+" GROUP BY state",args)}
        lanes={str(r[0]):r[1] for r in conn.execute(f"SELECT lane_id,COUNT(*) FROM {table}"+where+" GROUP BY lane_id",args)}
        namespaces={}
        if source=="runs":
            ns="CASE WHEN run_id LIKE 'n8n-wf-%' THEN 'n8n-wf' WHEN instr(run_id,':')>0 THEN substr(run_id,1,instr(run_id,':')-1) ELSE 'undated/other' END"
            namespaces={str(r[0]):r[1] for r in conn.execute(f"SELECT {ns},COUNT(*) FROM runs"+where+f" GROUP BY {ns}",args)}
        rows=[dict(r) for r in conn.execute(f"SELECT * FROM {table}"+where+f" ORDER BY {stamp} DESC LIMIT ?",[*args,page_limit])]
        arts={}
        if source=="events" and rows and conn.execute("SELECT 1 FROM sqlite_master WHERE name='artifact_refs'").fetchone():
            keys=[r["store_key"] for r in rows]
            arts={r["store_key"]:dict(r) for r in conn.execute("SELECT * FROM artifact_refs WHERE store_key IN ("+','.join('?' for _ in keys)+")",keys)}
        owners={}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='effect_owners'").fetchone():
            owners={r["process"]:dict(r) for r in conn.execute("SELECT process,owner,epoch FROM effect_owners")}
        conn.execute("ROLLBACK")
    except (sqlite3.Error,OSError) as exc:
        out["note"]="Ledger read unavailable: "+type(exc).__name__
        return out
    finally:
        if conn is not None:conn.close()
    invalid=0
    for r in rows:
        rec=_receipt(r.get("receipt_json"))
        if rec is None:
            invalid+=1;continue
        lane=r.get("lane_id") or rec.get("lane_id")
        owner=owners.get(str(lane)) or {}
        if source=="runs":
            rid=r.get("run_id");st=str(r.get("state") or "UNKNOWN")
            from scripts.lib import recovery_validator as RV
            try:effective=RV.effective_mode({**r,"receipt":rec})
            except (TypeError,ValueError):effective=None
            out["items"].append({
                "run_id":rid,"lane_id":lane,"mode":effective,"requested_mode":r.get("mode"),"state":st,
                "state_text":RUN_STATE_TEXT.get(st,st.lower()),"exit_code":r.get("exit_code"),"duration_s":r.get("duration_s"),
                "requested_by":r.get("requested_by") or r.get("caller_id"),"caller_id":r.get("caller_id"),
                "requested_at":r.get("requested_at"),"started_at":r.get("started_at"),"finished_at":r.get("finished_at"),
                "age_s":_age_s(r.get("finished_at") or r.get("started_at") or r.get("requested_at"),now),
                "receipt_ref":f"{RUNS_RECEIPT_DIR}/{rid}.json" if rid else None,"evidence":f"ledger:{p.name}#runs/{rid}",
                "attempt":r.get("attempt") or rec.get("attempt"),"workflow_id":rec.get("workflow_id"),"execution_id":rec.get("execution_id"),
                "served_sha":rec.get("code_sha"),"output_verdict":rec.get("output_verdict"),"owner":owner.get("owner"),"owner_epoch":owner.get("epoch")})
        else:
            key=r.get("store_key") or f"{rec.get('source_project')}:{rec.get('idempotency_key')}"
            st=str(r.get("state") or rec.get("state") or "UNKNOWN")
            art=arts.get(key) or rec.get("artifact_ref")
            out["items"].append({
                "event_id":rec.get("event_id"),"lane_id":lane,"project":rec.get("source_project"),"idempotency_key":rec.get("idempotency_key"),
                "state":st,"state_text":STATE_TEXT.get(st,st.lower()),"reason":rec.get("reason"),"owner":owner.get("owner"),"owner_epoch":owner.get("epoch"),
                "updated_at":r["updated_at"],"age_s":_age_s(r["updated_at"],now),"recorded_at":rec.get("recorded_at"),"origin_sha":rec.get("origin_sha"),
                "artifact":art,"artifact_ref":art,"consumer":rec.get("consumer"),"consumer_receipt_id":rec.get("consumer_receipt_id"),
                "durable":rec.get("durable"),"evidence":f"ledger:{p.name}#{key}","wave_b":lane in WAVE_B_LANES})
    out.update(count=len(out["items"]),total_count=total,summary={"by_state":states,"by_lane":lanes},
               status="PARTIAL" if invalid else "OK",availability="AVAILABLE")
    out["coverage"].update(since=first,through=last,total_rows=total,returned_rows=len(out["items"]),items_truncated=total>len(rows),
                           aggregation_complete=True,invalid_detail_rows=invalid,run_key_namespaces=namespaces,
                           aggregation_basis="ledger columns; useful output, delivery and acknowledgement are separate contracts")
    if not invalid:
        _LAST_SUCCESS[(str(p),source)]=now.isoformat()
        out.update(last_good_at=now.isoformat(),last_good_age_s=0)
    return out
