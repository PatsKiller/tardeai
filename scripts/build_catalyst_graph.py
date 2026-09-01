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

# Writer-status sidecar is operator/diagnose output written beside the
# projection; no production importer reads CatalystGraphWriterStatus@v1 yet.
# --diagnose-staleness and the audit doc are the consumers of record.
NO_CONSUMER_REASON = (
    "CatalystGraphWriterStatus@v1 is a served-path staleness sidecar for E5; "
    "operators read it via --diagnose-staleness / audit, no code importer yet."
)

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.catalyst_graph import build_graph, events_for_entity  # noqa: E402
from scripts.lib.identity_registry import load as load_registry, lookup_symbol  # noqa: E402

PROJECTION_RELATIVE = Path("data") / "cio" / "catalyst_graph_latest.json"
MOMENTUM_RELATIVE = Path("data") / "hermes" / "momentum_catalysts"
WRITER_STATUS_RELATIVE = Path("data") / "cio" / "catalyst_graph_writer_status.json"


def _state_root() -> Path:
    """Served / authoritative state root — never checkout-relative.

    E5: graph and momentum consumers must resolve here, not via cron cwd.
    `data/cio` under CURRENT is already a symlink into this root; hermes is not.
    """
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state"


def projection_path() -> Path:
    return _state_root() / PROJECTION_RELATIVE


def momentum_catalysts_dir() -> Path:
    """Canonical hermes momentum jsonl directory (served-state root)."""
    return _state_root() / MOMENTUM_RELATIVE


def diagnose_writer_staleness() -> dict:
    """E5: are graph/momentum artifacts fresh, and do they sit on the served path?"""
    from datetime import datetime, timezone

    graph = projection_path()
    mom = momentum_catalysts_dir()
    now = datetime.now(timezone.utc)
    graph_mtime = None
    if graph.is_file():
        graph_mtime = datetime.fromtimestamp(graph.stat().st_mtime, timezone.utc)
    mom_files = sorted(mom.glob("*_catalysts.jsonl")) if mom.is_dir() else []
    mom_latest = mom_files[-1] if mom_files else None
    mom_mtime = (
        datetime.fromtimestamp(mom_latest.stat().st_mtime, timezone.utc)
        if mom_latest is not None else None
    )

    def age_hours(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        return round((now - ts).total_seconds() / 3600.0, 1)

    return {
        "as_of": now.replace(microsecond=0).isoformat(),
        "state_root": str(_state_root()),
        "graph": {
            "path": str(graph),
            "exists": graph.is_file(),
            "mtime": graph_mtime.replace(microsecond=0).isoformat() if graph_mtime else None,
            "age_hours": age_hours(graph_mtime),
            "scheduled": False,
            "schedule_note": (
                "build_catalyst_graph.py is NOT in crontab. news_to_catalyst and "
                "catalyst_momentum_engine are. Projection path already uses "
                "production_state_root (not cron cwd)."
            ),
        },
        "momentum_jsonl": {
            "path": str(mom),
            "exists": mom.is_dir(),
            "file_count": len(mom_files),
            "latest": mom_latest.name if mom_latest is not None else None,
            "mtime": mom_mtime.replace(microsecond=0).isoformat() if mom_mtime else None,
            "age_hours": age_hours(mom_mtime),
            "scheduled_writer": "hermes_momentum_catalyst_researcher.py (checkout-relative PROJECT_ROOT)",
            "served_path_split": (
                "CURRENT/data/hermes is NOT symlinked to persistent-state; "
                "writer uses checkout data/hermes — fix is resolution layer, not cron cwd."
            ),
        },
        "authority": "READ_ONLY_ADVISORY",
    }

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
    ap.add_argument(
        "--diagnose-staleness",
        action="store_true",
        help="E5: report graph/momentum path freshness on the served state root",
    )
    args = ap.parse_args()

    if args.diagnose_staleness:
        report = diagnose_writer_staleness()
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"as_of={report['as_of']}  state_root={report['state_root']}")
            g = report["graph"]
            print(f"graph  exists={g['exists']}  age_h={g['age_hours']}  "
                  f"scheduled={g['scheduled']}  path={g['path']}")
            print(f"       {g['schedule_note']}")
            m = report["momentum_jsonl"]
            print(f"momentum_jsonl  files={m['file_count']}  latest={m['latest']}  "
                  f"age_h={m['age_hours']}  path={m['path']}")
            print(f"       {m['served_path_split']}")
        return 0

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
        # Writer status on the same served root so staleness is observable
        # without reading checkout-relative logs.
        status_path = _state_root() / WRITER_STATUS_RELATIVE
        status = {
            "schema": "CatalystGraphWriterStatus@v1",
            "generated_at": payload["generated_at"],
            "projection_path": str(path),
            "node_count": graph["node_count"],
            "trace_count": graph["trace_count"],
            "skipped": graph.get("skipped"),
            "scheduled": False,
            "authority": "READ_ONLY_ADVISORY",
        }
        stmp = status_path.with_suffix(status_path.suffix + ".tmp")
        stmp.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
        stmp.replace(status_path)
        print(f"\n  wrote {path}")
        print(f"  wrote {status_path}")
    elif not args.json:
        print(f"\nprojection path (served): {projection_path()}")
        print("nothing written. re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
