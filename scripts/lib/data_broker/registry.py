"""Data Broker registry loader + coverage/duplication checks.

Reads config/data_registry.yaml (the single catalog of data types, their canonical
producer/store, and every known consumer) and exposes:

  - load_registry()   -- cached parse of the YAML file
  - list_data_types() -- data types as a list with `id` injected
  - get_matrix()      -- the consumers section (pages / alerts / pipeline_scripts)
  - check_coverage()  -- duplication report: which `deprecated_producers` files still
                         exist in the repo (i.e. migration not yet done), plus referential
                         integrity checks (matrix rows referencing unknown data types,
                         data types with zero consumers).

This mirrors the existing scripts/lib/data_source_report.py pattern: fail soft, cheap to
call from an HTTP handler, safe to run standalone for CI (like the frontend design-token
guard). It intentionally does NOT touch the database — the registry itself is a static
config file; live freshness is composed separately by callers via data_source_health.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_registry.yaml"

_cache: dict[str, Any] = {"mtime": None, "data": None}


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load + cache config/data_registry.yaml. Re-parses only if the file changed."""
    p = path or REGISTRY_PATH
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {"version": None, "data_types": {}, "consumers": {}}

    if _cache["data"] is not None and _cache["mtime"] == mtime and path is None:
        return _cache["data"]

    import yaml
    with open(p, "r") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("data_types", {})
    data.setdefault("consumers", {})
    if path is None:
        _cache["mtime"] = mtime
        _cache["data"] = data
    return data


