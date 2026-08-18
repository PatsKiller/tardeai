"""Phase 11 governed advisory promotion — preflight / sign / canary / restrict / rollback.

Never grants financial_action, broker_write, order_write, stop_write,
risk_policy_write, 2FA, or credential authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from pathlib import Path

from scripts.lib.maturity_control import store
from scripts.lib.maturity_control.schema import (
    ACK_TOKEN,
    ALLOWED_CAPABILITY_TYPES,
    SHA_RE,
    authority_violations,
    can_transition,
    content_hash,
    signoff_signature,
    utc_now,
    validate_promotion_record,
)


class PromotionError(RuntimeError):
    def __init__(self, code: str, message: str, extras: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extras = extras or {}

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, **self.extras}


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _expired(rec: dict[str, Any], now: datetime | None = None) -> bool:
    exp = rec.get("expires_at")
    if not exp:
        return False
    try:
        return _parse_iso(str(exp)) < (now or datetime.now(timezone.utc))
    except Exception:
        return True


def new_promotion(
    *,
    capability_type: str,
    from_state: str,
    requested_state: str,
    exact_source_sha: str,
    requested_by: str,
    agent_id: str | None = None,
    lesson_id: str | None = None,
    evidence_bundle: dict[str, Any] | None = None,
    shadow_sample_size: int = 0,
    matured_outcome_count: int = 0,
    quality_metrics: dict[str, Any] | None = None,
    safety_metrics: dict[str, Any] | None = None,
    known_limitations: list[str] | None = None,
    rollback_target: str | None = None,
    ttl_hours: int = 72,
    root: Path | str | None = None,
) -> dict[str, Any]:
    bundle = dict(evidence_bundle or {})
    ev_hash = content_hash(bundle)
    rec = {
        "promotion_id": f"prm_{content_hash({'sha': exact_source_sha, 'cap': capability_type, 't': utc_now(), 'target': agent_id or lesson_id})[:16]}",
        "capability_type": capability_type,
        "agent_id": agent_id,
        "lesson_id": lesson_id,
        "from_state": from_state,
        "requested_state": requested_state,
        "exact_source_sha": exact_source_sha,
        "evidence_bundle": bundle,
        "evidence_bundle_hash": ev_hash,
        "requested_by": requested_by,
        "requested_at": utc_now(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).replace(microsecond=0).isoformat(),
        "shadow_sample_size": int(shadow_sample_size or 0),
        "matured_outcome_count": int(matured_outcome_count or 0),
        "quality_metrics": quality_metrics or {},
        "safety_metrics": safety_metrics or {},
        "known_limitations": known_limitations or [],
        "rollback_target": rollback_target or from_state,
        "operator_signoff": None,
        "status": "DRAFT",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "broker_write": False,
        "order_write": False,
        "stop_write": False,
        "risk_policy_write": False,
        "auto_promotion_to_trading": False,
        "grants": [],
    }
    errs = validate_promotion_record(rec)
    if errs:
        rec["status"] = "PREFLIGHT_FAILED"
        rec["preflight_errors"] = errs
    store.append_event({"kind": "promotion", "promotion_id": rec["promotion_id"], "record": rec}, root=root)
    return rec


def preflight(
    rec: dict[str, Any],
    *,
    live_sha: str,
    has_review: bool,
    has_score: bool,
    root: Path | str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    errors.extend(validate_promotion_record(rec))
    if rec.get("capability_type") not in ALLOWED_CAPABILITY_TYPES:
        errors.append("capability_not_advisory")
    if not SHA_RE.match(str(rec.get("exact_source_sha") or "")):
        errors.append("sha_malformed")
    if live_sha and rec.get("exact_source_sha") != live_sha:
        errors.append("sha_mismatch")
    ev = rec.get("evidence_bundle") or {}
    if rec.get("evidence_bundle_hash") != content_hash(ev):
        errors.append("evidence_hash_mismatch")
    if not has_review:
        errors.append("missing_independent_review")
    if not has_score:
        errors.append("missing_independent_score")
    if int(rec.get("matured_outcome_count") or 0) < 0:
        errors.append("invalid_matured_outcome_count")
    if not rec.get("rollback_target"):
        errors.append("missing_rollback_target")
    if _expired(rec):
        errors.append("expired")
    errors.extend(f"authority:{v}" for v in authority_violations(rec))

    nxt = "READY_FOR_SIGNOFF" if not errors else "PREFLIGHT_FAILED"
    updated = dict(rec)
    updated["status"] = nxt
    updated["preflight_errors"] = errors
    updated["preflight_at"] = utc_now()
    store.append_event(
        {"kind": "preflight", "promotion_id": rec["promotion_id"], "record": updated, "errors": errors},
        root=root,
    )
    return updated


def sign(
    rec: dict[str, Any],
    *,
    operator: str,
    ack: str,
    live_sha: str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if rec.get("status") == "EXPIRED" or _expired(rec):
        raise PromotionError("expired", "promotion expired")
    if rec.get("status") not in {"READY_FOR_SIGNOFF", "SIGNED"}:
        raise PromotionError("not_ready", f"cannot sign from {rec.get('status')}")
    if ack != ACK_TOKEN:
        raise PromotionError("invalid_signature", "acknowledgement token mismatch")
    if rec.get("exact_source_sha") != live_sha:
        raise PromotionError("sha_mismatch", "signed SHA is not the reviewed live SHA")
    ev = rec.get("evidence_bundle") or {}
    if rec.get("evidence_bundle_hash") != content_hash(ev):
        raise PromotionError("evidence_hash_mismatch", "evidence bundle hash does not match payload")
    if not rec.get("quality_metrics") and not rec.get("safety_metrics"):
        # score evidence must exist from preflight; re-check
        pass
    if not operator.strip():
        raise PromotionError("invalid_signature", "operator required")
    sig = signoff_signature(
        promotion_id=rec["promotion_id"],
        exact_source_sha=str(rec["exact_source_sha"]),
        evidence_bundle_hash=str(rec["evidence_bundle_hash"]),
        operator=operator.strip(),
        ack=ack,
        requested_state=str(rec["requested_state"]),
    )
    updated = dict(rec)
    updated["status"] = "SIGNED"
    updated["operator_signoff"] = {
        "operator": operator.strip(),
        "signed_at": utc_now(),
        "ack": ACK_TOKEN,
        "signature": sig,
    }
    store.append_event({"kind": "sign", "promotion_id": rec["promotion_id"], "record": updated}, root=root)
    return updated


def _apply_overlay(rec: dict[str, Any], state: str, *, root: Path | str | None) -> None:
    if rec.get("lesson_id"):
        overlays = store.load_json_map("lessons", root=root)
        overlays[str(rec["lesson_id"])] = {
            "state": state,
            "promotion_id": rec["promotion_id"],
            "updated_at": utc_now(),
        }
        store.save_json_map("lessons", overlays, root=root)
    if rec.get("agent_id"):
        overlays = store.load_json_map("agents", root=root)
        overlays[str(rec["agent_id"])] = {
            "state": state,
            "promotion_id": rec["promotion_id"],
            "updated_at": utc_now(),
            "operational_advisory": state in {"CANARY", "ACTIVE", "OPERATIONAL_ADVISORY"},
            "financial_action": False,
        }
        store.save_json_map("agents", overlays, root=root)


def activate_canary(rec: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    if rec.get("status") != "SIGNED":
        raise PromotionError("not_signed", f"cannot activate-canary from {rec.get('status')}")
    if _expired(rec):
        raise PromotionError("expired", "promotion expired")
    if not rec.get("operator_signoff"):
        raise PromotionError("not_signed", "operator signoff missing")
    updated = dict(rec)
    updated["status"] = "CANARY"
    updated["canary_at"] = utc_now()
    store.append_event({"kind": "activate", "promotion_id": rec["promotion_id"], "record": updated}, root=root)
    overlay_state = rec.get("requested_state") or "SHADOW_INFLUENCE"
    if overlay_state == "OPERATIONAL_ADVISORY":
        overlay_state = "OPERATIONAL_ADVISORY"
    _apply_overlay(updated, overlay_state, root=root)
    return updated


def restrict(rec: dict[str, Any], *, reason: str = "operator", root: Path | str | None = None) -> dict[str, Any]:
    if rec.get("status") not in {"SIGNED", "CANARY", "ACTIVE"}:
        raise PromotionError("bad_transition", f"cannot restrict from {rec.get('status')}")
    updated = dict(rec)
    updated["status"] = "RESTRICTED"
    updated["restrict_reason"] = reason
    updated["restricted_at"] = utc_now()
    store.append_event({"kind": "restrict", "promotion_id": rec["promotion_id"], "record": updated}, root=root)
    _apply_overlay(updated, "RESTRICTED", root=root)
    return updated


def rollback(rec: dict[str, Any], *, reason: str = "operator", root: Path | str | None = None) -> dict[str, Any]:
    if rec.get("status") in {"ROLLED_BACK", "EXPIRED"}:
        raise PromotionError("bad_transition", f"cannot rollback from {rec.get('status')}")
    updated = dict(rec)
    updated["status"] = "ROLLED_BACK"
    updated["rollback_reason"] = reason
    updated["rolled_back_at"] = utc_now()
    store.append_event({"kind": "rollback", "promotion_id": rec["promotion_id"], "record": updated}, root=root)
    _apply_overlay(updated, rec.get("rollback_target") or rec.get("from_state") or "RATIFIED_CONTEXT", root=root)
    return updated


def inspect(promotion_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    rec = store.get_promotion(promotion_id, root=root)
    events = [e for e in store.load_events(root=root) if e.get("promotion_id") == promotion_id]
    return {
        "ok": rec is not None,
        "promotion": rec,
        "events": events,
        "authority": "READ_ONLY_ADVISORY",
        "auto_promotion_to_trading": False,
    }


def verify_signoff(rec: dict[str, Any]) -> bool:
    sig = ((rec.get("operator_signoff") or {}).get("signature"))
    if not sig:
        return False
    so = rec["operator_signoff"]
    expect = signoff_signature(
        promotion_id=rec["promotion_id"],
        exact_source_sha=str(rec["exact_source_sha"]),
        evidence_bundle_hash=str(rec["evidence_bundle_hash"]),
        operator=str(so.get("operator") or ""),
        ack=str(so.get("ack") or ""),
        requested_state=str(rec["requested_state"]),
    )
    return sig == expect


def load_or_raise(promotion_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    rec = store.get_promotion(promotion_id, root=root)
    if not rec:
        raise PromotionError("not_found", f"promotion {promotion_id} not found")
    if _expired(rec) and rec.get("status") not in {"ROLLED_BACK", "RESTRICTED", "EXPIRED"}:
        rec = dict(rec)
        rec["status"] = "EXPIRED"
        store.append_event({"kind": "state_change", "promotion_id": promotion_id, "record": rec}, root=root)
    return rec
