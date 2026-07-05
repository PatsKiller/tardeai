"""Operator/system feedback on discovery candidates + score-adjustment hook.

record_feedback() writes hermes_discovery_feedback and nudges per-source /
per-trend score deltas persisted to data/runtime/hermes_discovery_weights.json.
Deltas are CUMULATIVE and hard-bounded to ±MAX_ABS_DELTA (0.3) per key —
feedback tilts scoring, it can never dominate it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_weights.json"
WEIGHTS_VERSION = "discovery-weights-v1"

MAX_ABS_DELTA = 0.3

# feedback_type → per-event delta applied to the candidate's source/trend keys.
FEEDBACK_DELTAS: dict[str, float] = {
    "useful": +0.05,
    "approved": +0.05,
    "noise": -0.05,
    "rejected": -0.05,
    "blocked": -0.10,
    "note": 0.0,
}


def _clamp_delta(v: float) -> float:
    return max(-MAX_ABS_DELTA, min(MAX_ABS_DELTA, float(v)))


def load_weight_adjustments(path: Path | None = None) -> dict[str, Any]:
    """Read the persisted adjustment file; empty shell if missing/corrupt."""
    p = path or WEIGHTS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("source_deltas", {})
            data.setdefault("trend_deltas", {})
            return data
    except Exception:
        pass
    return {"version": WEIGHTS_VERSION, "updated_at": None,
            "source_deltas": {}, "trend_deltas": {}}


def _save_weight_adjustments(data: dict[str, Any], path: Path | None = None) -> Path:
    p = path or WEIGHTS_PATH
    data = dict(data)
    data["version"] = WEIGHTS_VERSION
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return p


def apply_weight_delta(*, source_domain: str | None = None,
                       trend_key: str | None = None,
                       delta: float,
                       path: Path | None = None) -> dict[str, Any]:
    """Accumulate a bounded delta for a source domain and/or trend key."""
    data = load_weight_adjustments(path)
    if source_domain:
        key = source_domain.lower().strip()
        cur = float(data["source_deltas"].get(key, 0.0))
        data["source_deltas"][key] = round(_clamp_delta(cur + delta), 6)
    if trend_key:
        key = trend_key.lower().strip()
        cur = float(data["trend_deltas"].get(key, 0.0))
        data["trend_deltas"][key] = round(_clamp_delta(cur + delta), 6)
    _save_weight_adjustments(data, path)
    return data


def record_feedback(candidate_id: int, feedback_type: str, *,
                    actor: str = "operator",
                    notes: str | None = None,
                    payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Persist one feedback event and apply its score adjustment.

    Returns the inserted feedback row (dict) or None if the DB is unavailable.
    Also appends a FEEDBACK audit entry on the candidate.
    """
    feedback_type = (feedback_type or "note").lower().strip()
    delta = FEEDBACK_DELTAS.get(feedback_type, 0.0)

    from db_adapter import _execute

    cand = _execute(
        "SELECT id, candidate_type, normalized_key, source_domain FROM hermes_discovery_candidates WHERE id = %s",
        (candidate_id,), fetch="one")

    row = _execute(
        """INSERT INTO hermes_discovery_feedback
               (candidate_id, feedback_type, actor, weight_delta, notes, payload_json)
           VALUES (%s, %s, %s, %s, %s, %s::jsonb)
           RETURNING *""",
        (candidate_id, feedback_type, actor, delta, notes,
         json.dumps(payload or {})), fetch="one")
    if row is None:
        return None

    # Score-adjustment hook: nudge this candidate's source domain and, for
    # trend candidates, its normalized trend key.
    if delta and cand:
        trend_key = (cand.get("normalized_key")
                     if cand.get("candidate_type") == "TREND_CANDIDATE" else None)
        try:
            apply_weight_delta(source_domain=cand.get("source_domain"),
                               trend_key=trend_key, delta=delta)
        except Exception as e:  # weights file trouble must not lose the feedback row
            print(f"  [hermes_discovery.feedback] weight adjustment skipped: {e}")

    _execute(
        """INSERT INTO hermes_discovery_audit (candidate_id, action, actor, before_json, after_json, notes)
           VALUES (%s, 'FEEDBACK', %s, NULL, %s::jsonb, %s)""",
        (candidate_id, actor,
         json.dumps({"feedback_type": feedback_type, "weight_delta": delta}, default=str),
         notes))
    return dict(row)
