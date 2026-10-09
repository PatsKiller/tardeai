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
from pathlib import Path
from typing import Any, Optional

NO_CONSUMER_REASON = "read by GET /api/v2/coordination/events (?source=runs for the runs table) in scripts/api_v2.py; no scheduled lane"
SCHEMA = "N8nCoordinationProjection@v1"
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


def _age_s(iso: Optional[str], now: _dt.datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        ts = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return int((now - ts).total_seconds())


RUNS_SCHEMA = "N8nCoordinationRunsProjection@v1"
RUN_STATES = ("REQUESTED", "RUNNING", "RUN_DONE", "RUN_FAILED", "RUN_TIMEOUT", "RUN_SKIPPED_LOCK", "RUN_REFUSED")
RUN_STATE_TEXT = {
    "REQUESTED": "run requested, waiting for the executor",
    "RUNNING": "running",
    "RUN_DONE": "run finished (exit 0)",
    "RUN_FAILED": "run failed",
    "RUN_TIMEOUT": "run timed out",
    "RUN_SKIPPED_LOCK": "skipped: the lane's lock was held (no double-run)",
    "RUN_REFUSED": "refused by the gateway",
}
RUNS_RECEIPT_DIR = "data/runtime/n8n_runs"


def project(path: Optional[Path] = None, *, lane_id: Optional[str] = None, state: Optional[str] = None,
            limit: int = 100, now: Optional[_dt.datetime] = None, source: Optional[str] = None) -> dict[str, Any]:
    if source == "runs":
        return project_runs(path, lane_id=lane_id, state=state, limit=limit, now=now)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = path or ledger_path()
    out: dict[str, Any] = {"schema": SCHEMA, "as_of": now.isoformat(), "ledger": str(p), "items": [], "count": 0}
    if not p.is_file():
        out["status"] = "NO_LEDGER"
        out["note"] = "the coordination gateway has not written a ledger here; nothing is waiting"
        return out
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        out["status"] = f"UNREADABLE:{type(exc).__name__}"
        return out
    try:
        sql, args = "SELECT receipt_json, updated_at FROM receipts WHERE 1=1", []
        if lane_id:
            sql += " AND lane_id = ?"; args.append(lane_id)
        if state:
            sql += " AND state = ?"; args.append(state.upper())
        sql += " ORDER BY updated_at DESC LIMIT ?"; args.append(max(1, min(int(limit), 500)))
        rows = conn.execute(sql, args).fetchall()
        arts = {r["store_key"]: dict(r) for r in conn.execute("SELECT store_key, store, ref, sha256, as_of FROM artifact_refs")}
    except sqlite3.Error as exc:
        out["status"] = f"UNREADABLE:{type(exc).__name__}"
        return out
    finally:
        conn.close()
    for r in rows:
        rec = json.loads(r["receipt_json"])
        key = f"{rec.get('source_project')}:{rec.get('idempotency_key')}"
        st = str(rec.get("state") or "")
        out["items"].append({
            "event_id": rec.get("event_id"), "lane_id": rec.get("lane_id"), "project": rec.get("source_project"),
            "state": st, "state_text": STATE_TEXT.get(st, st.lower()),
            "reason": rec.get("reason"), "owner": "cron (incumbent); n8n coordinates only",
            "updated_at": r["updated_at"], "age_s": _age_s(r["updated_at"], now),
            "recorded_at": rec.get("recorded_at"), "origin_sha": rec.get("origin_sha"),
            "artifact": arts.get(key) or rec.get("artifact_ref"),
            "consumer": rec.get("consumer"), "consumer_receipt_id": rec.get("consumer_receipt_id"),
            "durable": rec.get("durable"), "evidence": f"ledger:{p.name}#{key}",
        })
    out["count"] = len(out["items"])
    out["status"] = "OK"
    return out


def project_runs(path: Optional[Path] = None, *, lane_id: Optional[str] = None, state: Optional[str] = None,
                 limit: int = 100, now: Optional[_dt.datetime] = None, mode: Optional[str] = None) -> dict[str, Any]:
    """Scheduler-of-record program (2026-10-08, stream G): the `runs` table the gateway's `run`
    operation writes and the executor settles. Read-only, short timeout; an absent ledger or an
    absent table is an honest empty page (the table is built by stream B and may land later)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = path or ledger_path()
    out: dict[str, Any] = {"schema": RUNS_SCHEMA, "source": "runs", "as_of": now.isoformat(), "ledger": str(p),
                           "items": [], "count": 0}
    if not p.is_file():
        out["status"] = "NO_LEDGER"
        out["note"] = "the coordination gateway has not written a ledger here; no runs were requested"
        return out
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        out["status"] = f"UNREADABLE:{type(exc).__name__}"
        return out
    try:
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
        if not has:
            out["status"] = "OK"
            out["note"] = "no runs table yet: the gateway run operation has not been served here"
            return out
        sql, args = "SELECT * FROM runs WHERE 1=1", []
        if lane_id:
            sql += " AND lane_id = ?"; args.append(lane_id)
        if state:
            sql += " AND state = ?"; args.append(state.upper())
        if mode:                                            # 2026-10-09 (B5.3): relay /runs/<lane>/last?mode=
            sql += " AND mode = ?"; args.append(mode)
        sql += " ORDER BY COALESCE(finished_at, started_at, requested_at) DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.Error as exc:
        out["status"] = f"UNREADABLE:{type(exc).__name__}"
        return out
    finally:
        conn.close()
    for r in rows:
        st = str(r.get("state") or "")
        run_id = r.get("run_id")
        out["items"].append({
            "run_id": run_id, "lane_id": r.get("lane_id"), "mode": r.get("mode"), "state": st,
            "state_text": RUN_STATE_TEXT.get(st, st.lower()), "exit_code": r.get("exit_code"),
            "duration_s": r.get("duration_s"), "requested_by": r.get("requested_by") or r.get("caller_id"),
            "caller_id": r.get("caller_id"), "requested_at": r.get("requested_at"), "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
            "age_s": _age_s(r.get("finished_at") or r.get("started_at") or r.get("requested_at"), now),
            "receipt_ref": f"{RUNS_RECEIPT_DIR}/{run_id}.json" if run_id else None,
            "evidence": f"ledger:{p.name}#runs/{run_id}",
        })
    out["count"] = len(out["items"])
    out["status"] = "OK"
    return out
