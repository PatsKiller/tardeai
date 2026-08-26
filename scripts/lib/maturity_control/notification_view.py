"""Notification-gate + Telegram receipt mapping for /v3/cio."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.maturity_control.redaction import redact
from scripts.lib.maturity_control.store import resolve_root


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _latest_by(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = str(r.get(key) or r.get("decision_lineage_id") or "")
        if k:
            latest[k] = r
    return latest


def collect_notification_gate(*, root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    cio = base / "data" / "cio"
    states = _read_jsonl(cio / "cio_notification_state.jsonl")
    audits = _read_jsonl(cio / "cio_notification_audit.jsonl")
    metrics = _read_jsonl(cio / "cio_notification_metrics.jsonl")
    latest = _latest_by(states, "decision_lineage_id")
    lineages = []
    for lid, row in sorted(latest.items()):
        lineages.append({
            "decision_lineage_id": lid,
            "evidence_generation_id": row.get("evidence_generation_id"),
            "material_generation_id": row.get("material_generation_id"),
            "notification_class": row.get("notification_class"),
            "suppression_reason": row.get("suppressed_reason") or row.get("suppression_reason"),
            "operator_disposition": row.get("operator_disposition"),
            "last_evaluated": row.get("created_at") or row.get("evaluated_at"),
            "last_materially_changed": row.get("material_changed_at"),
            "last_delivered": row.get("last_delivered_at") or row.get("delivered_at"),
            "telegram_message_id": row.get("telegram_message_id") or row.get("message_id"),
            "scanner_run": row.get("scanner_run_id") or row.get("wake_id"),
            "dedupe_state": row.get("dedupe_key") or row.get("notification_id"),
            "current_action": row.get("current_action"),
            "standing_recommendation": row.get("standing_recommendation"),
            "act_now": row.get("act_now"),
        })
    return redact({
        "authority": "READ_ONLY_ADVISORY",
        "lineage_count": len(lineages),
        "audit_rows": len(audits),
        "metrics": metrics[-1] if metrics else {},
        "classes": ["IMMEDIATE", "DIGEST", "COMMAND_CENTER_ONLY", "SUPPRESSED"],
        "lineages": lineages,
    })
