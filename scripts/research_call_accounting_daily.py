#!/usr/bin/env python3
"""Print the authoritative rolling research-call accounting summary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from lib.research_call_accounting import add_reservation_only_events, read_events, summarize


def _load_env() -> None:
    root = Path(__file__).resolve().parent.parent
    configured = os.getenv("TRADEAI_ENV_FILE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(root / ".env")
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))
        return


def _db_reconciliation(hours: int) -> tuple[list[dict], list[dict]]:
    _load_env()
    from db_adapter import _execute
    reservations = _execute(
        """SELECT id, created_at, process_id, status, metadata_json
             FROM llm_cost_reservations
            WHERE process_id='hermes_external_research'
              AND created_at >= NOW() - (%s || ' hours')::interval""",
        (max(1, int(hours)),), fetch="all",
    )
    consumption = _execute(
        """SELECT id, created_at, metadata_json
             FROM llm_consumption_log
            WHERE process_id='hermes_external_research'
              AND created_at >= NOW() - (%s || ' hours')::interval""",
        (max(1, int(hours)),), fetch="all",
    )
    if reservations is None or consumption is None:
        raise RuntimeError("DB_UNAVAILABLE")
    return [dict(row) for row in reservations], [dict(row) for row in consumption]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--no-db", action="store_true", help="offline ledger-only report")
    args = parser.parse_args()
    events = read_events(hours=args.hours)
    db_status = "SKIPPED_OFFLINE"
    if not args.no_db:
        try:
            reservations, consumption = _db_reconciliation(args.hours)
            events = add_reservation_only_events(events, reservations, consumption)
            db_status = "RECONCILED"
        except Exception as exc:
            db_status = f"UNAVAILABLE:{type(exc).__name__}"
    report = summarize(events)
    report["ledger_reconciled"] = report["reconciled"]
    report["reservation_db_status"] = db_status
    report["reconciled"] = bool(report["ledger_reconciled"] and db_status == "RECONCILED")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["reconciled"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
