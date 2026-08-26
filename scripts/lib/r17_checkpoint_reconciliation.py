"""Classify existing checkpoint store. Does not delete historical evidence."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_institutional_learning import CHECKPOINT_PATH, _jsonl

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CheckpointReconciliation@v1"
CLASSES = ("VALID_UNIQUE", "SEMANTIC_DUPLICATE", "ORPHANED", "UNRESOLVED_SUBJECT", "LEGACY")


def _cash_like(row: dict[str, Any]) -> bool:
    ctx = row.get("context_receipt") or {}
    rec = str(ctx.get("recommendation") or row.get("decision_id") or "").upper()
    return "CASH" in rec or str(ctx.get("symbol") or "").upper() == "CASH" or str(row.get("entity_type") or "") == "PORTFOLIO_CASH"


def classify_row(row: dict[str, Any], *, seen_cash: dict[tuple[str, str], str]) -> str:
    if not row.get("auto_registered"):
        return "LEGACY"
    if not row.get("semantic_key"):
        return "ORPHANED"
    subject = row.get("subject_guid") or row.get("subject_id")
    if _cash_like(row):
        rec = str((row.get("context_receipt") or {}).get("recommendation") or "HOLD_CASH").upper()
        hz = str(row.get("horizon") or "")
        key = (rec, hz)
        if key in seen_cash and seen_cash[key] != row.get("semantic_key"):
            return "SEMANTIC_DUPLICATE"
        seen_cash[key] = str(row.get("semantic_key"))
        if not subject:
            return "UNRESOLVED_SUBJECT"
        return "VALID_UNIQUE"
    if not subject:
        return "UNRESOLVED_SUBJECT"
    return "VALID_UNIQUE"


def reconcile_store(root: Path | str) -> dict[str, Any]:
    rows = _jsonl(Path(root) / CHECKPOINT_PATH)
    seen_cash: dict[tuple[str, str], str] = {}
    classified = []
    counts = {c: 0 for c in CLASSES}
    cash_n = 0
    for row in rows:
        klass = classify_row(row, seen_cash=seen_cash)
        if _cash_like(row):
            cash_n += 1
        counts[klass] += 1
        classified.append({
            "checkpoint_id": row.get("checkpoint_id"),
            "decision_id": row.get("decision_id"),
            "horizon": row.get("horizon"),
            "class": klass,
            "semantic_key": row.get("semantic_key"),
            "subject_guid": row.get("subject_guid"),
            "auto": bool(row.get("auto_registered")),
        })
    cash_dupes = counts["SEMANTIC_DUPLICATE"]
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total": len(rows),
        "auto": sum(1 for r in rows if r.get("auto_registered")),
        "cash_n": cash_n,
        "counts": counts,
        "sample": classified[:40],
        "deleted": 0,
        "repair_plan": {
            "delete_historical": False,
            "governed": True,
            "recommended": (
                "Keep historical rows. Future binds use PORTFOLIO_CASH subject_id + "
                "notification material_generation_id. Optional later compact of cash "
                "SEMANTIC_DUPLICATE keeping earliest per (recommendation, horizon)."
            ),
            "cash_duplicates_n": cash_dupes,
        },
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def write_report(root: Path | str, report: dict[str, Any] | None = None) -> Path:
    report = report or reconcile_store(root)
    path = Path(root) / "data/audit/checkpoint_reconciliation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return path
