"""Append-only research skip/execute ledger (data/cio/research_skip_ledger.jsonl).

Every candidate logs exactly one of:
  RESEARCH_EXECUTED | SKIP_UNCHANGED | SKIP_FRESH | RESEARCH_TRIGGERED

Never silence a skip. Cost attribution depends on these codes.

READ_ONLY_ADVISORY. Same JSONL pattern as agent_run_traces.jsonl.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchSkipLedger@v1"

RESEARCH_EXECUTED = "RESEARCH_EXECUTED"
SKIP_UNCHANGED = "SKIP_UNCHANGED"
SKIP_FRESH = "SKIP_FRESH"
RESEARCH_TRIGGERED = "RESEARCH_TRIGGERED"
CODES = frozenset({
    RESEARCH_EXECUTED,
    SKIP_UNCHANGED,
    SKIP_FRESH,
    RESEARCH_TRIGGERED,
})
SKIP_CODES = frozenset({SKIP_UNCHANGED, SKIP_FRESH})

# Existing producer reasons → unified codes (do not invent a fifth code).
REASON_TO_CODE: dict[str, str] = {
    "reused_fresh_result": SKIP_FRESH,
    "duplicate_in_flight": SKIP_FRESH,
    "fresh_hours": SKIP_FRESH,
    "FRESH_HOURS": SKIP_FRESH,
    "RESEARCH_BACKFILL_SKIP_FRESH_HOURS": SKIP_FRESH,
    "backfill_skip_fresh_hours": SKIP_FRESH,
    "queue_reused_fresh_result": SKIP_FRESH,
    "queue_duplicate_in_flight": SKIP_FRESH,
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ledger_path(*, root: Path | None = None) -> Path:
    env = (os.getenv("RESEARCH_SKIP_LEDGER_PATH") or "").strip()
    if env:
        return Path(env)
    return (root or _project_root()) / "data" / "cio" / "research_skip_ledger.jsonl"


def skip_gate_enabled() -> bool:
    """True when RESEARCH_SKIP_GATE is on. Default OFF (parity with today)."""
    return os.getenv("RESEARCH_SKIP_GATE", "0").strip().lower() not in {
        "0", "false", "no", "off", "",
    }


def _now_iso(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_dt(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        dt = val
    else:
        try:
            dt = datetime.fromisoformat(str(val).strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def code_for_reason(reason: str) -> str | None:
    if not reason:
        return None
    if reason in CODES:
        return reason
    mapped = REASON_TO_CODE.get(reason)
    if mapped:
        return mapped
    return None


def append_entry(
    *,
    source_id: str,
    code: str,
    symbol: str = "",
    lane: str = "",
    content_hash: str = "",
    reason: str = "",
    metered: bool = True,
    path: Path | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Append one ledger row. Fail-soft: never raise into a research producer."""
    if code not in CODES:
        raise ValueError(f"invalid skip-ledger code: {code!r}")
    row: dict[str, Any] = {
        "ts": _now_iso(now),
        "source_id": source_id,
        "symbol": str(symbol or "").upper().strip(),
        "lane": str(lane or ""),
        "code": code,
        "content_hash": content_hash or "",
        "reason": reason or code,
        "metered": bool(metered),
        "authority": AUTHORITY,
    }
    if extra:
        row["extra"] = extra
    p = Path(path) if path is not None else ledger_path(root=root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
    except Exception:
        return row
    return row


def log_mapped_reason(
    reason: str,
    *,
    symbol: str = "",
    lane: str = "",
    content_hash: str = "",
    source_id: str = "",
    path: Path | None = None,
    root: Path | None = None,
    require_gate: bool = True,
) -> dict[str, Any] | None:
    """Thin hook: map queue / FRESH_HOURS reasons onto SKIP_FRESH.

    No-op unless RESEARCH_SKIP_GATE is on (default) so producers stay silent
    when the flag is off.
    """
    if require_gate and not skip_gate_enabled():
        return None
    code = code_for_reason(reason) or SKIP_FRESH
    if code not in CODES:
        return None
    sid = source_id or (
        f"symbol:{str(symbol).upper().strip()}:lane:{lane or 'deepseek'}"
        if symbol
        else f"reason:{reason}"
    )
    try:
        return append_entry(
            source_id=sid,
            code=code,
            symbol=symbol,
            lane=lane,
            content_hash=content_hash,
            reason=reason,
            metered=True,
            path=path,
            root=root,
        )
    except Exception:
        return None


def summarize_rates(
    path: Path | str | None = None,
    *,
    hours: int = 24,
    now: datetime | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Counts and rates of skip codes in the last `hours` hours (scorecard later)."""
    p = Path(path) if path is not None else ledger_path(root=root)
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    cutoff = now_dt.astimezone(timezone.utc) - timedelta(hours=int(hours))
    by_code = {c: 0 for c in (
        RESEARCH_EXECUTED, SKIP_UNCHANGED, SKIP_FRESH, RESEARCH_TRIGGERED,
    )}
    total = 0
    metered_total = 0
    metered_skipped = 0
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        text = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        ts = _parse_dt(row.get("ts"))
        if ts is None or ts < cutoff:
            continue
        code = row.get("code")
        if code not in by_code:
            continue
        by_code[code] += 1
        total += 1
        if row.get("metered"):
            metered_total += 1
            if code in SKIP_CODES:
                metered_skipped += 1
    rates = {k: (by_code[k] / total if total else 0.0) for k in by_code}
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "hours": int(hours),
        "total": total,
        "by_code": by_code,
        "rates": rates,
        "metered_total": metered_total,
        "metered_skipped": metered_skipped,
        "path": str(p),
    }
