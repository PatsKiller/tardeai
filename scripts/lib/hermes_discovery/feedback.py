"""Operator/system feedback on discovery candidates + score-adjustment hook.

record_feedback() writes hermes_discovery_feedback and nudges per-source /
per-trend score deltas persisted to data/runtime/hermes_discovery_weights.json
under the persistent state root. The checkout copy is a seed, never a write target.
Deltas are CUMULATIVE and hard-bounded to ±MAX_ABS_DELTA (0.3) per key —
feedback tilts scoring, it can never dominate it.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CHECKOUT_WEIGHTS = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_weights.json"
# Kept for callers that import the checkout path. Live reads and writes use weights_path().
WEIGHTS_PATH = _CHECKOUT_WEIGHTS
WEIGHTS_VERSION = "discovery-weights-v1"


def _under_test() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CIO_TEST_ISOLATION")
                or os.environ.get("TRADE_AI_CI") == "1")


def resolve_weights_path(*, under_test: bool, state_root: Path, checkout: Path) -> Path:
    if under_test:
        return checkout
    return state_root / "data" / "runtime" / "hermes_discovery_weights.json"


def weights_path() -> Path:
    """Where discovery weights are read and written. Tests and CI stay on the checkout path."""
    if _under_test():
        return _CHECKOUT_WEIGHTS
    from ...persistent_state_root import good_persistent_root
    return resolve_weights_path(under_test=False, state_root=good_persistent_root(), checkout=_CHECKOUT_WEIGHTS)

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


def _empty_weights() -> dict[str, Any]:
    return {"version": WEIGHTS_VERSION, "updated_at": None,
            "source_deltas": {}, "trend_deltas": {}}


def _parse_weights(p: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict):
        data.setdefault("source_deltas", {})
        data.setdefault("trend_deltas", {})
        return data
    return None


def load_weight_adjustments(path: Path | None = None) -> dict[str, Any]:
    """Read the persisted adjustment file; empty shell if missing/corrupt.

    A missing state file is seeded from the checkout copy. The seed is not written back."""
    p = path or weights_path()
    if p.is_file():
        return _parse_weights(p) or _empty_weights()
    if path is None and p != _CHECKOUT_WEIGHTS and _CHECKOUT_WEIGHTS.is_file():
        return _parse_weights(_CHECKOUT_WEIGHTS) or _empty_weights()
    return _empty_weights()


def _save_weight_adjustments(data: dict[str, Any], path: Path | None = None) -> Path:
    p = path or weights_path()
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
