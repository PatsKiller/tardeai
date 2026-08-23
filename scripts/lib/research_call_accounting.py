"""Append-only accounting for autonomous research call decisions.

The ledger records intent before a provider call exists, so dedupe, skip-gate,
budget, and provider outcomes reconcile without inferring scheduler behavior from
cost rows. It is observability only and has no financial authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

SCHEMA = "ResearchCallAccountingEvent@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
EVENTS = {
    "SCHEDULED",
    "DRY_RUN",
    "DEDUPED",
    "SKIP_GATED",
    "ATTEMPTED",
    "RETRY",
    "FALLBACK",
    "COMPLETED",
    "ERROR",
    "COST_CAP_EXCEEDED",
    "RESERVATION_ONLY",
}
TERMINAL = {
    "DRY_RUN", "DEDUPED", "SKIP_GATED", "COMPLETED", "ERROR",
    "COST_CAP_EXCEEDED", "RESERVATION_ONLY",
}
FAMILIES = {"A", "B", "MANUAL", "REGISTERED"}


def ledger_path() -> Path:
    override = os.getenv("RESEARCH_CALL_ACCOUNTING_PATH", "").strip()
    if override:
        return Path(override)
    if os.getenv("PYTEST_CURRENT_TEST"):
        return Path("/tmp") / f"tradeai-research-call-accounting-pytest-{os.getpid()}.jsonl"
    return Path(__file__).resolve().parents[2] / "data" / "cio" / "research_call_accounting.jsonl"


def new_run_id(producer: str, *, now: datetime | None = None) -> str:
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%fZ")
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in producer)[:60]
    return f"{safe}:{ts}:{os.getpid()}"


def call_id_for(run_id: str, symbol: str | None, lane: str, *, ordinal: int = 0) -> str:
    raw = f"{run_id}|{(symbol or '_').upper()}|{lane.lower()}|{int(ordinal)}"
    return "rc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def append_event(
    event: str,
    *,
    producer: str,
    family: str,
    run_id: str,
    call_id: str,
    symbol: str | None,
    lane: str,
    trigger: str,
    reason: str | None = None,
    attempt_no: int = 0,
    apply: bool = True,
    fallback_from: str | None = None,
    metadata: dict | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    event = str(event or "").upper()
    family = str(family or "REGISTERED").upper()
    if event not in EVENTS:
        raise ValueError(f"invalid accounting event: {event}")
    if family not in FAMILIES:
        raise ValueError(f"invalid research family: {family}")
    required = {"producer": producer, "run_id": run_id, "call_id": call_id, "lane": lane}
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError("missing accounting identity: " + ",".join(missing))
    row = {
        "schema": SCHEMA,
        "event_id": "rce_" + uuid.uuid4().hex,
        "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
        "producer": str(producer),
        "family": family,
        "run_id": str(run_id),
        "call_id": str(call_id),
        "symbol": str(symbol).upper() if symbol else None,
        "lane": str(lane).lower(),
        "trigger": str(trigger or "unknown"),
        "event": event,
        "reason": str(reason)[:500] if reason else None,
        "attempt_no": max(0, int(attempt_no or 0)),
        "apply": bool(apply),
        "fallback_from": fallback_from,
        "authority": AUTHORITY,
        "financial_writes": 0,
        "metadata": dict(metadata or {}),
    }
    target = path or ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(row, sort_keys=True, default=str) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return row


def read_events(path: Path | None = None, *, hours: int = 24, now: datetime | None = None) -> list[dict]:
    target = path or ledger_path()
    if not target.exists():
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=max(1, int(hours)))
    rows: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            ts = datetime.fromisoformat(str(row.get("timestamp") or "").replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                rows.append(row)
        except Exception:
            continue
    return rows


def summarize(events: Iterable[dict]) -> dict:
    rows = list(events)
    calls: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        cid = str(row.get("call_id") or "")
        if cid:
            calls[cid].append(row)
    by_event = Counter(str(row.get("event") or "") for row in rows)
    by_family = Counter()
    by_producer = Counter()
    unresolved: list[str] = []
    attempted = completed = errors = capped = deduped = skip_gated = dry_run = 0
    retries = fallbacks = reservation_only = 0
    for cid, history in calls.items():
        events_for_call = {str(row.get("event") or "") for row in history}
        identity = history[0]
        by_family[str(identity.get("family") or "REGISTERED")] += 1
        by_producer[str(identity.get("producer") or "missing")] += 1
        attempted += int("ATTEMPTED" in events_for_call)
        completed += int("COMPLETED" in events_for_call)
        errors += int("ERROR" in events_for_call)
        capped += int("COST_CAP_EXCEEDED" in events_for_call)
        deduped += int("DEDUPED" in events_for_call)
        skip_gated += int("SKIP_GATED" in events_for_call)
        dry_run += int("DRY_RUN" in events_for_call)
        reservation_only += int("RESERVATION_ONLY" in events_for_call)
        retries += sum(int(row.get("metadata", {}).get("retry_count") or 1)
                       for row in history if row.get("event") == "RETRY")
        fallbacks += sum(1 for row in history if row.get("event") == "FALLBACK")
        if not (events_for_call & TERMINAL):
            unresolved.append(cid)
    scheduled_ids = {
        str(row.get("call_id")) for row in rows if row.get("event") == "SCHEDULED"
    }
    return {
        "schema": "ResearchCallAccountingSummary@v1",
        "authority": AUTHORITY,
        "events": len(rows),
        "calls": len(calls),
        "calls_scheduled": len(scheduled_ids),
        "calls_actually_attempted": attempted,
        "family_a": by_family.get("A", 0),
        "family_b": by_family.get("B", 0),
        "manual": by_family.get("MANUAL", 0),
        "registered_other": by_family.get("REGISTERED", 0),
        "retry": retries,
        "fallback": fallbacks,
        "error": errors,
        "reservation_only": reservation_only,
        "cost_cap_exceeded": capped,
        "deduped": deduped,
        "skip_gated": skip_gated,
        "dry_run": dry_run,
        "completed": completed,
        "by_event": dict(sorted(by_event.items())),
        "by_producer": dict(sorted(by_producer.items())),
        "unresolved_call_ids": sorted(unresolved),
        "reconciled": not unresolved,
        "financial_writes": 0,
    }


def add_reservation_only_events(
    events: Iterable[dict], reservations: Iterable[dict], consumption_rows: Iterable[dict],
    *, now: datetime | None = None,
) -> list[dict]:
    """Return events plus synthetic terminal rows for orphaned paid reservations.

    Existing rows may predate explicit research identities. Those reservations
    receive stable legacy identities derived from the authoritative reservation
    primary key, never an unclassified bucket.
    """
    out = list(events)
    terminal_by_call = {
        str(row.get("call_id")) for row in out if row.get("event") in TERMINAL
    }
    consumed_reservations: set[str] = set()
    for row in consumption_rows:
        meta = row.get("metadata_json") or row.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        reservation_id = meta.get("reservation_id")
        if reservation_id is not None:
            consumed_reservations.add(str(reservation_id))
    current = now or datetime.now(timezone.utc)
    for row in reservations:
        reservation_id = str(row.get("id") or "").strip()
        if not reservation_id or reservation_id in consumed_reservations:
            continue
        meta = row.get("metadata_json") or row.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        created = row.get("created_at") or current.isoformat()
        try:
            created_dt = created if isinstance(created, datetime) else datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
        except Exception:
            created_dt = current
        # A currently reserved row may still be in flight; the cost layer's stale
        # recovery threshold is 30 minutes, so do not classify it before then.
        if str(row.get("status") or "") == "reserved" and current - created_dt < timedelta(minutes=30):
            continue
        producer = str(meta.get("research_producer") or row.get("process_id") or "legacy_paid_process")
        family = str(meta.get("research_family") or (
            "A" if row.get("process_id") == "hermes_external_research" else "REGISTERED"
        )).upper()
        run_id = str(meta.get("research_run_id") or f"legacy_reservation:{created_dt.date()}:{producer}")
        call_id = str(meta.get("research_call_id") or f"reservation:{reservation_id}")
        if call_id in terminal_by_call:
            continue
        out.append({
            "schema": SCHEMA,
            "event_id": f"reservation_{reservation_id}",
            "timestamp": created_dt.isoformat(),
            "producer": producer,
            "family": family if family in FAMILIES else "REGISTERED",
            "run_id": run_id,
            "call_id": call_id,
            "symbol": None,
            "lane": str(meta.get("lane") or "deepseek").lower(),
            "trigger": "reservation_reconciliation",
            "event": "RESERVATION_ONLY",
            "reason": f"reservation_status:{row.get('status') or 'unknown'}",
            "attempt_no": 0,
            "apply": True,
            "fallback_from": None,
            "authority": AUTHORITY,
            "financial_writes": 0,
            "metadata": {"reservation_id": reservation_id, "provenance": "DB_RECONCILIATION"},
        })
        terminal_by_call.add(call_id)
    return out


def accounting_identity(
    *, producer: str, family: str, symbol: str | None, lane: str,
    run_id: str | None = None, call_id: str | None = None, ordinal: int = 0,
) -> tuple[str, str]:
    rid = run_id or new_run_id(producer)
    return rid, call_id or call_id_for(rid, symbol, lane, ordinal=ordinal)
