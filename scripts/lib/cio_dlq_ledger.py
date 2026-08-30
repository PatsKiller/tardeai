"""CIO lifecycle DLQ ledger helpers (G-LOOP-01 / P9 phases C–D).

APPEND_ONLY_EVIDENCE only. Never mutates lineage / hub jsonl stores.
never_auto_remediate store_consistency. No silent identity merge.

AUTHORITY: READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import append_jsonl
from scripts.lib.canonical_store_registry import AUTHORITY, MBI

SCHEMA = "CIOLifecycleDLQ@v1"
DEFAULT_LEDGER_REL = Path("data/cio/lifecycle_dlq.jsonl")
APPLY_ENV = "TRADEAI_DLQ_APPLY"

# Reason codes per P9 §6.3 phase C.
REASON_MISSING_EVENT_ID = "MISSING_EVENT_ID"
REASON_NULL_WORKFLOW_ID = "NULL_WORKFLOW_ID"
REASON_MISSING_WORKFLOW_ID = "MISSING_WORKFLOW_ID"
REASON_UNKNOWN_WORKFLOW_ID = "UNKNOWN_WORKFLOW_ID"
REASON_UNKNOWN_CHECKPOINT_ID = "UNKNOWN_CHECKPOINT_ID"
REASON_UNKNOWN_NOTIFICATION_ID = "UNKNOWN_NOTIFICATION_ID"
REASON_MISSING_CROSS_ID = "MISSING_CROSS_ID"
REASON_ORPHAN_EDGE = "ORPHAN_EDGE"

KIND_ENQUEUE = "enqueue"
KIND_REPLAY_PLAN = "replay_plan"
KIND_APPLY_RECEIPT = "apply_receipt"


def apply_env_armed() -> bool:
    """True only when TRADEAI_DLQ_APPLY=1 (exact)."""
    return os.environ.get(APPLY_ENV, "").strip() == "1"


def ledger_path(root: Path | str, override: Path | str | None = None) -> Path:
    if override is not None:
        return Path(override)
    return Path(root) / DEFAULT_LEDGER_REL


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def finding_id(payload: dict[str, Any]) -> str:
    """Stable content-addressed id for dedupe / receipts."""
    key = "|".join(
        [
            str(payload.get("class") or ""),
            str(payload.get("reason_code") or ""),
            str(payload.get("store_id") or ""),
            str(payload.get("field") or ""),
            str(payload.get("value") or ""),
            str(sorted((payload.get("row_keys") or {}).items())),
        ]
    )
    return "dlq_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def reason_for_missing(store_id: str, field: str) -> str:
    if field == "event_id":
        return REASON_MISSING_EVENT_ID
    if field == "workflow_id":
        if store_id == "cio.specialist_artifacts":
            return REASON_NULL_WORKFLOW_ID
        return REASON_MISSING_WORKFLOW_ID
    return REASON_MISSING_CROSS_ID


def reason_for_orphan(sample: dict[str, Any]) -> str:
    if sample.get("class") == "null_hub_id" or sample.get("value") is None:
        if sample.get("field") == "workflow_id":
            return REASON_NULL_WORKFLOW_ID
    ref = sample.get("ref_key") or sample.get("field") or ""
    if ref == "notification_id" or sample.get("field") == "notification_id":
        return REASON_UNKNOWN_NOTIFICATION_ID
    if ref == "workflow_id" or sample.get("field") == "workflow_id":
        return REASON_UNKNOWN_WORKFLOW_ID
    if ref == "checkpoint_id" or sample.get("field") == "checkpoint_id":
        return REASON_UNKNOWN_CHECKPOINT_ID
    return REASON_ORPHAN_EDGE


def findings_from_census(census: dict[str, Any]) -> list[dict[str, Any]]:
    """Map orphan census missing_cross_ids + orphans into DLQ finding rows."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for sample in (census.get("missing_cross_ids") or {}).get("samples") or []:
        store_id = str(sample.get("store_id") or "")
        field = str(sample.get("field") or "")
        row = {
            "class": "missing_cross_id",
            "reason_code": reason_for_missing(store_id, field),
            "store_id": store_id,
            "field": field,
            "value": None,
            "row_keys": dict(sample.get("row_keys") or {}),
            "source": "cio_registry_orphan_census",
        }
        fid = finding_id(row)
        if fid in seen:
            continue
        seen.add(fid)
        row["finding_id"] = fid
        out.append(row)

    for sample in (census.get("orphans") or {}).get("samples") or []:
        row = {
            "class": sample.get("class") or "orphan_edge",
            "reason_code": reason_for_orphan(sample),
            "store_id": str(sample.get("store_id") or ""),
            "field": str(sample.get("field") or ""),
            "value": sample.get("value"),
            "ref_key": sample.get("ref_key"),
            "row_keys": dict(sample.get("row_keys") or {}),
            "source": "cio_registry_orphan_census",
        }
        fid = finding_id(row)
        if fid in seen:
            continue
        seen.add(fid)
        row["finding_id"] = fid
        out.append(row)

    return out


