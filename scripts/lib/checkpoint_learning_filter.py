"""Exclude bug-generated checkpoint duplicates from active learning.

Do NOT delete the rows. BUG_DUPLICATE / QUARANTINED / ORPHANED remain
auditable and cannot influence learning, calibration, cadence, or model
selection.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.r17_checkpoint_reconciliation import classify_row

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

EXCLUDED_FROM_LEARNING = frozenset({
    "BUG_DUPLICATE",
    "SEMANTIC_DUPLICATE",
    "QUARANTINED",
    "ORPHANED",
})

LEARNING_SURFACES = (
    "learning",
    "performance_calibration",
    "cadence_learning",
    "model_selection",
)


def learning_class(row: dict[str, Any], *, seen_cash: dict | None = None) -> str:
    seen = seen_cash if seen_cash is not None else {}
    klass = classify_row(row, seen_cash=seen)
    if klass == "SEMANTIC_DUPLICATE":
        return "BUG_DUPLICATE"
    if row.get("quarantined") or row.get("class") == "QUARANTINED":
        return "QUARANTINED"
    return klass


def eligible_for_learning(row: dict[str, Any], *, seen_cash: dict | None = None) -> bool:
    return learning_class(row, seen_cash=seen_cash) not in EXCLUDED_FROM_LEARNING


def filter_learning_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seen: dict = {}
    kept = []
    excluded = []
    for row in rows:
        klass = learning_class(row, seen_cash=seen)
        rec = {**row, "learning_class": klass, "learning_eligible": klass not in EXCLUDED_FROM_LEARNING}
        if rec["learning_eligible"]:
            kept.append(rec)
        else:
            excluded.append({
                "checkpoint_id": row.get("checkpoint_id"),
                "learning_class": klass,
                "retained_for_audit": True,
                "deleted": False,
            })
    return {
        "schema": "CheckpointLearningFilter@v1",
        "input_n": len(rows),
        "eligible_n": len(kept),
        "excluded_n": len(excluded),
        "active_learning_influence_from_duplicates": 0,
        "excluded_sample": excluded[:20],
        "rows": kept,
        "surfaces_blocked": list(LEARNING_SURFACES),
        "deleted": 0,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
