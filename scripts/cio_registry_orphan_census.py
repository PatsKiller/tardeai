#!/usr/bin/env python3
"""CanonicalStoreRegistry orphan / missing-cross-id census (read-only).

Scans registry-linked stores for missing cross-ids and referential orphans in a
bounded time window. Fail-soft per store. Never writes. Never auto-remediates.

    python scripts/cio_registry_orphan_census.py            # human summary
    python scripts/cio_registry_orphan_census.py --json     # machine readable
    python scripts/cio_registry_orphan_census.py --days 30 --root /path

Integrates ``cio_lineage_completion_report`` baseline (G-LOOP-01 / 54% → 99.99%
path is design-only here; this tool measures, it does not repair).

AUTHORITY: READ_ONLY_ADVISORY. MBI=0. never_auto_remediate store_consistency.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

NO_CONSUMER_REASON = (
    "operator-invoked diligence CLI: CIORegistryOrphanCensus@v1 is a stdout receipt for Phase 9 orphan scans, not an ingested store contract"
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.canonical_store_registry import (  # noqa: E402
    AUTHORITY,
    CANONICAL_ID_FIELDS,
    MBI,
    STORES,
    production_state_root,
    resolve_store,
)
from scripts.lib.cio_lineage_health import completion_report  # noqa: E402

SCHEMA = "CIORegistryOrphanCensus@v1"
DEFAULT_DAYS = 30
# Cap rows read per store so a multi-GB jsonl cannot stall the census.
DEFAULT_ROW_CAP = 50_000
# How many orphan / missing samples to keep in the JSON report.
SAMPLE_CAP = 25

# Stores that participate in the cross-id / orphan graph. Declared id_fields
# (when present) plus the lineage/checkpoint hubs that mint the shared namespace.
SCAN_STORES: tuple[str, ...] = (
    "cio.workflow_lineage",
    "cio.checkpoints",
    "cio.outcomes",
    "cio.specialist_artifacts",
    "cio.notification_policy",
    "cio.delivery_receipts",
    "cio.lesson_binds",
    "cio.instrument_records",
    "notifications.audit",
    "notifications.outbox",
    "research.raw",
    "cio.agent_traces",
)

# Which stores contribute to each hub index. Satellite edges are checked
# against these hubs only — never against the satellite's own rows (that would
# make referential orphans tautologically impossible).
HUB_INDEX_SOURCES: dict[str, tuple[str, ...]] = {
    "workflow_id": ("cio.workflow_lineage",),
    "checkpoint_id": ("cio.workflow_lineage", "cio.checkpoints"),
    "notification_id": (
        "cio.workflow_lineage",
        "notifications.audit",
        "notifications.outbox",
    ),
    "event_id": ("cio.workflow_lineage",),
}

# Cross-store edges: (source_store, field, hub_index_key)
CROSS_EDGES: tuple[tuple[str, str, str], ...] = (
    ("cio.checkpoints", "workflow_id", "workflow_id"),
    ("cio.specialist_artifacts", "workflow_id", "workflow_id"),
    ("cio.lesson_binds", "checkpoint_id", "checkpoint_id"),
    ("cio.delivery_receipts", "notification_id", "notification_id"),
    ("cio.notification_policy", "notification_id", "notification_id"),
    ("cio.outcomes", "checkpoint_id", "checkpoint_id"),
)

# Fields we treat as "expected when the row is in the production window" for
# missing-cross-id counts. Not every store always stamps every id — we only
# flag declared id_fields (registry) plus the shared lineage keys on the hub.
HUB_EXPECTED_IDS = ("workflow_id", "event_id")

# Append-only stores: fold to latest row per primary key before counting so
# stage-transition history does not inflate missing-cross-id hits.
FOLD_PRIMARY_KEY: dict[str, str] = {
    "cio.workflow_lineage": "workflow_id",
    "cio.checkpoints": "checkpoint_id",
    "cio.specialist_artifacts": "artifact_id",
    "cio.delivery_receipts": "dedupe_key",
    "cio.notification_policy": "notification_id",
    "cio.lesson_binds": "lesson_id",
    "cio.instrument_records": "subject_key",
    "cio.outcomes": "outcome_id",
    "notifications.audit": "notification_id",
    "notifications.outbox": "notification_id",
    "cio.agent_traces": "workflow_id",
}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    # Tolerate "YYYY-MM-DD HH:MM:SS" (space separator)
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_ts(row: dict[str, Any]) -> datetime | None:
    for key in (
        "recorded_at",
        "created_at",
        "updated_at",
        "updated_ts",
        "created_ts",
        "as_of",
        "due_at",
    ):
        dt = _parse_ts(row.get(key))
        if dt is not None:
            return dt
    nested = row.get("original_decision_state")
    if isinstance(nested, dict):
        dt = _parse_ts(nested.get("as_of") or nested.get("created_at"))
        if dt is not None:
            return dt
    return None


def _in_window(row: dict[str, Any], *, cutoff: datetime | None) -> bool:
    """Rows without a parseable timestamp are included (fail-soft inclusion)."""
    if cutoff is None:
        return True
    ts = _row_ts(row)
    if ts is None:
        return True
    return ts >= cutoff


def _iter_jsonl(path: Path, *, row_cap: int) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= row_cap:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _iter_json_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        # Some current-projection stores wrap a list under a known key.
        for key in ("records", "items", "rows", "holdings", "entries"):
            val = raw.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        yield item
                return
        yield raw
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item


def _load_store_rows(
    store_id: str,
    *,
    root: Path,
    row_cap: int,
) -> dict[str, Any]:
    """Fail-soft load. Never raises."""
    try:
        loc = resolve_store(store_id, root=root)
    except Exception as exc:  # noqa: BLE001 — census must not abort
        return {
            "store_id": store_id,
            "ok": False,
            "exists": False,
            "error": type(exc).__name__,
            "rows": [],
        }
    if not loc.get("ok"):
        return {
            "store_id": store_id,
            "ok": False,
            "exists": False,
            "error": loc.get("reason") or "UNKNOWN_STORE",
            "rows": [],
        }
    if not loc.get("exists"):
        return {
            "store_id": store_id,
            "ok": True,
            "exists": False,
            "path": str(loc.get("primary_path")),
            "unavailable_reason": loc.get("unavailable_reason") or "PRODUCER_NOT_RUN",
            "rows": [],
        }
    path = Path(loc["path"])
    spec = loc.get("spec") or STORES.get(store_id) or {}
    fmt = spec.get("format") or path.suffix.lstrip(".")
    rows: list[dict[str, Any]] = []
    try:
        if fmt == "jsonl" or path.suffix == ".jsonl":
            rows = list(_iter_jsonl(path, row_cap=row_cap))
        elif fmt == "json" or path.suffix == ".json":
            rows = list(_iter_json_records(path))[:row_cap]
        elif fmt == "dir":
            # Ops dirs are not row-addressable for cross-id census.
            return {
                "store_id": store_id,
                "ok": True,
                "exists": True,
                "path": str(path),
                "skipped": "DIR_FORMAT",
                "rows": [],
            }
        else:
            return {
                "store_id": store_id,
                "ok": True,
                "exists": True,
                "path": str(path),
                "skipped": f"UNSUPPORTED_FORMAT:{fmt}",
                "rows": [],
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "store_id": store_id,
            "ok": False,
            "exists": True,
            "path": str(path),
            "error": type(exc).__name__,
            "rows": [],
        }
    return {
        "store_id": store_id,
        "ok": True,
        "exists": True,
        "path": str(path),
        "format": fmt,
        "rows": rows,
        "rows_read": len(rows),
        "id_fields": list(spec.get("id_fields") or []),
    }


def _id_value(row: dict[str, Any], field: str) -> str | None:
    val = row.get(field)
    if val is None:
        return None
    text = str(val).strip()
    if not text or text.lower() in {"none", "null", "undefined"}:
        return None
    return text


def _fold_latest(rows: list[dict[str, Any]], primary_key: str) -> list[dict[str, Any]]:
    """Keep the newest row per primary key. Rows lacking the key stay as-is."""
    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        pk = _id_value(row, primary_key)
        if not pk:
            passthrough.append(row)
            continue
        stamp = str(
            row.get("updated_at")
            or row.get("recorded_at")
            or row.get("created_at")
            or row.get("updated_ts")
            or row.get("created_ts")
            or row.get("as_of")
            or ""
        )
        if pk not in latest or stamp >= latest[pk][0]:
            latest[pk] = (stamp, row)
    return [row for _, row in latest.values()] + passthrough


def census(
    *,
    root: Path | str | None = None,
    days: int = DEFAULT_DAYS,
    row_cap: int = DEFAULT_ROW_CAP,
    include_lineage_baseline: bool = True,
) -> dict[str, Any]:
    """Run the orphan / missing-cross-id census. Read-only; never writes."""
    base = production_state_root(root)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
    if days <= 0:
        cutoff = None  # unbounded

    store_loads: dict[str, dict[str, Any]] = {}
    for store_id in SCAN_STORES:
        store_loads[store_id] = _load_store_rows(store_id, root=base, row_cap=row_cap)

    # Fold append-only stores to latest-per-primary before windowing/counting.
    folded_rows: dict[str, list[dict[str, Any]]] = {}
    for store_id, loaded in store_loads.items():
        rows = list(loaded.get("rows") or [])
        pk = FOLD_PRIMARY_KEY.get(store_id)
        if pk:
            rows = _fold_latest(rows, pk)
        folded_rows[store_id] = rows

    # Hub indexes: only from HUB_INDEX_SOURCES so satellite self-hits cannot
    # mask referential orphans.
    indexes: dict[str, set[str]] = defaultdict(set)
    for hub_field, sources in HUB_INDEX_SOURCES.items():
        for source_id in sources:
            for row in folded_rows.get(source_id) or []:
                if not _in_window(row, cutoff=cutoff):
                    continue
                val = _id_value(row, hub_field)
                if val:
                    indexes[hub_field].add(val)

    store_stats: dict[str, dict[str, Any]] = {}
    missing_cross: list[dict[str, Any]] = []
    missing_by_store_field: Counter[str] = Counter()
    orphans: list[dict[str, Any]] = []
    orphan_by_edge: Counter[str] = Counter()

    for store_id, loaded in store_loads.items():
        rows = folded_rows.get(store_id) or []
        in_window = [r for r in rows if _in_window(r, cutoff=cutoff)]
        declared = list(loaded.get("id_fields") or [])

        # Missing cross-ids: declared id_fields empty on in-window rows.
        # Lineage hub also expects workflow_id + event_id.
        expect = list(declared)
        if store_id == "cio.workflow_lineage":
            for f in HUB_EXPECTED_IDS:
                if f not in expect:
                    expect.append(f)
        if store_id == "cio.specialist_artifacts" and "workflow_id" not in expect:
            expect.append("workflow_id")

        missing_n = 0
        for row in in_window:
            for field in expect:
                if _id_value(row, field) is None:
                    missing_n += 1
                    missing_by_store_field[f"{store_id}.{field}"] += 1
                    if len(missing_cross) < SAMPLE_CAP:
                        missing_cross.append({
                            "store_id": store_id,
                            "field": field,
                            "row_keys": {
                                k: row.get(k)
                                for k in ("workflow_id", "checkpoint_id", "artifact_id",
                                          "notification_id", "lesson_id", "plan_id",
                                          "subject_key", "dedupe_key")
                                if k in row
                            },
                        })

        store_stats[store_id] = {
            "exists": bool(loaded.get("exists")),
            "ok": bool(loaded.get("ok")),
            "path": loaded.get("path"),
            "unavailable_reason": loaded.get("unavailable_reason"),
            "error": loaded.get("error"),
            "skipped": loaded.get("skipped"),
            "rows_read": loaded.get("rows_read", 0),
            "rows_folded": len(rows),
            "rows_in_window": len(in_window),
            "id_fields": declared,
            "missing_cross_id_hits": missing_n,
        }

    # Referential orphans: satellite FK absent from hub index.
    for source_store, field, ref_key in CROSS_EDGES:
        rows = [
            r for r in (folded_rows.get(source_store) or [])
            if _in_window(r, cutoff=cutoff)
        ]
        hub = indexes.get(ref_key) or set()
        hub_sources = HUB_INDEX_SOURCES.get(ref_key) or ()
        hub_store_present = any(
            (store_loads.get(s) or {}).get("exists") for s in hub_sources
        )
        if not hub_store_present:
            notes = store_stats.setdefault(source_store, {}).setdefault("notes", [])
            notes.append(f"skip_orphan_edge:{field}->{ref_key}:hub_store_absent")
            continue
        for row in rows:
            val = _id_value(row, field)
            if val is None:
                continue  # counted under missing_cross_ids
            if val not in hub:
                orphan_by_edge[f"{source_store}.{field}->{ref_key}"] += 1
                if len(orphans) < SAMPLE_CAP:
                    orphans.append({
                        "store_id": source_store,
                        "field": field,
                        "value": val,
                        "ref_key": ref_key,
                        "row_keys": {
                            k: row.get(k)
                            for k in ("workflow_id", "checkpoint_id", "artifact_id",
                                      "notification_id", "lesson_id", "plan_id",
                                      "dedupe_key")
                            if k in row
                        },
                    })

    # Null-workflow specialist artifacts are orphans even without a FK value.
    for row in (folded_rows.get("cio.specialist_artifacts") or []):
        if not _in_window(row, cutoff=cutoff):
            continue
        if _id_value(row, "workflow_id") is None:
            orphan_by_edge["cio.specialist_artifacts.null_workflow_id"] += 1
            if len(orphans) < SAMPLE_CAP:
                orphans.append({
                    "store_id": "cio.specialist_artifacts",
                    "field": "workflow_id",
                    "value": None,
                    "ref_key": "workflow_id",
                    "class": "null_hub_id",
                    "row_keys": {
                        k: row.get(k)
                        for k in ("artifact_id", "research_id", "plan_id")
                        if k in row
                    },
                })

    missing_total = int(sum(missing_by_store_field.values()))
    orphan_total = int(sum(orphan_by_edge.values()))

    lineage_baseline: dict[str, Any] | None = None
    if include_lineage_baseline:
        try:
            lineage_path = None
            lin = store_loads.get("cio.workflow_lineage") or {}
            if lin.get("exists") and lin.get("path"):
                lineage_path = lin["path"]
            lineage_baseline = completion_report(lineage_path)
        except Exception as exc:  # noqa: BLE001
            lineage_baseline = {
                "ok": False,
                "error": type(exc).__name__,
                "note": "lineage baseline failed soft; census continues",
            }

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "never_auto_remediate": True,
        "root": str(base),
        "window_days": days,
        "cutoff_utc": cutoff.isoformat() if cutoff else None,
        "row_cap": row_cap,
        "scan_stores": list(SCAN_STORES),
        "stores": store_stats,
        "index_sizes": {k: len(v) for k, v in sorted(indexes.items()) if v},
        "missing_cross_ids": {
            "total_hits": missing_total,
            "by_store_field": dict(sorted(missing_by_store_field.items(), key=lambda kv: -kv[1])),
            "samples": missing_cross,
        },
        "orphans": {
            "total_hits": orphan_total,
            "by_edge": dict(sorted(orphan_by_edge.items(), key=lambda kv: -kv[1])),
            "samples": orphans,
        },
        "headline": {
            "stores_scanned": len(SCAN_STORES),
            "stores_present": sum(1 for s in store_stats.values() if s.get("exists")),
            "missing_cross_id_hits": missing_total,
            "orphan_hits": orphan_total,
            "window_days": days,
        },
        "lineage_baseline": lineage_baseline,
        "rails": {
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "never_auto_remediate_store_consistency": True,
            "read_only": True,
        },
    }


def render(report: dict[str, Any]) -> str:
    h = report.get("headline") or {}
    lines = [
        "CIO registry orphan census (READ_ONLY_ADVISORY · MBI=0)",
        f"root                     {report.get('root')}",
        f"window_days              {report.get('window_days')}",
        f"stores_present           {h.get('stores_present')}/{h.get('stores_scanned')}",
        f"missing_cross_id_hits    {h.get('missing_cross_id_hits')}",
        f"orphan_hits              {h.get('orphan_hits')}",
    ]
    lb = report.get("lineage_baseline") or {}
    if isinstance(lb, dict) and lb.get("workflows") is not None:
        total = lb.get("workflows")
        done = lb.get("complete_to_checkpoint")
        rate = lb.get("completion_rate")
        rate_s = f"  ({rate:.1%})" if isinstance(rate, (int, float)) else ""
        lines.append(f"lineage_baseline         {done}/{total} complete_to_checkpoint{rate_s}")
        arcs = lb.get("arcs") or {}
        if arcs:
            lines.append(f"lineage_arcs             {arcs}")
    miss = (report.get("missing_cross_ids") or {}).get("by_store_field") or {}
    if miss:
        lines.append("top missing cross-ids:")
        for k, v in list(miss.items())[:8]:
            lines.append(f"  {k}: {v}")
    orph = (report.get("orphans") or {}).get("by_edge") or {}
    if orph:
        lines.append("top orphan edges:")
        for k, v in list(orph.items())[:8]:
            lines.append(f"  {k}: {v}")
    elif h.get("orphan_hits") == 0:
        lines.append("orphans                  0 in window (advisory; not a promote claim)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CanonicalStoreRegistry orphan / missing-cross-id census (read-only)",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--root", default=None, help="state root (default: production_state_root())")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"bounded window in days (default {DEFAULT_DAYS}; 0=unbounded)")
    ap.add_argument("--row-cap", type=int, default=DEFAULT_ROW_CAP,
                    help=f"max rows read per store (default {DEFAULT_ROW_CAP})")
    ap.add_argument("--out", default=None, help="optional path to write JSON (still prints)")
    args = ap.parse_args()

    report = census(
        root=args.root,
        days=args.days,
        row_cap=args.row_cap,
    )

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