def list_data_types(registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Data types as a flat list, each with its registry key injected as `id`."""
    reg = registry or load_registry()
    out = []
    for key, entry in (reg.get("data_types") or {}).items():
        row = dict(entry or {})
        row["id"] = key
        out.append(row)
    out.sort(key=lambda r: (r.get("domain") or "", r.get("id") or ""))
    return out


def get_data_type(data_type_id: str, registry: dict[str, Any] | None = None) -> dict[str, Any] | None:
    reg = registry or load_registry()
    entry = (reg.get("data_types") or {}).get(data_type_id)
    if entry is None:
        return None
    row = dict(entry)
    row["id"] = data_type_id
    return row


def get_matrix(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    reg = registry or load_registry()
    return reg.get("consumers") or {"pages": [], "alerts": [], "pipeline_scripts": []}


def _extract_path_candidate(producer_ref: str) -> str | None:
    """Pull a checkable repo-relative file path out of a free-text producer/deprecated string.

    Entries look like "scripts/foo.py:func_name", "scripts/foo.py", or plain prose notes
    like "Finviz $ATR field (context only)" -- only the first two are checkable.
    """
    ref = producer_ref.split(":", 1)[0].strip()
    if ref.endswith(".py") and "/" in ref and " " not in ref:
        return ref
    m = re.match(r"^([\w./-]+\.py)\b", producer_ref.strip())
    if m:
        return m.group(1)
    return None


def check_coverage(registry: dict[str, Any] | None = None, project_root: Path | None = None) -> dict[str, Any]:
    """Duplication + referential-integrity report.

    Returns:
      duplication: [{data_type, producer_path, exists, note}] for every deprecated_producers
                    entry that resolves to a file path -- `exists: true` means that ad-hoc
                    producer is STILL in the repo and has not yet been migrated to the
                    canonical producer/store.
      orphan_data_types: data_type ids with zero entries anywhere in the consumers matrix.
      dangling_consumer_refs: consumer rows (page/alert/script) whose `data_type` key does
                    not exist in data_types -- signals the matrix drifted from the catalog.
      counts: summary counts for the Data Management page header.
    """
    root = project_root or PROJECT_ROOT
    reg = registry or load_registry()
    data_types = reg.get("data_types") or {}
    matrix = reg.get("consumers") or {}

    duplication: list[dict[str, Any]] = []
    for dt_id, entry in data_types.items():
        for producer_ref in (entry or {}).get("deprecated_producers") or []:
            path = _extract_path_candidate(producer_ref)
            if not path:
                duplication.append({
                    "data_type": dt_id, "producer_path": None, "raw": producer_ref,
                    "exists": None, "note": "not a checkable file path (prose note)",
                })
                continue
            exists = (root / path).exists()
            duplication.append({
                "data_type": dt_id, "producer_path": path, "raw": producer_ref,
                "exists": exists,
                "note": "still present -- migration pending" if exists else "no longer present -- looks migrated",
            })

    referenced_types: set[str] = set()
    dangling_consumer_refs: list[dict[str, Any]] = []
    for group_name in ("pages", "alerts", "pipeline_scripts"):
        for row in matrix.get(group_name) or []:
            label = row.get("page") or row.get("alert") or row.get("script") or "?"
            for read in row.get("reads") or []:
                dt = read.get("data_type")
                if dt is None:
                    continue
                referenced_types.add(dt)
                if dt not in data_types:
                    dangling_consumer_refs.append({"group": group_name, "consumer": label, "data_type": dt})

    orphan_data_types = sorted(set(data_types.keys()) - referenced_types)

    pending_migrations = sum(1 for d in duplication if d["exists"] is True)
    migrated = sum(1 for d in duplication if d["exists"] is False)

    return {
        "checked_at": time.time(),
        "duplication": duplication,
        "orphan_data_types": orphan_data_types,
        "dangling_consumer_refs": dangling_consumer_refs,
        "counts": {
            "data_types": len(data_types),
            "deprecated_producer_entries": len(duplication),
            "pending_migrations": pending_migrations,
            "migrated": migrated,
            "orphan_data_types": len(orphan_data_types),
            "dangling_consumer_refs": len(dangling_consumer_refs),
        },
    }


def registry_summary(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    reg = registry or load_registry()
    data_types = reg.get("data_types") or {}
    by_domain: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for entry in data_types.values():
        by_domain[entry.get("domain", "unknown")] = by_domain.get(entry.get("domain", "unknown"), 0) + 1
        by_status[entry.get("status", "unknown")] = by_status.get(entry.get("status", "unknown"), 0) + 1
    matrix = reg.get("consumers") or {}
    return {
        "version": reg.get("version"),
        "audit_doc": reg.get("audit_doc"),
        "data_type_count": len(data_types),
        "by_domain": by_domain,
        "by_status": by_status,
        "page_count": len(matrix.get("pages") or []),
        "alert_count": len(matrix.get("alerts") or []),
        "pipeline_script_count": len(matrix.get("pipeline_scripts") or []),
    }


def _cli() -> int:
    """Standalone entry point: prints a coverage report, exits non-zero only with --strict
    and dangling refs found (broken registry), matching the design-token-guard convention.
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Data broker registry coverage check")
    parser.add_argument("--strict", action="store_true",
                         help="exit 1 if dangling consumer refs are found (broken registry)")
    parser.add_argument("--json", action="store_true", help="print raw JSON report")
    args = parser.parse_args()

    report = check_coverage()
    if args.json:
        print(_json.dumps(report, indent=2, default=str))
    else:
        c = report["counts"]
        print(f"Data Broker coverage report -- {c['data_types']} data types")
        print(f"  pending migrations (deprecated producer still present): {c['pending_migrations']}")
        print(f"  migrated (deprecated producer removed):                 {c['migrated']}")
        print(f"  orphan data types (no consumer listed):                 {c['orphan_data_types']}")
        print(f"  dangling consumer refs (unknown data_type):             {c['dangling_consumer_refs']}")
        if report["orphan_data_types"]:
            print("\nOrphans:", ", ".join(report["orphan_data_types"]))
        if report["dangling_consumer_refs"]:
            print("\nDangling refs:")
            for d in report["dangling_consumer_refs"]:
                print(f"  {d['group']}/{d['consumer']} -> unknown data_type '{d['data_type']}'")

    if args.strict and report["counts"]["dangling_consumer_refs"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
