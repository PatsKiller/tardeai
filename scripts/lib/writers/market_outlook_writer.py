"""The one write path for ``market_outlook_records`` and ``market_outlook_grades`` (§4.6).

Same contract as every other writer in ``scripts/lib/writers/``: validate the row first, then one parameterised
statement per row with ``ON CONFLICT DO NOTHING`` — a record is immutable, so a re-run of the same record_id writes
nothing instead of overwriting. The caller owns the transaction; this module never commits.

The CIO row (symbol ``MARKET``, ``strategy_type='market_outlook'``) is WU-3's write. :func:`cio_payload` returns the
exact column values so that lane builds the row from the record rather than re-deriving it.
"""

from __future__ import annotations

import json
from typing import Any

TABLE = "market_outlook_records"
GRADES_TABLE = "market_outlook_grades"
WRITTEN_BY = "scripts/lib/writers/market_outlook_writer.py"
COLUMNS: tuple[str, ...] = (
    "record_id",
    "as_of",
    "mode",
    "score",
    "band",
    "confidence",
    "confidence_band",
    "policy_version",
    "engine_commit",
    "record",
)
INSERT_SQL = (
    "INSERT INTO market_outlook_records "
    "(record_id, as_of, mode, score, band, confidence, confidence_band, policy_version, engine_commit, record) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (record_id) DO NOTHING"
)
GRADE_SQL = (
    "INSERT INTO market_outlook_grades "
    "(record_id, week_ending, realized, scenario_hit, brier, level_hits, band_hit, status, payload) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (record_id) DO NOTHING"
)


def _validate_record(record: dict[str, Any]) -> str | None:
    try:
        from scripts.lib.market_outlook.record import validate
    except ImportError:  # scripts/ on sys.path
        from lib.market_outlook.record import validate  # type: ignore[no-redef]

    problems = validate(record)
    return "; ".join(problems) if problems else None


def _row(record: dict[str, Any]) -> list[Any]:
    conf = (record.get("confidence") or {})
    return [
        record.get("record_id"),
        record.get("as_of"),
        record.get("mode"),
        record.get("score"),
        record.get("band"),
        conf.get("value"),
        conf.get("band"),
        record.get("policy_version"),
        record.get("engine_commit") or "",
        json.dumps(record, sort_keys=True, default=str),
    ]


def write_records(cur: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and insert each record. Returns a receipt dict; a rejected record is named with its reason."""
    accepted, rejected, written = 0, [], 0
    for rec in records:
        why = _validate_record(rec)
        if why:
            rejected.append({"record_id": rec.get("record_id"), "reason": why})
            continue
        cur.execute(INSERT_SQL, _row(rec))
        accepted += 1
        written += int(getattr(cur, "rowcount", 1) or 0)
    return {
        "schema": "WriteReceipt@v1",
        "table": TABLE,
        "written_by": WRITTEN_BY,
        "attempted": len(records),
        "accepted": accepted,
        "inserted": written,
        "rejected": rejected,
        "conflict_rule": "ON CONFLICT (record_id) DO NOTHING",
    }


def write_grades(cur: Any, grades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted, rejected, written = 0, [], 0
    for g in grades:
        missing = [k for k in ("record_id", "week_ending", "status") if not g.get(k)]
        if missing:
            rejected.append({"record_id": g.get("record_id"), "reason": f"missing {','.join(missing)}"})
            continue
        cur.execute(
            GRADE_SQL,
            [
                g.get("record_id"),
                g.get("week_ending"),
                json.dumps(g.get("realized"), sort_keys=True, default=str) if g.get("realized") is not None else None,
                g.get("scenario_hit"),
                g.get("brier"),
                json.dumps(g.get("level_hits"), sort_keys=True, default=str) if g.get("level_hits") is not None else None,
                g.get("band_hit"),
                g.get("status"),
                json.dumps(g, sort_keys=True, default=str),
            ],
        )
        accepted += 1
        written += int(getattr(cur, "rowcount", 1) or 0)
    return {
        "schema": "WriteReceipt@v1",
        "table": GRADES_TABLE,
        "written_by": WRITTEN_BY,
        "attempted": len(grades),
        "accepted": accepted,
        "inserted": written,
        "rejected": rejected,
        "conflict_rule": "ON CONFLICT (record_id) DO NOTHING",
    }


def cio_payload(record: dict[str, Any]) -> dict[str, Any]:
    """The ``cio_decisions`` row values WU-3 inserts — built here so the record stays the single source."""
    conf = record.get("confidence") or {}
    cats = record.get("categories") or []
    summary = [
        {"key": c.get("key"), "subscore": c.get("subscore"), "state": c.get("state"), "coverage": c.get("coverage")}
        for c in cats
    ]
    return {
        "symbol": "MARKET",
        "strategy_type": "market_outlook",
        "group_id": record.get("record_id"),
        "action": record.get("band"),
        "confidence_calibrated": conf.get("value"),
        "supporting_signals": summary,
        "metadata": {
            "record_id": record.get("record_id"),
            "policy_version": record.get("policy_version"),
            "mode": record.get("mode"),
            "score": record.get("score"),
        },
    }


__all__ = ["write_records", "write_grades", "cio_payload", "TABLE", "GRADES_TABLE"]
