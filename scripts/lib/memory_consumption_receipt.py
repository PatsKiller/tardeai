"""MemoryConsumptionReceipt@v1 — a durable, per-consumer record that shared
memory was actually READ by an agent other than the one that wrote it.

Why (2026-09-25): the daily MemoryShadowMeasure reports `THREE_WAY_SHARED`
when the CIO, Hermes and Advisory all hold rows on one subject. That proves
co-location in a store, not consumption. Hermes' research prompt and the
Advisory desk both call `retrieve_for_context` and then discard the fact that
they did, so nothing could show a second agent read the CIO's memory. Each
consumer now appends one receipt per retrieval that returned memory ids.

Contract: additive JSONL at data/cio/memory_consumption_receipts.jsonl.
Read by `agent_memory_shadow_measure` (consumer_receipts section). Cognition
context only — MBI_BEHAVIOR = 0; a receipt records reading, never acting.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "MemoryConsumptionReceipt@v1"
RECEIPTS_REL = Path("data") / "cio" / "memory_consumption_receipts.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"
KNOWN_CONSUMERS = frozenset({
    "hermes_research_prompt", "advisory_desk_operator", "persistent_agent_wake",
    "cio_run_worker", "test",
})


def receipts_path(root: Path | None = None) -> Path:
    override = os.environ.get("TRADEAI_MEMORY_RECEIPTS_PATH")
    if override and root is None:
        return Path(override)
    if root is not None:
        return Path(root) / RECEIPTS_REL
    shared = Path.home() / "trade-ai-releases" / "persistent-state" / RECEIPTS_REL
    if shared.parent.is_dir():
        return shared
    return Path(__file__).resolve().parents[2] / RECEIPTS_REL


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _memory_ids(rows: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for r in rows or []:
        if isinstance(r, dict):
            mid = r.get("memory_id") or r.get("memory_version_id") or r.get("id")
        else:
            mid = r
        if mid and str(mid) not in out:
            out.append(str(mid))
    return out


def build_receipt(
    *,
    consumer: str,
    purpose: str,
    symbols: Iterable[str],
    supporting: Iterable[Any] = (),
    counter: Iterable[Any] = (),
    retrieval_status: str | None = None,
    query: str | None = None,
    correlation_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any] | None:
    """One receipt, or None when the retrieval returned no memory ids.

    No ids → no receipt: a receipt for an empty read would let a consumer
    that never sees memory count as a consumer.
    """
    sup = _memory_ids(supporting)
    con = _memory_ids(counter)
    if not sup and not con:
        return None
    syms = sorted({str(s).upper() for s in symbols if s})
    ts = now or _now()
    key = f"{consumer}|{purpose}|{','.join(syms)}|{','.join(sup + con)}|{ts}"
    rid = "mcr_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return {
        "schema": SCHEMA,
        "receipt_id": rid,
        "consumer": consumer,
        "purpose": purpose,
        "symbols": syms,
        "memory_ids_supporting": sup,
        "memory_ids_counter": con,
        "retrieval_status": retrieval_status,
        "query": (query or "")[:200] or None,
        "correlation_id": correlation_id,
        "memory_behavior_influence": os.environ.get("MEMORY_BEHAVIOR_INFLUENCE", "0"),
        "authority": AUTHORITY,
        "consumed_at": ts,
    }


def append_receipt(receipt: dict[str, Any] | None, *, root: Path | None = None,
                   path: Path | None = None) -> Path | None:
    """Append fail-soft: a consumer's retrieval must never fail on receipting."""
    if not receipt:
        return None
    p = Path(path) if path else receipts_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt, sort_keys=True, default=str) + "\n")
    except OSError:
        return None
    return p


def record_consumption(*, consumer: str, purpose: str, symbols: Iterable[str],
                       result: dict[str, Any] | None, query: str | None = None,
                       correlation_id: str | None = None,
                       root: Path | None = None, path: Path | None = None) -> dict[str, Any] | None:
    """Build+append from a `retrieve_for_context` result. Returns the receipt."""
    result = result or {}
    rec = build_receipt(
        consumer=consumer, purpose=purpose, symbols=symbols,
        supporting=result.get("supporting") or [],
        counter=result.get("counter_memory") or result.get("counter") or [],
        retrieval_status=result.get("retrieval_status"),
        query=query, correlation_id=correlation_id,
    )
    append_receipt(rec, root=root, path=path)
    return rec


def read_receipts(*, root: Path | None = None, path: Path | None = None,
                  since: str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else receipts_path(root)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("schema") != SCHEMA:
            continue
        if since and str(row.get("consumed_at") or "") < since:
            continue
        out.append(row)
    return out


def consumers_by_memory_id(rows: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    """memory_id -> set of consumers that receipted reading it."""
    out: dict[str, set[str]] = {}
    for r in rows:
        for mid in list(r.get("memory_ids_supporting") or []) + list(r.get("memory_ids_counter") or []):
            out.setdefault(str(mid), set()).add(str(r.get("consumer")))
    return out


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    by_consumer: dict[str, int] = {}
    for r in rows:
        by_consumer[str(r.get("consumer"))] = by_consumer.get(str(r.get("consumer")), 0) + 1
    multi = {mid: sorted(c) for mid, c in consumers_by_memory_id(rows).items() if len(c) >= 2}
    return {
        "schema": SCHEMA,
        "receipts": len(rows),
        "by_consumer": dict(sorted(by_consumer.items())),
        "memory_ids_read_by_two_or_more_consumers": len(multi),
        "examples": dict(list(sorted(multi.items()))[:5]),
    }


__all__ = [
    "SCHEMA", "receipts_path", "build_receipt", "append_receipt", "record_consumption",
    "read_receipts", "consumers_by_memory_id", "summarize",
]
