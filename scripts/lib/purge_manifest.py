"""Purge candidate list. Does not delete anything."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.lib.checkpoint_learning_filter import learning_class
from scripts.lib.r17_checkpoint_reconciliation import reconcile_store

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def _hash(row: dict[str, Any]) -> str:
    blob = json.dumps(row, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build(*, root: Path | str) -> dict[str, Any]:
    rec = reconcile_store(root)
    candidates = []
    seen: dict = {}
    store = Path(root) / "data/cio/outcome_checkpoints.jsonl"
    rows = []
    if store.is_file():
        for line in store.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for row in rows:
        klass = learning_class(row, seen_cash=seen)
        if klass not in {"BUG_DUPLICATE", "SEMANTIC_DUPLICATE", "ORPHANED", "QUARANTINED"}:
            continue
        candidates.append({
            "record_path": "data/cio/outcome_checkpoints.jsonl",
            "checkpoint_id": row.get("checkpoint_id"),
            "classification": klass if klass != "SEMANTIC_DUPLICATE" else "BUG_DUPLICATE",
            "content_hash": _hash(row),
            "reason": "bug-generated semantic duplicate or orphan; excluded from learning",
            "replacement_source_of_truth": "earliest VALID_UNIQUE row for the same semantic key",
            "safe_to_delete": False,
            "rebuildable": False,
            "audit_retained": True,
        })
    return {
        "schema": "PurgeManifest@v1",
        "candidates": candidates,
        "candidate_n": len(candidates),
        "checkpoint_reconciliation": rec.get("counts"),
        "backup_complete": False,
        "quarantine_ready": True,
        "destructive_applied": False,
        "approval_required": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "note": "SNAPSHOT→INVENTORY→CLASSIFY→QUARANTINE→REBUILD. No delete in this tranche.",
    }
