#!/usr/bin/env python3
"""Scheduled pass: let an agent read communications addressed to it.

Dry run by default. ``--apply`` writes AgentConsumptionReceipt@v2 rows only —
never wake / commitment tables (Lane A owns those).

    python3 scripts/agent_consume_communications.py --agent cio
    python3 scripts/agent_consume_communications.py --agent cio --apply

Authority: READ_ONLY_ADVISORY. Reading an operator turn is not acting on it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _connect():
    """Connect the way the application does, or return None."""
    try:
        import psycopg2
    except Exception:
        return None
    dsn = os.getenv("DATABASE_URL") or os.getenv("AGENT_RUNTIME_SOURCE_DSN")
    try:
        if dsn:
            return psycopg2.connect(dsn)
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default="cio")
    p.add_argument("--purpose", default=None)
    p.add_argument(
        "--direction",
        default="INBOUND",
        help="INBOUND (default), OUTBOUND, or 'any' for both",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--lookback-hours", type=float, default=None)
    p.add_argument("--apply", action="store_true", default=False)
    p.add_argument(
        "--orphans",
        action="store_true",
        default=False,
        help="report consumption receipts naming a non-existent event",
    )
    p.add_argument(
        "--flag-orphans",
        action="store_true",
        default=False,
        help="mark those receipts in place; requires --apply and is never implied",
    )
    args = p.parse_args(argv)

    from scripts.lib.agent_comms_consumption import (
        DEFAULT_LIMIT,
        DEFAULT_LOOKBACK_HOURS,
        DEFAULT_PURPOSE,
        consume_recent,
        flag_orphan_comms_receipts,
    )

    conn = _connect()
    if conn is None:
        print(json.dumps({"ok": False, "reason": "no_database_connection"}, indent=2))
        return 1

    if args.orphans or args.flag_orphans:
        report = flag_orphan_comms_receipts(
            conn, apply=bool(args.flag_orphans and args.apply)
        )
        print(json.dumps(report, indent=2, default=str))
        return 0

    direction = None if str(args.direction).lower() == "any" else args.direction
    report = consume_recent(
        args.agent,
        conn=conn,
        purpose=args.purpose or DEFAULT_PURPOSE,
        direction=direction,
        limit=args.limit if args.limit is not None else DEFAULT_LIMIT,
        lookback_hours=(
            args.lookback_hours
            if args.lookback_hours is not None
            else DEFAULT_LOOKBACK_HOURS
        ),
        apply=bool(args.apply),
        provenance={"producer": "test"} if not args.apply else None,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("consumed") or not report.get("selected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
