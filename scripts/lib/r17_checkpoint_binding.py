"""R17 — bind natural MATERIAL decisions to observational checkpoints.

Uses existing OutcomeCheckpoint@v1 / process_due_checkpoint. Does not create a
second scheduler or invent elapsed time. Unchanged replay must not spam.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_institutional_learning import (
    AUTHORITY,
    CHECKPOINT_PATH,
    HORIZONS,
    MBI,
    OBSERVATION_PATH,
    identity_safe_subject,
    persist_checkpoint,
    persist_observation,
    process_due_checkpoint,
    schedule_outcome_checkpoint,
    _jsonl,
    _sha,
)

SCHEMA_BIND = "CheckpointBinding@v1"
SCHEMA_COCKPIT = "LearningCockpit@v1"
DEFAULT_HORIZONS = ("1_session", "5_sessions", "event-relative")
HORIZON_OFFSET = {
    "1_session": timedelta(days=1),
    "5_sessions": timedelta(days=5),
    "20_sessions": timedelta(days=20),
    "quarterly": timedelta(days=90),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.isoformat()


PORTFOLIO_CASH_ENTITY = "PORTFOLIO_CASH"
CASH_ACTIONS = {"HOLD_CASH", "DEPLOY_CASH", "RAISE_CASH", "WAIT_CASH"}


def is_cash_decision(decision: dict[str, Any]) -> bool:
    sym = str(decision.get("symbol") or "").upper()
    action = str(decision.get("action") or decision.get("recommendation") or decision.get("stance") or "").upper()
    if sym == "CASH" or action in CASH_ACTIONS:
        return True
    if str(decision.get("entity_type") or "").upper() == PORTFOLIO_CASH_ENTITY:
        return True
    return False


def canonical_checkpoint_subject(decision: dict[str, Any]) -> dict[str, Any]:
    """Stable subject for checkpoint identity. Never mints a security_guid.

    Cash is portfolio-level: PORTFOLIO_CASH + account/policy scope.
    Securities use identity_safe_subject only when a real security_guid exists.
    """
    from scripts.lib.cio_notification_signal import LINEAGE_CASH, decision_lineage_id

    if is_cash_decision(decision):
        scope = (
            decision.get("account_id")
            or decision.get("account")
            or decision.get("portfolio_scope")
            or "CONSOLIDATED"
        )
        subject_id = f"{PORTFOLIO_CASH_ENTITY}:{scope}"
        return {
            "entity_type": PORTFOLIO_CASH_ENTITY,
            "subject_id": subject_id,
            "subject_guid": None,
            "ticker_guid_is_not_security": True,
            "lineage_id": LINEAGE_CASH,
            "scope": str(scope),
            "never_minted_security_guid": True,
        }
    guid = identity_safe_subject(decision)
    lineage = decision_lineage_id(decision)
    return {
        "entity_type": "SECURITY" if guid else "UNRESOLVED",
        "subject_id": guid or f"UNRESOLVED:{lineage}",
        "subject_guid": guid,
        "ticker_guid_is_not_security": not bool(guid),
        "lineage_id": lineage,
        "never_minted_security_guid": True,
    }


def checkpoint_material_generation(decision: dict[str, Any]) -> str:
    """Operator-meaning generation. Must match notification unchanged_replay.

    Cash must NOT hash rotating evidence digests, USD jitter, or decision_id.
    """
    from scripts.lib.cio_notification_signal import material_generation_id

    explicit = decision.get("material_generation") or decision.get("material_generation_id")
    if explicit:
        return str(explicit)
    # Align with the notification layer that already stayed stable overnight.
    return material_generation_id(decision)


def semantic_checkpoint_key(decision: dict[str, Any], horizon: str) -> str:
    """Identity for dedupe. Ignores technical decision_id churn."""
    subject = canonical_checkpoint_subject(decision)
    payload = {
        "entity_type": subject["entity_type"],
        "subject_id": subject["subject_id"],
        "recommendation": str(
            decision.get("recommendation")
            or decision.get("action")
            or decision.get("stance")
            or ""
        ).upper(),
        "material_generation": checkpoint_material_generation(decision),
        "thesis_version": str(decision.get("thesis_version") or decision.get("symbol_thesis_version") or ""),
        "curation_version": str(decision.get("curation_version") or ""),
        "horizon": horizon,
        "policy_version": str(decision.get("policy_version") or (decision.get("cash_posture") or {}).get("policy_version") or ""),
    }
    # Do not include decision_id, evidence digest, timestamps, or raw USD.
    return _sha(payload)[:24]


def due_at_for(horizon: str, *, now: datetime | None = None) -> str | None:
    now = now or _now()
    delta = HORIZON_OFFSET.get(horizon)
    if not delta:
        return None
    return _iso(now + delta)


def enrich_checkpoint(
    decision: dict[str, Any],
    horizon: str,
    *,
    source_sha: str,
    now: datetime | None = None,
    existing_ids: list[str] | None = None,
) -> dict[str, Any]:
    now = now or _now()
    ck = schedule_outcome_checkpoint(str(decision.get("decision_id") or ""), horizon, existing=existing_ids)
    semantic = semantic_checkpoint_key(decision, horizon)
    subject = canonical_checkpoint_subject(decision)
    material_gen = checkpoint_material_generation(decision)
    ck.update({
        "subject_guid": subject.get("subject_guid"),
        "entity_type": subject.get("entity_type"),
        "subject_id": subject.get("subject_id"),
        "lineage_id": subject.get("lineage_id"),
        "decision_generation": material_gen,
        "semantic_key": semantic,
        "due_at": due_at_for(horizon, now=now),
        "runtime_source_sha": source_sha,
        "context_receipt": {
            "symbol": decision.get("symbol"),
            "recommendation": decision.get("recommendation") or decision.get("action"),
            "thesis_version": decision.get("thesis_version") or decision.get("symbol_thesis_version"),
            "curation_version": decision.get("curation_version"),
            "material_generation": material_gen,
            "producer_id": decision.get("producer_id") or "material_scan",
            "entity_type": subject.get("entity_type"),
            "subject_id": subject.get("subject_id"),
        },
        "original_decision_state": {
            "as_of": _iso(now),
            "recommendation": decision.get("recommendation") or decision.get("action"),
            "symbol": decision.get("symbol"),
            "notification_disposition": decision.get("notification_class"),
        },
        "observational_only": True,
        "trading": False,
        "auto_registered": True,
        "created_at": _iso(now),
    })
    # Stable checkpoint_id from semantic key + horizon so replay IDs don't fork rows.
    ck["checkpoint_id"] = _sha({"semantic_key": semantic, "horizon": horizon})[:20]
    return ck


def bind_material_decision(
    root: Path | str,
    decision: dict[str, Any],
    *,
    source_sha: str,
    persist: bool = True,
    horizons: tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """MATERIAL decision → observational checkpoints. Semantic dedupe, not decision_id."""
    now = now or _now()
    root_p = Path(root)
    existing = _jsonl(root_p / CHECKPOINT_PATH)
    by_semantic = {str(r.get("semantic_key")): r for r in existing if r.get("semantic_key")}
    wrote, skipped = [], []
    for hz in horizons or DEFAULT_HORIZONS:
        if hz not in HORIZONS:
            continue
        ck = enrich_checkpoint(decision, hz, source_sha=source_sha, now=now)
        prior = by_semantic.get(ck["semantic_key"])
        if prior and prior.get("status") in {None, "SCHEDULED", "PENDING"}:
            skipped.append({"horizon": hz, "reason": "semantic_duplicate", "checkpoint_id": prior.get("checkpoint_id")})
            continue
        if persist:
            result = persist_checkpoint(root_p, ck)
            if result.get("duplicate"):
                skipped.append({"horizon": hz, "reason": "checkpoint_id_duplicate", "checkpoint_id": ck["checkpoint_id"]})
                continue
        wrote.append(ck)
        by_semantic[ck["semantic_key"]] = ck
    return {
        "schema": SCHEMA_BIND,
        "decision_id": decision.get("decision_id"),
        "wrote_n": len(wrote),
        "skipped_n": len(skipped),
        "wrote": [{"checkpoint_id": c["checkpoint_id"], "horizon": c["horizon"], "due_at": c.get("due_at")} for c in wrote],
        "skipped": skipped,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "trading": False,
    }


def bind_scan_decisions(
    root: Path | str,
    decisions: list[dict[str, Any]],
    *,
    source_sha: str,
    persist: bool = True,
) -> dict[str, Any]:
    bindings = [bind_material_decision(root, d, source_sha=source_sha, persist=persist) for d in decisions]
    return {
        "schema": "ScanCheckpointBinding@v1",
        "n": len(decisions),
        "wrote_n": sum(b["wrote_n"] for b in bindings),
        "skipped_n": sum(b["skipped_n"] for b in bindings),
        "bindings": bindings,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def _parse_due(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def classify_checkpoint(row: dict[str, Any], *, now: datetime | None = None) -> str:
    now = now or _now()
    status = str(row.get("status") or "SCHEDULED").upper()
    if status in {"COMPLETE", "OBSERVED"} or row.get("outcome_id"):
        return "COMPLETE"
    if status in {"FAILED"}:
        return "FAILED"
    due = _parse_due(row.get("due_at"))
    if due and due <= now:
        return "DUE"
    if status in {"BLOCKED_DATA", "OUTCOME_PENDING_DATA"}:
        return "BLOCKED_DATA"
    return "PENDING"


def process_due_store(
    root: Path | str,
    *,
    source_available: bool,
    realized_state: dict[str, Any] | None = None,
    source_refs: list[str] | None = None,
    persist: bool = True,
    now: datetime | None = None,
    event_occurred: bool = False,
) -> dict[str, Any]:
    """Observational due processor over durable jsonl. No trading. No fabricated time."""
    now = now or _now()
    root_p = Path(root)
    results = []
    for ck in _jsonl(root_p / CHECKPOINT_PATH):
        klass = classify_checkpoint(ck, now=now)
        due = _parse_due(ck.get("due_at"))
        if due and due > now:
            results.append({"checkpoint_id": ck.get("checkpoint_id"), "status": "NO_ACTION", "reason": "not_due"})
            continue
        if ck.get("horizon") == "event-relative" and not event_occurred and not due:
            results.append({"checkpoint_id": ck.get("checkpoint_id"), "status": "NO_ACTION", "reason": "event_not_occurred"})
            continue
        if klass == "COMPLETE":
            results.append({"checkpoint_id": ck.get("checkpoint_id"), "status": "NO_ACTION", "reason": "already_complete"})
            continue
        if klass not in {"DUE", "PENDING"} and due is None and not event_occurred:
            results.append({"checkpoint_id": ck.get("checkpoint_id"), "status": "NO_ACTION", "reason": "not_due"})
            continue
        if not source_available:
            out = process_due_checkpoint(checkpoint=ck, source_available=False)
            results.append({"checkpoint_id": ck.get("checkpoint_id"), **out})
            continue
        if due is None and not event_occurred:
            results.append({"checkpoint_id": ck.get("checkpoint_id"), "status": "NO_ACTION", "reason": "not_due"})
            continue
        if due and due > now:
            results.append({"checkpoint_id": ck.get("checkpoint_id"), "status": "NO_ACTION", "reason": "not_due"})
            continue
        out = process_due_checkpoint(
            checkpoint=ck,
            source_available=True,
            realized_state=realized_state or {"linked": True},
            source_refs=source_refs or ["due_processor"],
            source_as_of=_iso(now),
        )
        if persist and out.get("observation"):
            persist_observation(root_p, out["observation"])
        results.append({"checkpoint_id": ck.get("checkpoint_id"), **out})
    return {
        "schema": "DueStoreProcessor@v1",
        "n": len(results),
        "observed": sum(1 for r in results if r.get("status") == "OBSERVED"),
        "pending_data": sum(1 for r in results if r.get("status") == "OUTCOME_PENDING_DATA"),
        "no_action": sum(1 for r in results if r.get("status") == "NO_ACTION"),
        "invented": False,
        "results": results,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "trading": False,
    }


def learning_cockpit_from_store(root: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    """GUI projection of durable checkpoint/outcome/lesson stores. Not in-memory theater."""
    now = now or _now()
    root_p = Path(root)
    checkpoints = _jsonl(root_p / CHECKPOINT_PATH)
    observations = _jsonl(root_p / OBSERVATION_PATH)
    lessons = _jsonl(root_p / "data/cio/lesson_candidates.jsonl")
    hyps = _jsonl(root_p / "data/cio/hypothesis_candidates.jsonl")
    experiments = _jsonl(root_p / "data/cio/shadow_experiments.jsonl")
    counts = {"PENDING": 0, "DUE": 0, "COMPLETE": 0, "FAILED": 0, "BLOCKED_DATA": 0}
    for row in checkpoints:
        counts[classify_checkpoint(row, now=now)] = counts.get(classify_checkpoint(row, now=now), 0) + 1
    return {
        "ok": True,
        "schema": SCHEMA_COCKPIT,
        "outcomes_due": counts["DUE"],
        "checkpoint_counts": counts,
        "checkpoints_n": len(checkpoints),
        "observations_n": len(observations),
        "lessons_n": len(lessons),
        "hypotheses_n": len(hyps),
        "experiments_n": len(experiments),
        "pending": counts["PENDING"],
        "due": counts["DUE"],
        "completed": counts["COMPLETE"],
        "blocked_data": counts["BLOCKED_DATA"],
        "stores": {
            "checkpoints": CHECKPOINT_PATH,
            "observations": OBSERVATION_PATH,
        },
        "in_memory_only": False,
        "gui_cannot_self_promote": True,
        "max_unattended_stage": "REVIEW_READY",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
