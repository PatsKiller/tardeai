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

NO_CONSUMER_REASON = "read by GET /api/v2/coordination/events in scripts/api_v2.py; no scheduled lane"
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


def project(path: Optional[Path] = None, *, lane_id: Optional[str] = None, state: Optional[str] = None,
            limit: int = 100, now: Optional[_dt.datetime] = None) -> dict[str, Any]:
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
