"""Durable recurring review-policy authorization ledger (Watch Intelligence).

Policy authorizations are parent records. Every provider execution requires a
child execution authorization validated before cost reservation.

operator_approved=true inside an artifact is NEVER sufficient.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lib.llm_model_registry import deepseek_model_id, resolve_logical_policy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")

# Prefer host shared runtime (portfolio-server data/runtime symlink target) so
# worktree workers and the live release board read/write the same ledger + artifacts.
_MAIN_RUNTIME = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime")


def runtime_root() -> Path:
    env = (os.environ.get("TRADEAI_RUNTIME_ROOT") or "").strip()
    if env:
        return Path(env)
    if _MAIN_RUNTIME.exists():
        return _MAIN_RUNTIME
    return PROJECT_ROOT / "data" / "runtime"


def _wi_root() -> Path:
    return runtime_root() / "watchlist_intelligence"


LEDGER_ROOT = _wi_root() / "policy_ledger"
POLICIES_DIR = LEDGER_ROOT / "policies"
EXEC_DIR = LEDGER_ROOT / "execution_authorizations"
JOBS_DIR = LEDGER_ROOT / "jobs"
EVENT_STATE_DIR = LEDGER_ROOT / "event_state"
NO_CALL_DIR = _wi_root() / "no_call"
QUARANTINE_DIR = _wi_root() / "quarantine"
ARTIFACTS_DIR = _wi_root() / "artifacts"

# Registered process IDs — do not invent replacements
MARIA_PROCESS_ID = "watchlist_maria_flash_narrative"
CIO_PROCESS_ID = "watchlist_cio_synthesis"

MARIA_SPEC = {
    "agent_id": "maria",
    "registered_process_id": MARIA_PROCESS_ID,
    "provider": "deepseek",
    "model": deepseek_model_id("FAST"),
    "policy": "FAST",
    "thinking": "off",
    "fallback_allowed": False,
}
CIO_SPEC = {
    "agent_id": "cio",
    "registered_process_id": CIO_PROCESS_ID,
    "provider": "deepseek",
    "model": deepseek_model_id("PRO_THINK"),
    "policy": "PRO_THINK",
    "thinking": resolve_logical_policy("PRO_THINK")["thinking"],
    "fallback_allowed": False,
}

GLOBAL_DAILY_USD_CAP = 0.25
MARIA_MAX_CALLS_PER_RUN = 15
MARIA_RUN_CAP_USD = 0.08
CIO_MAX_CALLS_PER_RUN = 8

#: Everything that GRANTS authority in a parent record. A change to any of these is a new approval, not a rename:
#: the record carries an ``authority_approval`` digest over exactly this set, so editing the file in place (the only
#: way authority has ever been widened without review) invalidates it. Caps are here because raising them widens
#: authority just as renaming a model does.
AUTHORITY_FIELDS = (
    "authorization_policy_id",
    "allowed_agents",
    "allowed_process_ids",
    "allowed_providers",
    "allowed_models",
    "allowed_policies",
    "expires_at",
    "effective_at",
    "containment_required",
    "fallback_allowed",
    "maximum_calls_per_run",
    "maximum_calls_per_symbol_per_day",
    "maximum_cost_per_run_usd",
    "maximum_cost_per_day_usd",
)


def authority_digest(policy: dict[str, Any] | None) -> str:
    """Digest of the authority-bearing fields. Renaming a model changes it; a mere status flip does not."""
    core = {key: (policy or {}).get(key) for key in AUTHORITY_FIELDS}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
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
    for d in (
        POLICIES_DIR,
        EXEC_DIR,
        JOBS_DIR / "pending",
        JOBS_DIR / "completed",
        JOBS_DIR / "deferred",
        EVENT_STATE_DIR,
        NO_CALL_DIR,
    ):
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
        try:
            from lib.agent_jobs_containment import containment_cleared
        except ImportError:  # pragma: no cover
            from scripts.lib.agent_jobs_containment import containment_cleared  # type: ignore
        if containment_cleared():
            return True, "containment_cleared_by_operator"
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
                "model": deepseek_model_id("FAST"),
                "policy": "FAST",
                "thinking": "off",
            },
            "cio": {
                "days": ["Monday", "Wednesday", "Friday"],
                "time_et": "16:20",
                "agent_id": "cio",
                "registered_process_id": CIO_PROCESS_ID,
                "provider": "deepseek",
                "model": deepseek_model_id("PRO_THINK"),
                "policy": "PRO_THINK",
                "thinking": CIO_SPEC["thinking"],
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
        "allowed_models": list(dict.fromkeys([MARIA_SPEC["model"], CIO_SPEC["model"]])),
        "allowed_policies": ["FAST", "PRO_THINK"],
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


def persist_policy(policy: dict[str, Any] | None = None, *, approved_by: str | None = None) -> dict[str, Any]:
    """Write durable policy record. Does not enable workers or call providers.

    Persisting IS the approval event: the record carries an ``authority_approval`` digest over its
    authority-bearing fields, written here and only here. That is what makes a later in-place edit (a
    "silent rename" of an allowed model) grant nothing — it changes the digest and the dispatch gate
    refuses until an operator persists the record again (2026-11-04 joint invariant).
    """
    _ensure_dirs()
    pol = dict(policy or build_intended_policy())
    pid = pol["authorization_policy_id"]
    path = POLICIES_DIR / f"{pid}.json"
    pol["persisted_at"] = _now_iso()
    # Force workers off at persistence time (phase 2 install); use set_workers_enabled for phase 5
    pol["workers_enabled"] = False
    pol["event_watcher_enabled"] = False
    pol["authority_approval"] = {
        "approved_by": str(approved_by or pol.get("operator_id") or "operator").strip() or "operator",
        "approved_at": _now_iso(),
        "reason": "persist_policy",
        "digest": authority_digest(pol),
    }
    _atomic_write(path, pol)
    # index pointer
    _atomic_write(
        LEDGER_ROOT / "ACTIVE_POLICY.json",
        {
            "authorization_policy_id": pid,
            "path": str(path),
            "updated_at": _now_iso(),
            "workers_enabled": False,
            "event_watcher_enabled": False,
        },
    )
    return pol


def set_workers_enabled(
    *,
    workers: bool = True,
    event_watcher: bool = False,
    operator_id: str = "johnclaw",
    reason: str = "operator_enable_scheduled_mwf",
) -> dict[str, Any]:
    """Phase 5: enable/disable scheduled workers without reinstalling the whole policy.

    Does not call providers. Does not lift CECO quarantine. Does not clear host containment flag.
    """
    _ensure_dirs()
    pol = load_policy()
    if not pol:
        pol = build_intended_policy(operator_id=operator_id)
        # seed file with workers off, then flip below
        persist_policy(pol)
        pol = load_policy()
    assert pol is not None
    ok, reason_v = validate_policy(pol)
    if not ok:
        raise PermissionError(f"cannot_enable_workers:{reason_v}")
    pol["workers_enabled"] = bool(workers)
    pol["event_watcher_enabled"] = bool(event_watcher)
    pol["workers_enabled_at"] = _now_iso() if workers else None
    pol["workers_enabled_by"] = operator_id if workers else None
    pol["workers_enable_reason"] = reason if workers else None
    if not workers:
        pol["workers_disabled_at"] = _now_iso()
        pol["workers_disabled_reason"] = reason
    pid = pol["authorization_policy_id"]
    path = POLICIES_DIR / f"{pid}.json"
    pol["updated_at"] = _now_iso()
    _atomic_write(path, pol)
    _atomic_write(
        LEDGER_ROOT / "ACTIVE_POLICY.json",
        {
            "authorization_policy_id": pid,
            "path": str(path),
            "updated_at": _now_iso(),
            "workers_enabled": bool(workers),
            "event_watcher_enabled": bool(event_watcher),
            "reason": reason,
            "operator_id": operator_id,
        },
    )
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


def policy_expiry_verdict(policy: dict[str, Any] | None, *, now: datetime | None = None) -> tuple[bool, str]:
    """Is the record still inside its own validity window? A parsed clock, never a status string.

    This is the single place the expiry fact is read (2026-11-04, property B): a status field is a claim written by
    whoever edited the file — the live Maria/CIO record read ACTIVE while its ``expires_at`` was already a day past —
    so the clock is checked FIRST and outranks the status string everywhere.

    EXPIRY IS MANDATORY, AND UNPARSEABLE MEANS REFUSED (property D): a record whose expiry is missing, empty, null or
    not a parseable timestamp cannot demonstrate that it is current, and an inability to prove must never resolve to
    permission. Do not "fix" this by returning OK on a parse error.
    """
    try:
        exp = datetime.fromisoformat(str((policy or {})["expires_at"]).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if (now or _now()) > exp:
            return False, "POLICY_EXPIRED"
    except Exception:
        return False, "POLICY_EXPIRES_AT_INVALID"
    return True, "OK"


def validate_policy(policy: dict[str, Any] | None, *, now: datetime | None = None) -> tuple[bool, str]:
    if not policy:
        return False, "MISSING_POLICY"
    # EXPIRY OUTRANKS THE STATUS STRING (property B). Reversed from the pre-2026-11-04 order, where a record whose
    # status said REVOKED/DRAFT reported that string and its expired clock was never consulted; and stated here, in
    # the one validation function every caller shares, rather than duplicated in the dispatch gate.
    ok, reason = policy_expiry_verdict(policy, now=now)
    if not ok:
        return False, reason
    if policy.get("authorization_status") != "ACTIVE":
        return False, f"POLICY_STATUS_{policy.get('authorization_status')}"
    if policy.get("revoked_at"):
        return False, "POLICY_REVOKED"
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


def dispatch_authority(
    agent_id: str,
    *,
    policy_id: str | None = None,
    model: str | None = None,
    record: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """THE joint dispatch invariant: registry-valid AND explicitly parent-approved, or no dispatch.

    One function covers both boundaries, because they have drifted apart in production twice:

    * the RUNTIME resolves a logical policy to an exact model id through the canonical registry, and a caller may
      not supply a different one (a literal that the registry has since retired is a refusal, not a fallback);
    * the PERSISTED record must name that exact model AND that logical policy, per member list — approval is
      explicit, never inferred from a range, prefix, alias or a matching-looking name;
    * an EXPIRED record cannot authorise, whatever its ``authorization_status`` string says (a status field is a
      claim; the clock is a fact, and the live Maria/CIO record is ACTIVE on paper while expired since 2026-11-03);
    * the record's authority-bearing fields must still match the digest the operator approved, so silently
      renaming a model in the JSON grants nothing.

    Order is part of the contract. A refusal is always a named reason, and there is no path that returns a pass
    for an unapproved model.
    """
    pol = record if record is not None else load_policy(policy_id)
    if not pol:
        return False, "MISSING_POLICY", None
    # One expiry order for every caller: validate_policy checks the clock BEFORE the status string (property B),
    # so there is no second copy of this rule here to drift from it.
    ok, reason = validate_policy(pol, now=now)
    if not ok:
        return False, reason, pol
    try:
        spec = agent_spec(agent_id)
    except ValueError:
        return False, "AGENT_OUT_OF_SCOPE", pol
    if spec["agent_id"] not in (pol.get("allowed_agents") or []):
        return False, "AGENT_OUT_OF_SCOPE", pol
    expected = deepseek_model_id(spec["policy"])
    if model is not None and model != expected:
        return False, "MODEL_NOT_REGISTRY_CURRENT", pol
    if expected not in (pol.get("allowed_models") or []):
        return False, "MODEL_MISMATCH", pol
    if spec["policy"] not in (pol.get("allowed_policies") or []):
        return False, "POLICY_MISMATCH", pol
    if spec["fallback_allowed"] or pol.get("fallback_allowed") is True:
        return False, "FALLBACK_FORBIDDEN", pol
    approval = pol.get("authority_approval") or {}
    if not isinstance(approval, dict) or not approval.get("digest"):
        return False, "AUTHORITY_NOT_APPROVED", pol
    if str(approval.get("approved_by") or "").strip() == "" or not approval.get("approved_at"):
        return False, "AUTHORITY_NOT_APPROVED", pol
    if approval["digest"] != authority_digest(pol):
        return False, "AUTHORITY_CHANGED_SINCE_APPROVAL", pol
    return True, "OK", pol


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
    # Joint invariant (2026-11-04): registry-resolved AND explicitly approved, in one place. Replaces the two
    # membership checks that let a renamed allowed_models list silently gain authority.
    ok, reason, _ = dispatch_authority(agent_id, model=spec["model"], record=pol)
    if not ok:
        raise PermissionError(reason)

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
        "authority_digest": authority_digest(pol),
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
    # The parent must STILL authorise this dispatch (registry + explicit approval + unchanged approval digest),
    # and the child must have been issued against the authority that is standing now.
    ok, reason, _ = dispatch_authority(str(rec.get("agent_id") or ""), model=rec.get("model"), record=pol)
    if not ok:
        return False, reason, rec
    if rec.get("authority_digest") and rec["authority_digest"] != authority_digest(pol):
        return False, "AUTHORITY_CHANGED_SINCE_ISSUE", rec

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
