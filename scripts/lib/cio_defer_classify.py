"""Append-only classification / quarantine of defer lineage.

Does not delete history. Terminal records stop participation in due_defers
and production current/notification once latest-per-lineage is used.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_alex_telegram import _defer_path, iter_defer_lineage, latest_defer_by_lineage
from scripts.lib.cio_production_eligibility import (
    classify_advisory_record,
    quarantine_record,
)

AUTHORITY = "READ_ONLY_ADVISORY"


def inventory_defers(path: Optional[Path] = None) -> dict[str, Any]:
    if path:
        rows = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
        latest: dict[str, dict[str, Any]] = {}
        for rec in rows:
            key = str(rec.get("lineage_id") or rec.get("decision_id") or "")
            if key:
                latest[key] = rec
    else:
        rows = iter_defer_lineage()
        latest = latest_defer_by_lineage()

    counts: Counter[str] = Counter()
    items = []
    for rec in latest.values():
        v = classify_advisory_record(rec)
        counts[v["classification"]] += 1
        items.append({
            "lineage_id": rec.get("lineage_id"),
            "decision_id": rec.get("decision_id"),
            "status": rec.get("status"),
            "reason": rec.get("reason"),
            "classification": v["classification"],
            "eligible": v["eligible"],
        })
    return {
        "authority": AUTHORITY,
        "history_deleted": False,
        "row_count": len(rows),
        "lineage_count": len(latest),
        "counts": dict(counts),
        "items": items,
    }


def quarantine_non_production(*, path: Optional[Path] = None, dry_run: bool = True) -> dict[str, Any]:
    target = path or _defer_path()
    inv = inventory_defers(path=path)
    appended = []
    if dry_run:
        for it in inv["items"]:
            if it["classification"] in {"SYNTHETIC_E2E", "SYNTHETIC_TEST", "SHADOW", "LEGACY_UNPROVEN"}:
                appended.append(it)
        return {"ok": True, "dry_run": True, "would_quarantine": appended, "count": len(appended)}

    latest = latest_defer_by_lineage() if path is None else {
        str(i["lineage_id"] or i["decision_id"]): i for i in inv["items"]
    }
    # Re-read full latest records
    if path is not None:
        full = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                key = str(rec.get("lineage_id") or rec.get("decision_id") or "")
                if key:
                    full[key] = rec
        latest = full

    n = 0
    for rec in latest.values():
        v = classify_advisory_record(rec)
        if v["classification"] not in {"SYNTHETIC_E2E", "SYNTHETIC_TEST", "SHADOW", "LEGACY_UNPROVEN"}:
            continue
        if rec.get("quarantined"):
            continue
        q = quarantine_record(rec, classification=v["classification"],
                              reason="r610_non_prod_defer_excluded_from_current")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(q, default=str) + "\n")
        appended.append({"lineage_id": rec.get("lineage_id"), "decision_id": rec.get("decision_id"),
                         "classification": v["classification"]})
        n += 1
    return {"ok": True, "dry_run": False, "quarantined": appended, "count": n, "history_deleted": False}
