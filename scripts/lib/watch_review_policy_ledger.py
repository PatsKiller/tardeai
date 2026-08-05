"""Durable recurring review-policy authorization ledger (Watch Intelligence).

Policy authorizations are parent records. Every provider execution requires a
child execution authorization validated before cost reservation.

operator_approved=true inside an artifact is NEVER sufficient.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")

LEDGER_ROOT = PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "policy_ledger"
POLICIES_DIR = LEDGER_ROOT / "policies"
EXEC_DIR = LEDGER_ROOT / "execution_authorizations"
JOBS_DIR = LEDGER_ROOT / "jobs"
EVENT_STATE_DIR = LEDGER_ROOT / "event_state"
NO_CALL_DIR = PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "no_call"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "quarantine"

# Registered process IDs — do not invent replacements
MARIA_PROCESS_ID = "watchlist_maria_flash_narrative"
CIO_PROCESS_ID = "watchlist_cio_synthesis"

MARIA_SPEC = {
    "agent_id": "maria",
    "registered_process_id": MARIA_PROCESS_ID,
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "policy": "FAST",
    "thinking": "off",
    "fallback_allowed": False,
}
CIO_SPEC = {
    "agent_id": "cio",
    "registered_process_id": CIO_PROCESS_ID,
    "provider": "deepseek",
    "model": "deepseek-v4-pro",
    "policy": "PRO",
    "thinking": "off",
    "fallback_allowed": False,
}

GLOBAL_DAILY_USD_CAP = 0.25
MARIA_MAX_CALLS_PER_RUN = 15
MARIA_RUN_CAP_USD = 0.08
CIO_MAX_CALLS_PER_RUN = 8
CIO_RUN_CAP_USD = 0.14

# Workers remain disabled until phase 5
DEFAULT_WORKERS_ENABLED = False
DEFAULT_EVENT_WATCHER_ENABLED = False

CANONICAL_POLICY_ID = "watch_intel_maria_cio_mwf_v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _ensure_dirs() -> None:
    for d in (POLICIES_DIR, EXEC_DIR, JOBS_DIR / "pending", JOBS_DIR / "completed",
              JOBS_DIR / "deferred", EVENT_STATE_DIR, NO_CALL_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    _ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def containment_required_ok() -> tuple[bool, str]:
    """Containment must remain ACTIVE for governed automated reviews (fail-closed)."""
    try:
        from lib.agent_jobs_containment import evaluate_containment_state, STATUS_ACTIVE
        st = evaluate_containment_state()
        if st.get("status") == STATUS_ACTIVE:
            return True, "containment_active"
        return False, f"containment_not_active:{st.get('status')}"
    except Exception as e:
        return False, f"containment_check_failed:{e}"


def build_intended_policy(
    *,
    operator_id: str = "operator",
    effective_at: str | None = None,
    expires_days: int = 90,
) -> dict[str, Any]:
    """Construct the durable recurring policy described by operator instruction.

    Does not enable workers. Does not authorize any call until persist_policy().
    """
    now = _now()
    effective = effective_at or now.isoformat()
    expires = (now + timedelta(days=expires_days)).isoformat()
    return {
        "authorization_policy_id": CANONICAL_POLICY_ID,
        "operator_id": operator_id,
        "created_at": now.isoformat(),
        "effective_at": effective,
        "expires_at": expires,
        "timezone": "America/New_York",
        "schedule": {
            "maria": {
                "days": ["Monday", "Wednesday", "Friday"],
                "time_et": "16:05",
                "agent_id": "maria",
                "registered_process_id": MARIA_PROCESS_ID,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "policy": "FAST",
                "thinking": "off",
            },
            "cio": {
                "days": ["Monday", "Wednesday", "Friday"],
                "time_et": "16:20",
                "agent_id": "cio",
                "registered_process_id": CIO_PROCESS_ID,
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "policy": "PRO",
                "thinking": "off",
                "requires_current_maria": True,
            },
        },
        "eligible_universe_definition": {
            "priority_order": [
                "held",
                "starred",
                "top_ideas_non_held",
                "street_strong_buy_buy_priority_limit",
                "rolling_7pct_event",
            ],
            "exclude": [
                "unresolved_identity",
                "missing_canonical_quote",
                "DATA_UNAVAILABLE",
                "stale_mandatory_evidence",
                "AVOID",
                "BLOCKED",
                "DETERMINISTIC_FAIL",
                "quarantined_authorization",
            ],
        },
        "event_trigger_definition": {
            "kind": "ROLLING_5_SESSION_MOVE_GE_7PCT",
            "threshold_abs": 0.07,
            "sessions": 5,
            "watcher_interval_minutes": 15,
            "watcher_calls_provider": False,
            "edge_triggered": True,
            "max_event_chain_per_symbol_per_24h": 1,
            "reason_code": "ROLLING_5_SESSION_MOVE_GE_7PCT",
        },
        "allowed_agents": ["maria", "cio"],
        "allowed_process_ids": [MARIA_PROCESS_ID, CIO_PROCESS_ID],
        "allowed_providers": ["deepseek"],
        "allowed_models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "allowed_policies": ["FAST", "PRO"],
        "maximum_calls_per_run": {
            "maria": MARIA_MAX_CALLS_PER_RUN,
            "cio": CIO_MAX_CALLS_PER_RUN,
        },
        "maximum_calls_per_symbol_per_day": 2,
        "maximum_cost_per_run_usd": {
            "maria": MARIA_RUN_CAP_USD,
            "cio": CIO_RUN_CAP_USD,
        },
        "maximum_cost_per_day_usd": GLOBAL_DAILY_USD_CAP,
        "fallback_allowed": False,
        "containment_required": True,
        "authorization_status": "ACTIVE",
        "revoked_at": None,
        "revocation_reason": None,
        "workers_enabled": False,
        "event_watcher_enabled": False,
        "source": "operator_instruction_watch_review_automation",
        "advisory_only": True,
        "broker_authority": "NONE",
    }


def persist_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write durable policy record. Does not enable workers or call providers."""
    _ensure_dirs()
    pol = dict(policy or build_intended_policy())
    pid = pol["authorization_policy_id"]
    path = POLICIES_DIR / f"{pid}.json"
    pol["persisted_at"] = _now_iso()
    # Force workers off at persistence time (phase 2)
    pol["workers_enabled"] = False
    pol["event_watcher_enabled"] = False
    _atomic_write(path, pol)
    # index pointer
    _atomic_write(LEDGER_ROOT / "ACTIVE_POLICY.json", {
        "authorization_policy_id": pid,
        "path": str(path),
        "updated_at": _now_iso(),
        "workers_enabled": False,
        "event_watcher_enabled": False,
    })
    return pol


