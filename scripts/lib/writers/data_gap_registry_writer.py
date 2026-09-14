"""data_gap_registry_writer.py — THE write module for the `data_gap_registry` store.

One Source of Truth, phase 9 pattern (AGENTS.md §7A rule 1: one writer per store).

`data_gap_registry` is the queue the gap resolver (`scripts/data_gap_resolver.py`,
cron 10-16 and 18 on weekdays) works from. Before this module two files carried
their own SQL against it, with two dedup rules:

  * `run_deep_overnight_llm_queue.py` inserted gaps it found in overnight model
    output, deduping on status = 'open' only. That lane was retired 2026-06-01,
    and the table has had no new row since 2026-05-24.
  * `data_gap_resolver.py` moved rows open -> enriching -> resolved / back to
    open, and abandoned rows open for more than 30 days.

The operator desk was meant to be a third writer through
`advisory_gap_requeue`, which never reached main, so every desk call
registered nothing. The operator approved reconnecting the desk on 2026-09-13.
This module is the one place the table is written. It owns:

  * the INSERT column list and parameter order           (`register_gaps`)
  * the ONE dedup rule: a symbol+gap_type already open OR enriching is not
    inserted again; its id comes back on the receipt as `existing_ids`
  * every status transition the resolver makes           (`mark_enriching`,
    `mark_dispatched`, `mark_resolved`, `reopen`, `abandon`, `abandon_stale`).
    'resolved' means PROVEN: the data is present, or the dispatched agent job
    completed with a result row. Queuing a job leaves the gap 'enriching'.
  * the rails: a tradable-looking symbol (never "BOOK"), a gap_type the
    resolver has an action for, a severity on its vocabulary, a non-empty
    `detected_by`, an integer `source_job_id` when one is given

Rejected rows are never dropped silently: they come back on the receipt with a
reason and are logged at WARNING. Nothing here opens a connection, commits, or
imports psycopg2: the caller owns the transaction. Tests inject a fake cursor.

Nothing here sizes, orders, stops, or touches a broker (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .receipt import WriteReceipt, cursor_of, rowcount_of

log = logging.getLogger("tradeai.writers.data_gap_registry")

TABLE = "data_gap_registry"
WRITTEN_BY = "scripts/lib/writers/data_gap_registry_writer.py"

#: The gap types `data_gap_resolver.GAP_RESOLVERS` has an action for, plus
#: 'explicit' (the resolver routes it to the catalyst action). A gap of any other
#: type would sit open for 30 days and be abandoned, so it is rejected up front.
GAP_TYPES = (
    "missing_div_yield",
    "missing_sector",
    "missing_market_data",
    "missing_catalyst",
    "missing_thesis",
    "stale_news",
    "missing_setup_details",
    "explicit",
)
SEVERITIES = ("high", "medium", "low")
STATUSES = ("open", "enriching", "resolved", "abandoned")
LIVE_STATUSES = ("open", "enriching")
#: The overnight writer's severity rule, kept as the default.
HIGH_SEVERITY_TYPES = ("missing_catalyst", "missing_market_data", "explicit")
CONFLICT_RULE = "skip when the same symbol+gap_type is already open or enriching"

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-/^=]{0,14}$")
_NOT_SYMBOLS = frozenset({"BOOK", "PORTFOLIO", "NONE", "NULL", "N/A", "NA"})


@dataclass
class GapReceipt(WriteReceipt):
    gap_ids: list[int] = field(default_factory=list)       # rows inserted by this call
    existing_ids: list[int] = field(default_factory=list)  # already queued (open/enriching)
    deduped_in_call: int = 0                                # same symbol+type twice in one call

    @property
    def queued_ids(self) -> list[int]:
        return list(self.gap_ids) + [i for i in self.existing_ids if i not in self.gap_ids]

    def as_dict(self) -> dict[str, Any]:
        d = super().as_dict()
        d["gap_ids"] = list(self.gap_ids)
        d["existing_ids"] = list(self.existing_ids)
        d["deduped_in_call"] = self.deduped_in_call
        return d


def default_severity(gap_type: str) -> str:
    return "high" if gap_type in HIGH_SEVERITY_TYPES else "medium"


def _first_value(row: Any) -> Any:
    """First column of a fetched row, for tuple cursors and dict cursors alike."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    try:
        return row[0]
    except (TypeError, IndexError, KeyError):
        return None


def _rail(row: Any) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not isinstance(row, dict):
        return None, "row is not a mapping"
    sym = str(row.get("symbol") or "").strip().upper()
    if not sym or sym in _NOT_SYMBOLS or not _SYMBOL_RE.match(sym):
        return None, "symbol missing or not a tradable symbol"
    gap_type = str(row.get("gap_type") or "").strip()
    if gap_type not in GAP_TYPES:
        return None, f"gap_type {gap_type!r} has no resolver action"
    severity = str(row.get("severity") or default_severity(gap_type)).strip().lower()
    if severity not in SEVERITIES:
        return None, f"severity {severity!r} is not one of {SEVERITIES}"
    detail = row.get("gap_detail")
    source_job_id = row.get("source_job_id")
    if source_job_id is not None:
        try:
            source_job_id = int(source_job_id)
        except (TypeError, ValueError):
            return None, "source_job_id is not an integer"
    return {
        "symbol": sym,
        "gap_type": gap_type,
        "gap_detail": None if detail is None else str(detail),
        "severity": severity,
        "source_job_id": source_job_id,
    }, None


