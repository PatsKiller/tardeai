#!/usr/bin/env python3
"""Daily shadow-receipt producer — Financial Senses + durable-memory heartbeats.

READ_ONLY_ADVISORY. This is the scheduled producer that gives the Advisory
Desk's SENSES and MEMORY source clocks a real, observable cadence. Every run
writes exactly two observation receipts at ``influence = 0``:

  1. a Financial Senses tool-trace heartbeat → data/cio/agent_tool_traces.jsonl
  2. a governed durable-memory admission      → data/cio/aif_memory.jsonl
                                                 + aif_memory_admissions.jsonl

It never invokes a live Financial Senses provider, never calls a model, never
reads a live broker feed, and never touches order / stop / risk / 2FA.
``MEMORY_BEHAVIOR_INFLUENCE`` is pinned to 0 and enforced below; the memory
admission lands as CANDIDATE (context only, never policy).

Scheduled by config/systemd/user/tradeai-advisory-shadow-seed.{service,timer}
(OnCalendar=*-*-* 21:45:00, immediately before the 21:50 nightly reflection).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_ID = "advisory_shadow_seed"
AUTHORITY = "READ_ONLY_ADVISORY"

# Make `scripts.lib.*` (repo root) and `lib.*` (scripts/) importable whether run
# directly or under systemd.
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FS_TOOL_NAME = "financial_senses"
FS_PROVIDER = "shadow_seed"
FS_CAPABILITY = "daily_shadow_seed"

MEMORY_TYPE = "PROCEDURAL_HINT"
MEMORY_SUBJECT = "Advisory Desk shadow seed heartbeat"
MEMORY_CONTENT = (
    "Daily shadow-receipt producer ran. Financial Senses and durable-memory "
    "heartbeat receipts were written at influence=0. Observation only; no "
    "canonical financial facts are asserted and no behavior is mutated."
)
MEMORY_SOURCE_KIND = "agent_run"


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def _norm_symbol(sym: Any) -> str:
    s = str(sym or "").strip().upper()
    return s if s and s not in {"", "NONE", "NULL", "CASH"} else ""


def _iter_symbols_from(value: Any) -> set[str]:
    """Extract uppercase symbols from an arbitrary JSON shape (list or dict)."""
    out: set[str] = set()
    if isinstance(value, list):
        for item in value:
            out |= _iter_symbols_from(item)
    elif isinstance(value, dict):
        for key in ("symbol", "ticker"):
            s = _norm_symbol(value.get(key))
            if s:
                out.add(s)
        # Recurse into common container keys.
        for key in ("holdings", "rows", "items", "positions", "entries", "records"):
            if key in value:
                out |= _iter_symbols_from(value[key])
    return out


def collect_symbols(root: Path) -> list[str]:
    """Current desk symbols across holdings, re-entry, and personal watch.

    Fail-soft per file: a missing source only narrows the heartbeat coverage;
    it never fails the producer.
    """
    found: set[str] = set()
    state_dir = root / "data" / "portfolios" / "state"

    holdings = _load_json(state_dir / "holdings.json")
    if isinstance(holdings, dict):
        found |= _iter_symbols_from(holdings.get("holdings") or holdings)

    reentry = _load_json(root / "data" / "runtime" / "reentry_decision_desk_latest.json")
    if isinstance(reentry, dict):
        rows = reentry.get("rows")
        if rows is None and isinstance(reentry.get("data"), dict):
            rows = reentry["data"].get("rows")
        found |= _iter_symbols_from(rows)

    watch = _load_json(state_dir / "watchlist.json")
    if isinstance(watch, dict):
        items = watch.get("items")
        if isinstance(items, dict):
            for sym in items.keys():
                s = _norm_symbol(sym)
                if s:
                    found.add(s)
        elif items is None:
            # Flat {SYMBOL: {...}} legacy shape.
            for sym in watch.keys():
                s = _norm_symbol(sym)
                if s:
                    found.add(s)

    return sorted(found)


def write_fs_receipt(cio_dir: Path, symbols: list[str], now: Optional[datetime] = None) -> bool:
    """Append the Financial Senses heartbeat to agent_tool_traces.jsonl."""
    from scripts.lib.agent_tool_trace import append_tool_call

    ts = _now_iso(now)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    record = {
        "tool_name": FS_TOOL_NAME,
        "capability_class": "read",
        "read_write": "read",
        "trace_id": f"fs-shadow-seed-{stamp}",
        "wake_id": f"shadow-seed-{stamp}",
        "agent": PRODUCER_ID,
        "provider": FS_PROVIDER,
        "fs_provider": FS_PROVIDER,
        "fs_capability": FS_CAPABILITY,
        "request_id": f"fs-shadow-seed-{stamp}",
        "validation_ok": True,
        "shadow_only": True,
        "behavior_influence": False,
        "influence": 0,
        "authority": AUTHORITY,
        "symbols": symbols,
        "started_at": ts,
        "ended_at": ts,
        "source_asof": ts,
        "status": "ok",
        "summary": (
            f"Daily shadow seed heartbeat ({len(symbols)} desk symbols). "
            "No live FS provider invoked; receipt only."
        ),
    }
    return append_tool_call(record, path=cio_dir / "agent_tool_traces.jsonl")


def write_memory_admission(provider: Any, symbols: list[str], now: Optional[datetime] = None) -> dict[str, Any]:
    """Admit the governed memory heartbeat (CANDIDATE, influence=0)."""
    from scripts.lib.agent_memory_admission import admit_candidate

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    raw = {
        "memory_type": MEMORY_TYPE,
        "subject": MEMORY_SUBJECT,
        "content": MEMORY_CONTENT,
        "symbols": symbols,
        "source_refs": [f"{PRODUCER_ID}:daily:{stamp}"],
        "source_kind": MEMORY_SOURCE_KIND,
        "confidence": 0.5,
        "admission_reason": "daily_shadow_seed",
        "producer": PRODUCER_ID,
        "agent": PRODUCER_ID,
    }
    return admit_candidate(raw, provider=provider, admitted_by=PRODUCER_ID)


def resolve_cio_dir(root: Optional[Path] = None, cio_dir: Optional[Path] = None) -> Path:
    if cio_dir:
        return Path(cio_dir)
    env = os.environ.get("TRADEAI_CIO_DIR")
    if env:
        return Path(env)
    return Path(root or _PROJECT_ROOT) / "data" / "cio"


def run(
    *,
    root: Optional[Path] = None,
    cio_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    provider: Any = None,
) -> dict[str, Any]:
    """Produce both shadow receipts and return an audit summary. Never raises."""
    # Enforce the influence=0 contract regardless of the caller's environment.
    os.environ["MEMORY_BEHAVIOR_INFLUENCE"] = "0"
    root = Path(root or _PROJECT_ROOT)
    cio = resolve_cio_dir(root, cio_dir)

    symbols = collect_symbols(root)

    fs_written = write_fs_receipt(cio, symbols, now)

    memory_result: dict[str, Any] = {"admitted": False}
    if provider is None:
        from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider
        provider = DurableJsonlMemoryProvider(path=cio / "aif_memory.jsonl")
    try:
        receipt = write_memory_admission(provider, symbols, now)
        memory_result = {
            "admitted": bool(receipt.get("accepted")),
            "memory_id": receipt.get("memory_id"),
            "display_status": receipt.get("display_status"),
            "reason": receipt.get("reason"),
            "admitted_at": receipt.get("admitted_at"),
        }
    except Exception as exc:  # noqa: BLE001 — producer must not die on a bad admission
        memory_result = {"admitted": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "ok": bool(fs_written),
        "authority": AUTHORITY,
        "influence": 0,
        "at": _now_iso(now),
        "symbols": symbols,
        "symbols_count": len(symbols),
        "fs": {
            "written": fs_written,
            "path": str(cio / "agent_tool_traces.jsonl"),
            "provider": FS_PROVIDER,
            "capability": FS_CAPABILITY,
        },
        "memory": memory_result,
        "memory_store": str(cio / "aif_memory.jsonl"),
    }


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args and args[0] == "--help":
        print(__doc__)
        return 0
    summary = run()
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