def plan_replay_actions(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build dry-run replay plans. Advisory only — never mutates stores."""
    plans: list[dict[str, Any]] = []
    for f in findings:
        reason = f.get("reason_code")
        action: str
        notes: str
        if reason == REASON_MISSING_EVENT_ID:
            action = "PLAN_STAMP_EVENT_ID_ON_NEW_WRITE"
            notes = (
                "Would stamp event_id on future lineage writes; "
                "does NOT rewrite historical workflow_lineage rows."
            )
        elif reason in {REASON_NULL_WORKFLOW_ID, REASON_MISSING_WORKFLOW_ID}:
            action = "PLAN_LINK_WORKFLOW_OR_QUARANTINE"
            notes = (
                "Would link satellite to authoritative workflow_id or keep quarantined; "
                "no silent identity merge."
            )
        elif reason == REASON_UNKNOWN_NOTIFICATION_ID:
            action = "PLAN_RECONCILE_NOTIFICATION_OR_QUARANTINE"
            notes = "Would reconcile receipt to hub notification_id or keep in DLQ."
        elif reason == REASON_UNKNOWN_WORKFLOW_ID:
            action = "PLAN_RECONCILE_WORKFLOW_OR_QUARANTINE"
            notes = "Would reconcile FK to hub workflow_id or keep in DLQ."
        elif reason == REASON_UNKNOWN_CHECKPOINT_ID:
            action = "PLAN_RECONCILE_CHECKPOINT_OR_QUARANTINE"
            notes = "Would reconcile FK to hub checkpoint_id or keep in DLQ."
        else:
            action = "PLAN_OPERATOR_REVIEW"
            notes = "Unclassified finding; operator review required."
        plans.append({
            "schema": SCHEMA,
            "kind": KIND_REPLAY_PLAN,
            "finding_id": f.get("finding_id"),
            "reason_code": reason,
            "action": action,
            "notes": notes,
            "mutates_historical_stores": False,
            "store_id": f.get("store_id"),
            "field": f.get("field"),
            "value": f.get("value"),
            "row_keys": f.get("row_keys") or {},
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "never_auto_remediate": True,
        })
    return plans


def make_enqueue_record(
    finding: dict[str, Any],
    *,
    census_days: int,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "kind": KIND_ENQUEUE,
        "recorded_at": _utcnow(),
        "run_id": run_id,
        "census_days": census_days,
        "finding_id": finding.get("finding_id"),
        "class": finding.get("class"),
        "reason_code": finding.get("reason_code"),
        "store_id": finding.get("store_id"),
        "field": finding.get("field"),
        "value": finding.get("value"),
        "ref_key": finding.get("ref_key"),
        "row_keys": finding.get("row_keys") or {},
        "source": finding.get("source") or "cio_registry_orphan_census",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "never_auto_remediate": True,
        "mutates_historical_stores": False,
    }


def make_replay_plan_record(
    plan: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    rec = dict(plan)
    rec["schema"] = SCHEMA
    rec["kind"] = KIND_REPLAY_PLAN
    rec["recorded_at"] = _utcnow()
    rec["run_id"] = run_id
    rec["authority"] = AUTHORITY
    rec["memory_behavior_influence"] = MBI
    rec["financial_action"] = False
    rec["never_auto_remediate"] = True
    rec["mutates_historical_stores"] = False
    return rec


def make_apply_receipt(
    plans: list[dict[str, Any]],
    *,
    run_id: str,
    census_days: int,
) -> dict[str, Any]:
    """Operator-gated apply receipt. Append-only; does not rewrite hubs."""
    return {
        "schema": SCHEMA,
        "kind": KIND_APPLY_RECEIPT,
        "recorded_at": _utcnow(),
        "run_id": run_id,
        "census_days": census_days,
        "apply_env": APPLY_ENV,
        "apply_armed": True,
        "planned_action_count": len(plans),
        "planned_finding_ids": [p.get("finding_id") for p in plans],
        "actions": [p.get("action") for p in plans],
        "mutates_historical_stores": False,
        "rewrote_lineage": False,
        "rewrote_hubs": False,
        "note": (
            "Apply path appends this receipt only. Historical lineage/jsonl hubs "
            "are not mutated. Store consistency remediation remains operator-authorized."
        ),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "never_auto_remediate": True,
    }


def append_ledger_records(path: Path, records: list[dict[str, Any]]) -> int:
    """Append records to the DLQ ledger. Creates parent dirs. Returns count."""
    n = 0
    for rec in records:
        append_jsonl(path, rec)
        n += 1
    return n


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    import json

                    obj = json.loads(line)
                except Exception:  # noqa: BLE001 — fail-soft
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        return []
    return out
