"""Persistence for closed-loop evaluations (Phase D)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CLOSED_LOOP_EVAL_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_closed_loop_evaluations.json"
CLOSED_LOOP_EVAL_AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_closed_loop_eval_audit.jsonl"


def load_closed_loop_evaluations() -> dict[str, Any]:
    if not CLOSED_LOOP_EVAL_PATH.exists():
        return {"version": "closed-loop-eval-v1", "evaluations": [], "summary": {}}
    try:
        return json.loads(CLOSED_LOOP_EVAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "closed-loop-eval-v1", "evaluations": [], "summary": {}}


def save_closed_loop_evaluations(payload: dict[str, Any]) -> Path:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    CLOSED_LOOP_EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CLOSED_LOOP_EVAL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(CLOSED_LOOP_EVAL_PATH)
    return CLOSED_LOOP_EVAL_PATH


def append_closed_loop_eval_audit(event: dict[str, Any]) -> None:
    CLOSED_LOOP_EVAL_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), **event}
    with CLOSED_LOOP_EVAL_AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def new_closed_loop_evaluation_id() -> str:
    return f"cle_{uuid.uuid4().hex[:10]}"