def load_policy(policy_id: str | None = None) -> dict[str, Any] | None:
    _ensure_dirs()
    pid = policy_id
    if not pid:
        idx = _read_json(LEDGER_ROOT / "ACTIVE_POLICY.json") or {}
        pid = idx.get("authorization_policy_id")
    if not pid:
        return None
    return _read_json(POLICIES_DIR / f"{pid}.json")


def list_policies() -> list[dict[str, Any]]:
    _ensure_dirs()
    out = []
    for p in sorted(POLICIES_DIR.glob("*.json")):
        data = _read_json(p)
        if data:
            out.append(data)
    return out


def validate_policy(policy: dict[str, Any] | None) -> tuple[bool, str]:
    if not policy:
        return False, "MISSING_POLICY"
    if policy.get("authorization_status") != "ACTIVE":
        return False, f"POLICY_STATUS_{policy.get('authorization_status')}"
    if policy.get("revoked_at"):
        return False, "POLICY_REVOKED"
    try:
        exp = datetime.fromisoformat(str(policy["expires_at"]).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if _now() > exp:
            return False, "POLICY_EXPIRED"
    except Exception:
        return False, "POLICY_EXPIRES_AT_INVALID"
    if policy.get("fallback_allowed") is True:
        return False, "FALLBACK_FORBIDDEN"
    if policy.get("containment_required"):
        ok, reason = containment_required_ok()
        if not ok:
            return False, f"CONTAINMENT_REQUIRED:{reason}"
    return True, "OK"


def revoke_policy(policy_id: str, reason: str) -> dict[str, Any]:
    pol = load_policy(policy_id)
    if not pol:
        raise ValueError("policy_not_found")
    pol["authorization_status"] = "REVOKED"
    pol["revoked_at"] = _now_iso()
    pol["revocation_reason"] = reason
    pol["workers_enabled"] = False
    pol["event_watcher_enabled"] = False
    _atomic_write(POLICIES_DIR / f"{policy_id}.json", pol)
    return pol


def agent_spec(agent_id: str) -> dict[str, Any]:
    a = (agent_id or "").lower()
    if a == "maria":
        return dict(MARIA_SPEC)
    if a == "cio":
        return dict(CIO_SPEC)
    raise ValueError(f"unknown_agent:{agent_id}")


def create_execution_authorization(
    *,
    policy_id: str,
    symbol: str,
    agent_id: str,
    input_snapshot_id: str,
    input_hash: str,
    trigger_reason: str,
    maximum_cost_usd: float | None = None,
    expires_minutes: int = 60,
) -> dict[str, Any]:
    """Create a single-use child authorization. Does not call a provider."""
    pol = load_policy(policy_id)
    ok, reason = validate_policy(pol)
    if not ok:
        raise PermissionError(reason)
    assert pol is not None
    spec = agent_spec(agent_id)
    if spec["agent_id"] not in (pol.get("allowed_agents") or []):
        raise PermissionError("AGENT_OUT_OF_SCOPE")
    if spec["registered_process_id"] not in (pol.get("allowed_process_ids") or []):
        raise PermissionError("PROCESS_MISMATCH")
    if spec["provider"] not in (pol.get("allowed_providers") or []):
        raise PermissionError("PROVIDER_MISMATCH")
    if spec["model"] not in (pol.get("allowed_models") or []):
        raise PermissionError("MODEL_MISMATCH")
    if spec["policy"] not in (pol.get("allowed_policies") or []):
        raise PermissionError("POLICY_MISMATCH")
    if spec["fallback_allowed"] or pol.get("fallback_allowed"):
        raise PermissionError("FALLBACK_FORBIDDEN")

    max_cost = maximum_cost_usd
    if max_cost is None:
        caps = pol.get("maximum_cost_per_run_usd") or {}
        max_cost = float(caps.get(agent_id) or 0.05)

    eid = f"exec_{agent_id}_{symbol.upper()}_{uuid.uuid4().hex[:12]}"
    rec = {
        "execution_authorization_id": eid,
        "authorization_policy_id": policy_id,
        "symbol": symbol.upper(),
        "agent_id": spec["agent_id"],
        "registered_process_id": spec["registered_process_id"],
        "provider": spec["provider"],
        "model": spec["model"],
        "requested_policy": spec["policy"],
        "thinking": spec["thinking"],
        "fallback_allowed": False,
        "input_snapshot_id": input_snapshot_id,
        "input_hash": input_hash,
        "trigger_reason": trigger_reason,
        "authorized_at": _now_iso(),
        "expires_at": (_now() + timedelta(minutes=expires_minutes)).isoformat(),
        "maximum_calls": 1,
        "maximum_cost_usd": max_cost,
        "consumed_at": None,
        "provider_request_reference": None,
        "status": "ISSUED",
    }
    _atomic_write(EXEC_DIR / f"{eid}.json", rec)
    return rec


def load_execution_authorization(execution_id: str) -> dict[str, Any] | None:
    return _read_json(EXEC_DIR / f"{execution_id}.json")


def validate_execution_authorization(
    execution_id: str,
    *,
    symbol: str,
    agent_id: str,
    process_id: str,
    provider: str,
    model: str,
    policy: str,
    input_hash: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate child auth before cost reservation. Rejects reuse/expiry/mismatch."""
    rec = load_execution_authorization(execution_id)
    if not rec:
        return False, "MISSING_EXECUTION_AUTHORIZATION", None
    if rec.get("status") == "CONSUMED" or rec.get("consumed_at"):
        return False, "EXECUTION_AUTHORIZATION_REUSED", rec
    if rec.get("status") not in ("ISSUED", "RESERVED"):
        return False, f"EXECUTION_STATUS_{rec.get('status')}", rec
    try:
        exp = datetime.fromisoformat(str(rec["expires_at"]).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if _now() > exp:
            return False, "EXECUTION_AUTHORIZATION_EXPIRED", rec
    except Exception:
        return False, "EXECUTION_EXPIRES_INVALID", rec

    pol = load_policy(rec.get("authorization_policy_id"))
    ok, reason = validate_policy(pol)
    if not ok:
        return False, reason, rec

    if (rec.get("symbol") or "").upper() != (symbol or "").upper():
        return False, "SYMBOL_OUT_OF_SCOPE", rec
    if (rec.get("agent_id") or "").lower() != (agent_id or "").lower():
        return False, "AGENT_MISMATCH", rec
    if rec.get("registered_process_id") != process_id:
        return False, "PROCESS_MISMATCH", rec
    if rec.get("provider") != provider:
        return False, "PROVIDER_MISMATCH", rec
    if rec.get("model") != model:
        return False, "MODEL_MISMATCH", rec
    if rec.get("requested_policy") != policy:
        return False, "POLICY_MISMATCH", rec
    if rec.get("input_hash") != input_hash:
        return False, "INPUT_HASH_MISMATCH", rec
    if rec.get("fallback_allowed") is True:
        return False, "FALLBACK_FORBIDDEN", rec
    return True, "OK", rec


def mark_execution_reserved(execution_id: str, reservation_id: Any) -> dict[str, Any]:
    rec = load_execution_authorization(execution_id)
    if not rec:
        raise ValueError("missing_execution")
    if rec.get("consumed_at"):
        raise PermissionError("EXECUTION_AUTHORIZATION_REUSED")
    rec["status"] = "RESERVED"
    rec["reservation_id"] = reservation_id
    rec["reserved_at"] = _now_iso()
    _atomic_write(EXEC_DIR / f"{execution_id}.json", rec)
    return rec


def mark_execution_consumed(
    execution_id: str,
    *,
    provider_request_reference: str,
    settlement_id: Any = None,
) -> dict[str, Any]:
    rec = load_execution_authorization(execution_id)
    if not rec:
        raise ValueError("missing_execution")
    if rec.get("consumed_at"):
        raise PermissionError("EXECUTION_AUTHORIZATION_REUSED")
    rec["status"] = "CONSUMED"
    rec["consumed_at"] = _now_iso()
    rec["provider_request_reference"] = provider_request_reference
    rec["settlement_id"] = settlement_id
    _atomic_write(EXEC_DIR / f"{execution_id}.json", rec)
    return rec


def complete_artifact_required_fields() -> tuple[str, ...]:
    return (
        "authorization_policy_id",
        "execution_authorization_id",
        "agent_id",
        "agent_version",
        "registered_process_id",
        "provider",
        "model",
        "requested_policy",
        "executed_policy",
        "thinking",
        "fallback_used",
        "provider_request_id",
        "reservation_id",
        "settlement_id",
        "started_at",
        "completed_at",
        "input_snapshot_id",
        "input_hash",
        "artifact_id",
        "artifact_hash",
        "prompt_tokens",
        "completion_tokens",
        "estimated_cost_usd",
        "settled_cost_usd",
        "reconciliation_status",
        "verdict",
        "summary",
        "thesis",
        "counter_thesis",
        "catalysts",
        "risks",
        "evidence_gaps",
        "what_changes_the_decision",
        "evidence_references",
    )


def artifact_may_display_complete(raw: dict[str, Any]) -> tuple[bool, str | None]:
    """Stricter COMPLETE gate for automated pipeline artifacts."""
    if not raw:
        return False, "EMPTY"
    if raw.get("status") == "QUARANTINED" or raw.get("quarantine"):
        return False, "QUARANTINED"
    if raw.get("fallback_used") is True:
        return False, "FALLBACK_USED"
    for k in complete_artifact_required_fields():
        if raw.get(k) in (None, "", "NONE"):
            # catalysts/risks/evidence may be empty lists — allow
            if k in ("catalysts", "risks", "evidence_gaps", "evidence_references") and raw.get(k) == []:
                continue
            return False, f"MISSING_{k.upper()}"
    # Child auth must still validate
    ok, reason, _ = validate_execution_authorization(
        str(raw.get("execution_authorization_id")),
        symbol=str(raw.get("symbol") or ""),
        agent_id=str(raw.get("agent_id") or ""),
        process_id=str(raw.get("registered_process_id") or raw.get("process_id") or ""),
        provider=str(raw.get("provider") or ""),
        model=str(raw.get("model") or ""),
        policy=str(raw.get("executed_policy") or raw.get("requested_policy") or ""),
        input_hash=str(raw.get("input_hash") or ""),
    )
    # For display of already-consumed auth, reuse is expected after complete
    if not ok and reason != "EXECUTION_AUTHORIZATION_REUSED":
        # After consumption, status is CONSUMED — allow if IDs match and were consumed
        rec = load_execution_authorization(str(raw.get("execution_authorization_id") or ""))
        if not rec or rec.get("status") != "CONSUMED":
            return False, reason
        if rec.get("provider_request_reference") != raw.get("provider_request_id"):
            return False, "PROVIDER_REQUEST_MISMATCH"
    return True, None


def policy_api_payload() -> dict[str, Any]:
    """Read-only API envelope for the durable policy (phase 2)."""
    pol = load_policy()
    active = _read_json(LEDGER_ROOT / "ACTIVE_POLICY.json")
    ok, reason = validate_policy(pol) if pol else (False, "MISSING_POLICY")
    return {
        "ok": True,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "broker_write_authority": "NONE",
        "authorization_endpoint": "/api/v3/data-broker/watch-review-policy",
        "active_policy_id": (pol or {}).get("authorization_policy_id") if pol else None,
        "authorization_policy_id": (pol or {}).get("authorization_policy_id") if pol else None,
        "policy_valid": ok,
        "policy_validation_reason": reason,
        "workers_enabled": bool((pol or {}).get("workers_enabled")),
        "event_watcher_enabled": bool((pol or {}).get("event_watcher_enabled")),
        "containment_required": True,
        "fallback_allowed": False,
        "maria": MARIA_SPEC,
        "cio": CIO_SPEC,
        "global_daily_usd_cap": GLOBAL_DAILY_USD_CAP,
        "maximum_maria_calls_per_run": MARIA_MAX_CALLS_PER_RUN,
        "maximum_cio_calls_per_run": CIO_MAX_CALLS_PER_RUN,
        "policy": pol,
        "active_index": active,
        "schedules": {
            "maria": "Mon/Wed/Fri 16:05 America/New_York",
            "cio": "Mon/Wed/Fri 16:20 America/New_York",
        },
        "event_trigger": "ROLLING_5_SESSION_MOVE_GE_7PCT",
        "ceco_quarantine_preserved": QUARANTINE_DIR.exists() and any(QUARANTINE_DIR.glob("CECO_*.json")),
    }
