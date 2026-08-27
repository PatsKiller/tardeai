#!/usr/bin/env python3
"""Bind catalysts to durable entities and write the projection. Phase C.

    python scripts/build_catalyst_graph.py                  # dry run (default)
    python scripts/build_catalyst_graph.py --limit 40000
    python scripts/build_catalyst_graph.py --symbol NOC     # one entity's timeline
    python scripts/build_catalyst_graph.py --apply          # write the projection

The projection is derived and rebuildable, per `ADR_DURABLE_STATE_EVENT_SOURCING`
(event log authoritative, projections derived). `catalyst_events` stays the
source of truth; deleting the output and re-running reproduces it exactly,
because every node id is a deterministic UUIDv5 of (issuer, event_type, period).

AUTHORITY: READ_ONLY_ADVISORY. Reads catalysts, writes one projection file.
No trading authority, no scoring, no materiality judgement.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.catalyst_graph import build_graph, events_for_entity  # noqa: E402
from scripts.lib.identity_registry import load as load_registry, lookup_symbol  # noqa: E402

PROJECTION_RELATIVE = Path("data") / "cio" / "catalyst_graph_latest.json"


def projection_path() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root()) / PROJECTION_RELATIVE
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state" / PROJECTION_RELATIVE


def fetch_catalysts(limit: int) -> list[dict]:
    from price_db_sync import _get_conn  # type: ignore
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT id, symbol, catalyst_type, headline, source,
                              published_at, created_at
                         FROM catalyst_events
                        ORDER BY published_at DESC NULLS LAST
                        LIMIT %s""", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the catalyst→entity graph (Phase C)")
    ap.add_argument("--apply", action="store_true", help="write the projection")
    ap.add_argument("--limit", type=int, default=40000, help="catalysts to scan (newest first)")
    ap.add_argument("--symbol", default=None, help="print one entity's lifecycle timeline")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    registry = load_registry()
    graph = build_graph(fetch_catalysts(args.limit), registry)

    if args.symbol:
        entity = lookup_symbol(registry, args.symbol)
        if not entity:
            print(f"{args.symbol}: not a registered entity")
            return 0
        timeline = events_for_entity(graph, entity["subject_guid"])
        print(f"{args.symbol}  subject_guid={entity['subject_guid']}  "
              f"({entity['identity_status']})  {len(timeline)} event(s)\n")
        for ev in timeline:
            print(f"  {str(ev.get('as_of'))[:10]}  {ev['event_type']:<22}"
                  f"{ev['period']:<10}{ev['event_guid'][:8]}")
        return 0

    if args.json:
        print(json.dumps({k: v for k, v in graph.items() if k not in ("nodes", "traces")},
                         indent=2, sort_keys=True))
    else:
        print(f"{'APPLY' if args.apply else 'DRY RUN'}")
        print(f"  lifecycle nodes  {graph['node_count']:,}")
        print(f"  entity edges     {graph['trace_count']:,}")
        print(f"  bound by type    {graph['bound_by_type']}")
        print(f"  skipped          {graph['skipped']}")

    if args.apply:
        path = projection_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(graph)
        payload["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        payload["derived"] = True          # rebuildable projection, not a source of truth
        payload["source"] = "catalyst_events"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(path)
        print(f"\n  wrote {path}")
    elif not args.json:
        print("\nnothing written. re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
