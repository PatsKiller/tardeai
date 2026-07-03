"""Persistence for threshold change evaluations (Phase 2)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVALUATIONS_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_threshold_evaluations.json"
EVAL_AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_threshold_eval_audit.jsonl"


def load_evaluations() -> dict[str, Any]:
    if not EVALUATIONS_PATH.exists():
        return {"version": "evaluations-v1", "evaluations": [], "summary": {}}
    try:
        return json.loads(EVALUATIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "evaluations-v1", "evaluations": [], "summary": {}}


def save_evaluations(payload: dict[str, Any]) -> Path:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    EVALUATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EVALUATIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(EVALUATIONS_PATH)
    return EVALUATIONS_PATH


def append_eval_audit(event: dict[str, Any]) -> None:
    EVAL_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), **event}
    with EVAL_AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def new_evaluation_id() -> str:
    return f"te_{uuid.uuid4().hex[:10]}"