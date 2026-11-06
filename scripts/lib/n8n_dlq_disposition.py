"""Read-only dead-letter disposition and recovery evidence helpers.

Acknowledgement is a receipt alongside the release audit, never a release or
ledger migration. The dispatcher continues to see the original terminal slot.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib import recovery_validator as RV

ACK_SCHEMA = "DeadLetterAcknowledgement@v1"
RECEIPTS_REL = Path("data/runtime/n8n_dlq_releases.jsonl")


def instant(value):
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (TypeError, ValueError):
        return None


def recovery(dead: dict, run: dict | None, *, now: datetime) -> tuple[bool, str]:
    at = instant(dead.get("dead_at"))
    if at is None:
        return False, "dead_letter_time_unknown"
    return RV.validate(run, mode=dead.get("mode"), lane=dead.get("lane_id"),
                       since=at.timestamp(), exclude_run=dead.get("last_run_id"), now=now)


def acknowledgements(path: Path) -> dict[str, dict]:
    """Only complete committed receipts count; a crash after intent closes nothing."""
    out = {}
    try:
        with path.open("rb") as stream:
            # A partial audit read must never silently re-open acknowledged incidents.
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("disposition audit exceeds read bound")
            for line in stream:
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(row, dict):
                    continue
                if (row.get("schema") == ACK_SCHEMA and row.get("phase") == "committed"
                        and row.get("disposition") == "superseded" and row.get("rearm") is False
                        and row.get("by") in {"operator", "coordinator"} and not row.get("dry_run")):
                    for target in row.get("acknowledged") or []:
                        if isinstance(target, dict) and target.get("slot_key"):
                            out[target["slot_key"]] = {**target, "superseded_by": row.get("superseded_by"),
                                                       "acknowledged_at": row.get("at")}
    except FileNotFoundError:
        pass
    return out


def is_acknowledged(dead: dict, receipts: dict[str, dict]) -> bool:
    ack = receipts.get(dead.get("slot_key")) or {}
    return bool(ack.get("superseded_by") and ack.get("dead_at") == dead.get("dead_at")
                and ack.get("last_run_id") == dead.get("last_run_id")
                and ack.get("lane_id") == dead.get("lane_id"))


def successful_runs(path: Path, *, now: datetime) -> dict[tuple[str, str], dict]:
    """Newest receipt-verified successful run per lane/effective mode; SQLite read only."""
    if not path.is_file():
        return {}
    out = {}
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.set_progress_handler(lambda: 1 if datetime.now(timezone.utc).timestamp() > deadline else 0, 10000)
    deadline = datetime.now(timezone.utc).timestamp() + 2
    try:
        for row in conn.execute("SELECT * FROM runs WHERE state='RUN_DONE' AND exit_code=0 ORDER BY finished_at DESC LIMIT 10000"):
            run = dict(row)
            run["receipt"] = RV.receipt_of(run)
            mode = RV.effective_mode(run)
            key = (run.get("lane_id"), mode)
            if key not in out and RV.validate(run, mode=mode, lane=key[0], now=now)[0]:
                out[key] = run
    finally:
        conn.close()
    return out


def cause(receipt: dict | None, fallback: str | None = None) -> str:
    """The bounded stderr cause, then an explicit missing-diagnostic gap."""
    receipt = receipt or {}
    from scripts.lib.error_line_redaction import redact_error_line
    from scripts.lib.scheduler_operations import redact_command
    stderr = receipt.get("stderr_tail")
    if isinstance(stderr, str) and stderr.strip():
        # The command redactor knows NAME=value shell pairs only; error text also carries URL query
        # keys, bot tokens, DSN passwords and secrets paths (2026-10-31), so the strict one runs too.
        return redact_error_line(redact_command(stderr.strip()))[-600:]
    reason = str(receipt.get("reason") or fallback or "").strip()
    if reason and not re.fullmatch(r"exit[_ :\-]?\d+", reason, flags=re.I):
        return redact_error_line(redact_command(reason))[:600]
    return "Failure recorded; stderr diagnostic was not retained"
