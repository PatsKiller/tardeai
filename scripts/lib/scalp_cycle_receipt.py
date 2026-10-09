"""ScalpCycleReceipt@v1 — one receipt per 5-minute scalp cycle (lane trade-ai-scalp-live).

Workstream B4 of the n8n maturity program (2026-10-09). The lane's existing receipt
(data/runtime/trade_ai_scalp_live_last.json, TradeAIScalpLiveReceipt@v1) keeps only the LAST run and is
written only when a cycle completes. A cycle killed by the 295 s timeout left no trace at all: Python's
stdout is block-buffered into the cron log, so even the partial log lines were lost. That is why audit D
(finding 2.9) could count 25 cron invocations but only 3 heartbeats, and could not say why.

This ledger fixes that:
- a ``started`` record is appended before the cycle does any work;
- the final record (``ok`` / ``error`` / ``killed``) is appended when it ends, including on SIGTERM;
- a ``started`` record with no final record is a cycle lost to SIGKILL (or a host crash).

One JSONL file per ET trading day under ``<state root>/data/runtime/scalp_cycle_receipts/``. Records are
pure data: no Telegram, no network. The monitor (scripts/lib/scalp_cycle_monitor.py) folds them per slot.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "ScalpCycleReceipt@v1"
LANE_ID = "trade-ai-scalp-live"
LEDGER_REL = "data/runtime/scalp_cycle_receipts"
FINAL_STATUSES = ("ok", "error", "killed")
STATUSES = ("started",) + FINAL_STATUSES


def state_root() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(base)


def ledger_path(day: str, root: Optional[Path] = None) -> Path:
    return (root or state_root()) / LEDGER_REL / f"{day}.jsonl"


def slot_of(now: datetime, cadence_min: int = 5) -> str:
    """The cadence slot a cycle belongs to (HH:MM floored to the cadence): the cycle's idempotency key part."""
    m = (now.hour * 60 + now.minute) // cadence_min * cadence_min
    return f"{m // 60:02d}:{m % 60:02d}"


def cycle_id(day: str, slot: str, lane_id: str = LANE_ID) -> str:
    return f"{lane_id}:{day}:{slot.replace(':', '')}"


def build(status: str, *, day: str, slot: str, started_at: datetime, finished_at: Optional[datetime] = None,
          phase: Optional[str] = None, symbols_scanned: Optional[int] = None, signals: Optional[int] = None,
          triggers: Optional[int] = None, alerts_sent: Optional[int] = None, alerts_deduped: Optional[int] = None,
          deadline_s: Optional[float] = None, enrich_budget_s: Optional[float] = None,
          errors: Iterable[str] = (), scheduler: Optional[str] = None, release: Optional[str] = None,
          lane_id: str = LANE_ID) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"unknown ScalpCycleReceipt status {status!r}")
    seconds = None if finished_at is None else round((finished_at - started_at).total_seconds(), 1)
    used_pct = None if (seconds is None or not deadline_s) else round(100.0 * seconds / float(deadline_s), 1)
    return {
        "schema": SCHEMA, "lane_id": lane_id, "cycle_id": cycle_id(day, slot, lane_id), "date": day, "slot": slot,
        "status": status, "phase": phase,
        "started_at": started_at.isoformat(), "finished_at": None if finished_at is None else finished_at.isoformat(),
        "seconds": seconds,
        "symbols_scanned": symbols_scanned, "signals": signals, "triggers": triggers,
        "alerts_sent": alerts_sent, "alerts_deduped": alerts_deduped,
        "budget": {"deadline_s": deadline_s, "enrich_budget_s": enrich_budget_s, "used_s": seconds,
                   "used_pct": used_pct},
        "errors": [str(e)[:200] for e in errors][:20],
        "scheduler": scheduler or os.getenv("TRADEAI_SCHEDULER") or ("n8n" if os.getenv("TRADEAI_RUN_ID") else "cron"),
        "run_id": os.getenv("TRADEAI_RUN_ID") or None,
        "release": release, "pid": os.getpid(),
    }


def append(doc: dict[str, Any], root: Optional[Path] = None) -> Path:
    """Append one record (single write + flush + fsync, so a following SIGKILL cannot lose it)."""
    p = ledger_path(doc["date"], root)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(doc, sort_keys=True) + "\n"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return p


def read_day(day: str, root: Optional[Path] = None) -> list[dict[str, Any]]:
    """All records of one ET day; torn or foreign lines are skipped."""
    p = ledger_path(day, root)
    out: list[dict[str, Any]] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("schema") == SCHEMA:
            out.append(d)
    return out


def fold(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest record per slot. A final record outranks ``started``; between finals the later one wins."""
    by_slot: dict[str, dict[str, Any]] = {}
    for r in records:
        slot = r.get("slot")
        if not slot:
            continue
        cur = by_slot.get(slot)
        if cur is None:
            by_slot[slot] = r
            continue
        cur_final = cur.get("status") in FINAL_STATUSES
        new_final = r.get("status") in FINAL_STATUSES
        if new_final or not cur_final:
            # an ok in the slot is never replaced by a later failed retry: the slot already produced output
            if cur.get("status") == "ok" and r.get("status") != "ok":
                continue
            by_slot[slot] = r
    return by_slot
