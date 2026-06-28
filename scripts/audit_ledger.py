#!/usr/bin/env python3
"""Append-only audit ledger for live-adjacent events — hash-chained JSONL + optional DB."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "data" / "runtime" / "audit_ledger"
LEDGER_PATH = LEDGER_DIR / "events.jsonl"


def _conn():
    try:
        from db_adapter import _get_conn
        return _get_conn()
    except Exception:
        return None


def _ensure_db(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS audit_ledger_events (
                     id SERIAL PRIMARY KEY,
                     event_id TEXT UNIQUE NOT NULL,
                     event_hash TEXT NOT NULL,
                     prev_event_hash TEXT,
                     correlation_id TEXT,
                     actor TEXT,
                     component TEXT,
                     event_type TEXT NOT NULL,
                     decision TEXT,
                     reason TEXT,
                     snapshot_json JSONB,
                     created_at TIMESTAMPTZ DEFAULT NOW())""")


def _last_hash() -> str:
    if not LEDGER_PATH.exists():
        return "GENESIS"
    try:
        with LEDGER_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return "GENESIS"
            f.seek(max(0, size - 8192))
            chunk = f.read().decode("utf-8", errors="ignore")
        for line in reversed(chunk.splitlines()):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            return row.get("event_hash") or "GENESIS"
    except Exception:
        return "GENESIS"


def _hash_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_event(
    event_type: str,
    *,
    decision: str = "",
    reason: str = "",
    correlation_id: str | None = None,
    actor: str = "system",
    component: str = "trade_ai",
    snapshot: dict | None = None,
    snapshot_refs: list[str] | None = None,
) -> dict:
    """Append immutable audit record. Never raises — returns ok=False on failure."""
    event_id = str(uuid.uuid4())
    correlation_id = correlation_id or event_id
    prev_hash = _last_hash()
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    body = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "actor": actor,
        "component": component,
        "event_type": event_type,
        "decision": decision,
        "reason": reason,
        "snapshot": snapshot or {},
        "snapshot_refs": snapshot_refs or [],
        "prev_event_hash": prev_hash,
        "created_at": created_at,
    }
    event_hash = _hash_payload(body)
    body["event_hash"] = event_hash
    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, default=str) + "\n")
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    conn = _conn()
    if conn:
        try:
            cur = conn.cursor()
            _ensure_db(cur)
            cur.execute(
                """INSERT INTO audit_ledger_events
                   (event_id, event_hash, prev_event_hash, correlation_id, actor, component,
                    event_type, decision, reason, snapshot_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (event_id, event_hash, prev_hash, correlation_id, actor, component,
                 event_type, decision, reason, json.dumps(snapshot or {}, default=str)),
            )
            conn.commit()
        except Exception:
            pass
    return {"ok": True, "event_id": event_id, "event_hash": event_hash, "correlation_id": correlation_id}


def tail(limit: int = 50) -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    rows = []
    try:
        with LEDGER_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception:
        return []
    return rows[-max(1, limit):]


def verify_chain(limit: int = 500) -> dict:
    """Verify hash chain integrity over recent events WITHOUT mutating any event row.

    When ``limit`` is smaller than the ledger, only a window is verified; we seed the
    expected previous hash from the first row's own ``prev_event_hash`` so a partial
    window verifies its internal linkage rather than spuriously reporting a chain break.
    """
    rows = tail(limit)
    if not rows:
        return {"ok": True, "verified": 0, "note": "empty ledger"}
    # Seed from the first row's recorded predecessor so a partial tail still verifies.
    prev = rows[0].get("prev_event_hash") or "GENESIS"
    verified = 0
    for row in rows:
        eh = row.get("event_hash")
        if row.get("prev_event_hash") != prev:
            return {"ok": False, "verified": verified, "error": "chain_break", "event_id": row.get("event_id")}
        # Recompute over the canonical body WITHOUT mutating the row (copy, drop the hash).
        body = {k: v for k, v in row.items() if k != "event_hash"}
        calc = _hash_payload(body)
        if eh != calc:
            return {"ok": False, "verified": verified, "error": "hash_mismatch", "event_id": row.get("event_id")}
        prev = eh
        verified += 1
    return {"ok": True, "verified": verified}


# Live-adjacent event types we expect to see covered in a healthy live-adjacent ledger.
EXPECTED_LIVE_ADJACENT_EVENTS = (
    "readiness_evaluated", "readiness_blocked", "risk_block_emitted", "queue_approval",
    "evidence_revalidation", "submit_requested", "broker_ack_received", "broker_reject",
    "partial_fill", "fill", "cancel", "reconcile_result", "kill_switch_change",
    "release_readiness_run",
)

# Events that are strictly required whenever any live-adjacent activity has occurred.
CRITICAL_LIVE_ADJACENT_EVENTS = (
    "readiness_evaluated", "queue_approval", "submit_requested", "reconcile_result",
)


def coverage_report(limit: int = 5000, *, release_mode: str = "review") -> dict:
    """Report which expected live-adjacent event types are present in the ledger.

    ``release_mode='live'`` escalates missing CRITICAL event types (when any live-adjacent
    activity exists) to FAIL; otherwise they are WARN. A ledger write/verify failure is a
    release blocker for live-adjacent mode.
    """
    rows = tail(limit)
    present = {}
    for r in rows:
        et = r.get("event_type")
        if et:
            present[et] = present.get(et, 0) + 1
    seen = set(present)
    any_live_activity = bool(seen & set(EXPECTED_LIVE_ADJACENT_EVENTS))
    missing_expected = [e for e in EXPECTED_LIVE_ADJACENT_EVENTS if e not in seen]
    missing_critical = [e for e in CRITICAL_LIVE_ADJACENT_EVENTS if e not in seen]

    chain = verify_chain(min(limit, 5000))
    if not chain.get("ok"):
        status = "FAIL"
    elif any_live_activity and missing_critical:
        status = "FAIL" if release_mode == "live" else "WARN"
    elif missing_expected:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "ok": chain.get("ok", False),
        "status": status,
        "chain": chain,
        "event_counts": present,
        "expected_event_types": list(EXPECTED_LIVE_ADJACENT_EVENTS),
        "present_event_types": sorted(seen),
        "missing_expected": missing_expected,
        "missing_critical": missing_critical,
        "any_live_activity": any_live_activity,
        "release_mode": release_mode,
        "total_events": len(rows),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--release-mode", default="review")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.coverage:
        out = coverage_report(release_mode=args.release_mode)
    else:
        out = verify_chain()
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())