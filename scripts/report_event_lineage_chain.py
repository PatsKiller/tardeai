#!/usr/bin/env python3
"""Read-only: walk one operator question's lineage by event id.

    turn (operator_conversation_turns)
      -> gap / pending rows      (cio_operator_gap_requests.jsonl, cio_operator_pending_replies.jsonl)
      -> research request        (hermes_research_requests.jsonl)
      -> research completion     (hermes_research_results.jsonl)
      -> outbound                (communication_events, agent turns)

Every hop is joined on ``causation_id`` / ``parent_event_id`` = the root
inbound event id (scripts/lib/event_lineage.py), never on the ticker. A hop
with no rows is reported as empty, which is the measurement of what is still
unlinked.

Usage:
  python scripts/report_event_lineage_chain.py --event-id <inbound event id>
  python scripts/report_event_lineage_chain.py --turn-id 410
  python scripts/report_event_lineage_chain.py --event-id <id> --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA = "EventLineageChain@v1"
NO_CONSUMER_REASON = (
    "operator-run read-only CLI (python scripts/report_event_lineage_chain.py --event-id ...); "
    "nothing imports the report schema, it is printed for a human"
)
AUTHORITY = "READ_ONLY_ADVISORY"
HOPS = ("turns", "gap_requests", "pending_replies", "research_requests", "research_results", "outbound_events")


def _links_to(row: Mapping[str, Any], root: str) -> bool:
    return any(str(row.get(k) or "") == root for k in ("event_id", "causation_id", "parent_event_id"))


def build_chain(
    root_event_id: str,
    *,
    turns: Iterable[Mapping[str, Any]] = (),
    gap_rows: Iterable[Mapping[str, Any]] = (),
    pending_rows: Iterable[Mapping[str, Any]] = (),
    research_request_rows: Iterable[Mapping[str, Any]] = (),
    research_result_rows: Iterable[Mapping[str, Any]] = (),
    outbound_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Pure join: every row of every hop that names ``root_event_id``."""
    root = str(root_event_id or "").strip()
    if not root:
        raise ValueError("root_event_id required")

    def pick(rows: Iterable[Mapping[str, Any]], keep: tuple[str, ...]) -> list[dict[str, Any]]:
        out = []
        for r in rows or ():
            if isinstance(r, Mapping) and _links_to(r, root):
                out.append({k: r.get(k) for k in keep if r.get(k) is not None})
        return out

    chain = {
        "turns": pick(
            turns,
            (
                "id",
                "role",
                "chat_id",
                "message_id",
                "reply_to_message_id",
                "symbol",
                "subject_guid",
                "event_id",
                "causation_id",
                "parent_event_id",
                "occurred_at",
            ),
        ),
        "gap_requests": pick(
            gap_rows,
            (
                "ts",
                "pending_id",
                "kind",
                "plan_id",
                "research_id",
                "symbols",
                "subject_guid",
                "causation_id",
                "parent_event_id",
            ),
        ),
        "pending_replies": pick(
            pending_rows, ("pending_id", "status", "message_id", "causation_id", "parent_event_id")
        ),
        "research_requests": pick(
            research_request_rows,
            ("event", "research_id", "plan_id", "symbol", "subject_guid", "causation_id", "parent_event_id"),
        ),
        "research_results": pick(
            research_result_rows,
            ("event", "research_id", "result_id", "symbol", "subject_guid", "causation_id", "parent_event_id"),
        ),
        "outbound_events": pick(
            outbound_events,
            ("event_id", "direction", "producer", "subject_guid", "causation_id", "parent_event_id", "created_at"),
        ),
    }
    research_ids = sorted(
        {
            str(r["research_id"])
            for hop in ("gap_requests", "research_requests")
            for r in chain[hop]
            if r.get("research_id")
        }
    )
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "root_event_id": root,
        "research_ids": research_ids,
        "hop_counts": {h: len(chain[h]) for h in HOPS},
        "complete": all(chain[h] for h in ("turns", "research_requests", "research_results")),
        "chain": chain,
    }


# ── live loaders (read-only) ────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _cio_dir() -> Path:
    env = os.environ.get("TRADEAI_CIO_DATA_DIR")
    if env:
        return Path(env)
    try:
        from scripts.lib.canonical_store_registry import production_state_root  # noqa: PLC0415

        return Path(production_state_root()) / "data" / "cio"
    except Exception:  # noqa: BLE001
        return ROOT / "data" / "cio"


def _connect():
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("refusing to open a database connection under pytest")
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT") or None,
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.set_session(readonly=True)
    return conn


def _turn_columns(cur) -> set[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'operator_conversation_turns'")
    return {r["column_name"] for r in cur.fetchall()}


def load_live(root_event_id: Optional[str], turn_id: Optional[int]) -> tuple[str, dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cols = _turn_columns(cur)
        has_lineage = {"event_id", "causation_id", "parent_event_id"} <= cols
        root = root_event_id
        if not root and turn_id is not None:
            if has_lineage:
                cur.execute("SELECT event_id FROM operator_conversation_turns WHERE id = %s", (int(turn_id),))
                r = cur.fetchone()
                root = (r or {}).get("event_id")
            if not root:
                cur.execute(
                    "SELECT e.event_id FROM operator_conversation_turns t JOIN communication_events e"
                    "  ON e.direction = 'INBOUND' AND e.provider_coordinates->>'message_id' = t.message_id::text"
                    " AND e.provider_coordinates->>'chat_id' = t.chat_id WHERE t.id = %s LIMIT 1",
                    (int(turn_id),),
                )
                r = cur.fetchone()
                root = (r or {}).get("event_id")
        if not root:
            raise SystemExit("no root event id: pass --event-id, or a --turn-id whose inbound event is on the ledger")
        turns: list[dict[str, Any]] = []
        if has_lineage:
            cur.execute(
                "SELECT * FROM operator_conversation_turns WHERE %s IN (event_id, causation_id, parent_event_id)"
                " ORDER BY id",
                (root,),
            )
            turns = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT event_id, direction, producer, subject_guid, causation_id, parent_event_id, created_at"
            "  FROM communication_events WHERE %s IN (event_id, causation_id, parent_event_id)"
            " ORDER BY created_at",
            (root,),
        )
        events = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    cio = _cio_dir()
    return root, {
        "turns": turns,
        "gap_rows": _read_jsonl(cio / "cio_operator_gap_requests.jsonl"),
        "pending_rows": _read_jsonl(cio / "cio_operator_pending_replies.jsonl"),
        "research_request_rows": _read_jsonl(cio / "hermes_research_requests.jsonl"),
        "research_result_rows": _read_jsonl(cio / "hermes_research_results.jsonl"),
        "outbound_events": events,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--event-id")
    ap.add_argument("--turn-id", type=int)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.event_id and args.turn_id is None:
        ap.error("--event-id or --turn-id required")
    root, stores = load_live(args.event_id, args.turn_id)
    report = build_chain(root, **stores)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"root event: {report['root_event_id']}")
    for hop in HOPS:
        print(f"  {hop:18s} {report['hop_counts'][hop]}")
    if report["research_ids"]:
        print(f"  research ids: {', '.join(report['research_ids'])}")
    print(f"  complete (turn -> request -> result): {report['complete']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