def register_gaps(
    target: Any,
    rows: Iterable[dict[str, Any]],
    *,
    detected_by: str,
    source: Optional[str] = None,
    run_id: Optional[str] = None,
) -> GapReceipt:
    """Queue gaps for the resolver. One dedup rule; ids for new and existing rows.

    ``target`` is a DB-API cursor or connection. The caller commits.
    """
    rows = list(rows or [])
    by = str(detected_by or "").strip()
    rec = GapReceipt(
        table=TABLE,
        source=source or by or "unknown",
        written_by=WRITTEN_BY,
        run_id=run_id,
        conflict_rule=CONFLICT_RULE,
    )
    rec.rows_in = len(rows)
    if not by:
        for r in rows:
            rec.reject(r, "detected_by is required")
        return rec
    if not rows:
        return rec
    cur = cursor_of(target)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        clean, why = _rail(row)
        if clean is None:
            rec.reject(row, why or "rejected")
            continue
        key = (clean["symbol"], clean["gap_type"])
        if key in seen:
            rec.deduped_in_call += 1
            continue
        seen.add(key)
        rec.rows_accepted += 1
        cur.execute(
            "SELECT id FROM data_gap_registry "
            "WHERE symbol = %s AND gap_type = %s AND status IN ('open', 'enriching') "
            "ORDER BY id LIMIT 1",
            [clean["symbol"], clean["gap_type"]],
        )
        rec.statements += 1
        existing = _first_value(cur.fetchone())
        if existing is not None:
            rec.existing_ids.append(int(existing))
            continue
        cur.execute(
            "INSERT INTO data_gap_registry "
            "(symbol, gap_type, gap_detail, detected_by, source_job_id, severity, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'open') RETURNING id",
            [
                clean["symbol"], clean["gap_type"], clean["gap_detail"], by,
                clean["source_job_id"], clean["severity"],
            ],
        )
        rec.statements += 1
        rec.rows_written += rowcount_of(cur) or 1
        new_id = _first_value(cur.fetchone())
        if new_id is not None:
            rec.gap_ids.append(int(new_id))
    return rec


def mark_enriching(target: Any, gap_id: int) -> int:
    cur = cursor_of(target)
    cur.execute("UPDATE data_gap_registry SET status = 'enriching' WHERE id = %s", [int(gap_id)])
    return rowcount_of(cur)


def mark_dispatched(target: Any, gap_id: int, *, job_id: str, action: str) -> int:
    """The resolver queued work for this gap. It stays 'enriching' until that work is proven.

    Before 2026-09-13 queuing a job marked the gap 'resolved' on the spot, so the
    queue's resolved count said data had landed when only a job had been queued
    (and most of those jobs were failing on an input-token cap).
    """
    jid = str(job_id or "").strip()
    if not jid:
        raise ValueError("job_id is required")
    cur = cursor_of(target)
    cur.execute(
        "UPDATE data_gap_registry SET status = 'enriching', "
        "resolution_data = COALESCE(resolution_data, '{}'::jsonb) "
        "|| jsonb_build_object('job_id', %s, 'action', %s, 'dispatched_at', NOW()) "
        "WHERE id = %s",
        [jid, str(action or ""), int(gap_id)],
    )
    return rowcount_of(cur)


def mark_resolved(target: Any, gap_id: int, *, resolved_by: str, evidence: Optional[dict[str, Any]] = None) -> int:
    """Resolved means proven: the data is present, or the dispatched job completed with a result row.

    ``evidence`` is merged into resolution_data so the row says what proved it.
    """
    by = str(resolved_by or "").strip()
    if not by:
        raise ValueError("resolved_by is required")
    cur = cursor_of(target)
    if evidence:
        cur.execute(
            "UPDATE data_gap_registry SET status = 'resolved', resolved_at = NOW(), resolved_by = %s, "
            "resolution_data = COALESCE(resolution_data, '{}'::jsonb) || %s::jsonb "
            "WHERE id = %s",
            [by, json.dumps(evidence, default=str), int(gap_id)],
        )
    else:
        cur.execute(
            "UPDATE data_gap_registry SET status = 'resolved', resolved_at = NOW(), resolved_by = %s "
            "WHERE id = %s",
            [by, int(gap_id)],
        )
    return rowcount_of(cur)


def reopen(target: Any, gap_id: int, *, reason: Optional[str] = None) -> int:
    """Back to 'open'. With a reason, the failure is recorded and the attempt counted."""
    cur = cursor_of(target)
    if reason:
        cur.execute(
            "UPDATE data_gap_registry SET status = 'open', "
            "resolution_data = COALESCE(resolution_data, '{}'::jsonb) "
            "|| jsonb_build_object('last_failure', %s, "
            "'attempts', COALESCE((resolution_data->>'attempts')::int, 0) + 1) "
            "WHERE id = %s",
            [str(reason), int(gap_id)],
        )
    else:
        cur.execute("UPDATE data_gap_registry SET status = 'open' WHERE id = %s", [int(gap_id)])
    return rowcount_of(cur)


def abandon(target: Any, gap_id: int, *, reason: str) -> int:
    """Give up on one gap after repeated failed work, saying why."""
    why = str(reason or "").strip()
    if not why:
        raise ValueError("reason is required")
    cur = cursor_of(target)
    cur.execute(
        "UPDATE data_gap_registry SET status = 'abandoned', "
        "resolution_data = COALESCE(resolution_data, '{}'::jsonb) || jsonb_build_object('abandoned_reason', %s) "
        "WHERE id = %s",
        [why, int(gap_id)],
    )
    return rowcount_of(cur)


def abandon_stale(target: Any, *, older_than_days: int) -> int:
    days = int(older_than_days)
    if days < 1:
        raise ValueError("older_than_days must be at least 1")
    cur = cursor_of(target)
    cur.execute(
        "UPDATE data_gap_registry SET status = 'abandoned' "
        "WHERE status = 'open' AND detected_at < NOW() - (%s * INTERVAL '1 day')",
        [days],
    )
    return rowcount_of(cur)
