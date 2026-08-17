"""agent_context_envelope.py — ContextEnvelope@v1 + get_context_for_agent() (Phase 1).

READ_ONLY_ADVISORY. Canonical context object shared by Alex and specialists.

Guarantees:
  * deterministic stable serialization for the context digest
  * explicit source/as-of on canonical truth
  * memory separated from truth (memory is NON_AUTHORITATIVE_CONTEXT)
  * conflicts surfaced, never silently folded into truth
  * missing providers represented explicitly (NOT_CONFIGURED / UNAVAILABLE)
  * no hidden fallback to stale memory

Pure and deterministic. No broker / order / stop / 2FA / Telegram side effects.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

CONTEXT_ENVELOPE_VERSION = "1.0"

# ── Authority ──────────────────────────────────────────────────────────────
AUTHORITY_READ_ONLY_ADVISORY = "READ_ONLY_ADVISORY"
MEMORY_AUTHORITY_NON_AUTHORITATIVE = "NON_AUTHORITATIVE_CONTEXT"

# ── Retrieval status enums ─────────────────────────────────────────────────
RETRIEVAL_OK = "OK"
RETRIEVAL_UNAVAILABLE = "UNAVAILABLE"
RETRIEVAL_NOT_CONFIGURED = "NOT_CONFIGURED"
RETRIEVAL_EMPTY = "EMPTY"
RETRIEVAL_CONFLICT = "CONFLICT"
RETRIEVAL_ERROR = "ERROR"

# ── Schema section keys (single source of truth) ──────────────────────────
SECTION_DECISION = "decision"
SECTION_OFFICE_TRUTH = "office_truth"
SECTION_ACTIVE_INTENT = "active_intent"
SECTION_EPISODIC_MEMORY = "episodic_memory"
SECTION_RESEARCH_MEMORY = "research_memory"
SECTION_EXTERNAL_READ = "external_read_context"
SECTION_SPECIALIST = "specialist_context"
SECTION_GOVERNANCE = "governance"
SECTION_PROVENANCE = "provenance"

_REQUIRED_TOP_LEVEL = (
    "context_envelope_version",
    "wake_id",
    "trace_id",
    "agent",
    "role",
    "created_at",
    "governance",
    "provenance",
)

_REQUIRED_SECTIONS = (
    SECTION_DECISION,
    SECTION_OFFICE_TRUTH,
    SECTION_ACTIVE_INTENT,
    SECTION_EPISODIC_MEMORY,
    SECTION_RESEARCH_MEMORY,
    SECTION_EXTERNAL_READ,
    SECTION_SPECIALIST,
    SECTION_GOVERNANCE,
    SECTION_PROVENANCE,
)

# ── Secret redaction patterns (over-broad is safer than under-broad) ──────
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|credential|"
    r"authorization|bearer|private[_-]?key|session[_-]?cookie|"
    r"access[_-]?key|refresh[_-]?token)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[a-z0-9]{8,}|ghp_[a-z0-9]{10,}|xox[baprs]-[a-z0-9-]{8,}|"
    r"AKIA[0-9A-Z]{16}|[0-9a-f]{32,})"
)
_REDACTED = "[REDACTED]"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for digests. Sorted keys, compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str, n: int = 32) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def redact_secrets(value: Any) -> Any:
    """Recursively redact credential-shaped keys and values.

    Never mutates the input. Returns a deep copy with secrets removed.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)):
                out[str(k)] = _REDACTED
            else:
                out[str(k)] = redact_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        if _SECRET_KEY_RE.search(value) or _SECRET_VALUE_RE.search(value):
            return _REDACTED
        return value
    return value


def _empty_decision() -> dict[str, Any]:
    return {
        "decision_id": None,
        "decision_input_digest": None,
        "decision_evidence_digest": None,
        "standing_recommendation": None,
        "current_action": None,
        "actionability": None,
        "act_now": False,
        "freshness": None,
    }


def _empty_office_truth() -> dict[str, Any]:
    return {
        "holdings_ref": None,
        "cash_ref": None,
        "portfolio_ref": None,
        "risk_ref": None,
        "policy_ref": None,
        "tax_ref": None,
        "source_asof": None,
        "truth_digest": None,
    }


def _empty_active_intent() -> dict[str, Any]:
    return {
        "thesis_id": None,
        "thesis_version": None,
        "open_goal_ids": [],
        "plan_ids": [],
        "current_constraints": {},
    }


def _empty_memory(provider: Optional[str]) -> dict[str, Any]:
    return {
        "query": None,
        "memory_ids": [],
        "records": [],
        "conflicts": [],
        "retrieval_status": RETRIEVAL_NOT_CONFIGURED if not provider else RETRIEVAL_EMPTY,
        "provider": provider,
    }


def _empty_research() -> dict[str, Any]:
    return {
        "case_ids": [],
        "lesson_ids": [],
        "hypothesis_ids": [],
        "research_refs": [],
        "counterevidence_refs": [],
        "retrieval_status": RETRIEVAL_NOT_CONFIGURED,
    }


def _empty_external() -> dict[str, Any]:
    return {
        "mcp_calls": [],
        "calendar_refs": [],
        "document_refs": [],
        "availability": RETRIEVAL_NOT_CONFIGURED,
    }


def _empty_specialist() -> dict[str, Any]:
    return {
        "prior_views": [],
        "requested_views": [],
    }


def _governance() -> dict[str, Any]:
    return {
        "authority": AUTHORITY_READ_ONLY_ADVISORY,
        "permitted_capabilities": [],
        "denied_capabilities": [],
        "freshness_rules": {
            "stale_never_act_now": True,
            "blocking_actions": ["DATA_CONFLICT", "STALE_REFRESH_REQUIRED", "REVALIDATE"],
        },
        "memory_authority": MEMORY_AUTHORITY_NON_AUTHORITATIVE,
    }


def build_context_envelope(
    *,
    agent: str,
    role: str,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    trigger: Optional[str] = None,
    trigger_type: Optional[str] = None,
    trigger_digest: Optional[str] = None,
    decision: Optional[dict[str, Any]] = None,
    office_truth: Optional[dict[str, Any]] = None,
    active_intent: Optional[dict[str, Any]] = None,
    episodic_memory: Optional[dict[str, Any]] = None,
    research_memory: Optional[dict[str, Any]] = None,
    external_read_context: Optional[dict[str, Any]] = None,
    specialist_context: Optional[dict[str, Any]] = None,
    permitted_capabilities: Optional[list[str]] = None,
    denied_capabilities: Optional[list[str]] = None,
    source_refs: Optional[list[str]] = None,
    memory_provider: Optional[str] = None,
) -> dict[str, Any]:
    """Build a ContextEnvelope@v1.

    Missing canonical providers are represented explicitly (NOT_CONFIGURED)
    rather than silently omitted. Memory is always separated from truth.
    """
    wake_id = wake_id or ""
    trace_id = trace_id or (f"tr_{wake_id}" if wake_id else "")

    decision = dict(decision or {})
    decision_merged = _empty_decision()
    decision_merged.update(decision)

    office_truth = dict(office_truth or {})
    office_truth_merged = _empty_office_truth()
    office_truth_merged.update(office_truth)

    active_intent = dict(active_intent or {})
    active_intent_merged = _empty_active_intent()
    active_intent_merged.update(active_intent)

    episodic_memory = dict(episodic_memory or {})
    episodic_merged = _empty_memory(memory_provider)
    episodic_merged.update(episodic_memory)

    research_memory = dict(research_memory or {})
    research_merged = _empty_research()
    research_merged.update(research_memory)

    external_read_context = dict(external_read_context or {})
    external_merged = _empty_external()
    external_merged.update(external_read_context)

    specialist_context = dict(specialist_context or {})
    specialist_merged = _empty_specialist()
    specialist_merged.update(specialist_context)

    governance = _governance()
    if permitted_capabilities is not None:
        governance["permitted_capabilities"] = list(permitted_capabilities)
    if denied_capabilities is not None:
        governance["denied_capabilities"] = list(denied_capabilities)

    envelope: dict[str, Any] = {
        "context_envelope_version": CONTEXT_ENVELOPE_VERSION,
        "wake_id": wake_id,
        "trace_id": trace_id,
        "agent": str(agent or ""),
        "role": str(role or ""),
        "trigger": trigger,
        "trigger_type": trigger_type,
        "trigger_digest": trigger_digest,
        "created_at": _now_iso(),
        SECTION_DECISION: decision_merged,
        SECTION_OFFICE_TRUTH: office_truth_merged,
        SECTION_ACTIVE_INTENT: active_intent_merged,
        SECTION_EPISODIC_MEMORY: episodic_merged,
        SECTION_RESEARCH_MEMORY: research_merged,
        SECTION_EXTERNAL_READ: external_merged,
        SECTION_SPECIALIST: specialist_merged,
        SECTION_GOVERNANCE: governance,
        SECTION_PROVENANCE: {
            "context_digest": None,
            "source_refs": list(source_refs or []),
            "built_at": _now_iso(),
        },
    }
    envelope[SECTION_PROVENANCE]["context_digest"] = context_envelope_digest(envelope)
    return envelope


def context_envelope_digest(envelope: dict[str, Any]) -> str:
    """Stable content digest of a ContextEnvelope.

    Timestamps (created_at / built_at) and the digest field itself are
    excluded so that materially-identical envelopes hash identically and any
    material change yields a new digest.
    """
    body = {
        "version": envelope.get("context_envelope_version"),
        "wake_id": envelope.get("wake_id"),
        "trace_id": envelope.get("trace_id"),
        "agent": envelope.get("agent"),
        "role": envelope.get("role"),
        "trigger": envelope.get("trigger"),
        "trigger_type": envelope.get("trigger_type"),
        "trigger_digest": envelope.get("trigger_digest"),
        "decision": _digest_section(envelope, SECTION_DECISION),
        "office_truth": _digest_section(envelope, SECTION_OFFICE_TRUTH),
        "active_intent": _digest_section(envelope, SECTION_ACTIVE_INTENT),
        "episodic_memory": _digest_section(envelope, SECTION_EPISODIC_MEMORY),
        "research_memory": _digest_section(envelope, SECTION_RESEARCH_MEMORY),
        "external_read_context": _digest_section(envelope, SECTION_EXTERNAL_READ),
        "specialist_context": _digest_section(envelope, SECTION_SPECIALIST),
        "governance": _digest_section(envelope, SECTION_GOVERNANCE),
    }
    raw = canonical_json(body)
    return "ctx_" + sha256_hex(raw, 16)


def _digest_section(envelope: dict[str, Any], section: str) -> Any:
    return envelope.get(section) or {}


def validate_context_envelope(envelope: Any) -> tuple[bool, list[str]]:
    """Schema-validate a ContextEnvelope@v1. Returns (ok, errors)."""
    errors: list[str] = []
    if not isinstance(envelope, dict):
        return False, ["envelope is not a dict"]
    for key in _REQUIRED_TOP_LEVEL:
        if key not in envelope:
            errors.append(f"missing top-level field: {key}")
    if envelope.get("context_envelope_version") != CONTEXT_ENVELOPE_VERSION:
        errors.append(
            f"bad context_envelope_version: {envelope.get('context_envelope_version')!r}"
        )
    for section in _REQUIRED_SECTIONS:
        if section not in envelope or not isinstance(envelope.get(section), dict):
            errors.append(f"missing/invalid section: {section}")
    gov = envelope.get(SECTION_GOVERNANCE) if isinstance(envelope, dict) else None
    if isinstance(gov, dict):
        if gov.get("authority") != AUTHORITY_READ_ONLY_ADVISORY:
            errors.append(f"bad governance.authority: {gov.get('authority')!r}")
        if gov.get("memory_authority") != MEMORY_AUTHORITY_NON_AUTHORITATIVE:
            errors.append(f"bad governance.memory_authority: {gov.get('memory_authority')!r}")
    prov = envelope.get(SECTION_PROVENANCE) if isinstance(envelope, dict) else None
    if isinstance(prov, dict):
        want = context_envelope_digest(envelope)
        if prov.get("context_digest") not in (None, want):
            errors.append("provenance.context_digest does not match recomputed digest")
    return (len(errors) == 0, errors)


# ── get_context_for_agent(): the single chokepoint ─────────────────────────


def get_context_for_agent(
    *,
    agent: str,
    wake: Optional[dict[str, Any]] = None,
    decision: Optional[dict[str, Any]] = None,
    symbols: Optional[list[str]] = None,
    plan_id: Optional[str] = None,
    required_domains: Optional[list[str]] = None,
    office_truth: Optional[dict[str, Any]] = None,
    active_intent: Optional[dict[str, Any]] = None,
    memory_provider: Optional[Any] = None,
    research_memory: Optional[dict[str, Any]] = None,
    external_read_context: Optional[dict[str, Any]] = None,
    specialist_context: Optional[dict[str, Any]] = None,
    source_refs: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a ContextEnvelope for a given agent + wake.

    This is the single chokepoint all agent reasoning should migrate toward.
    It deliberately does NOT invent truth: canonical inputs (office_truth,
    decision) are passed through verbatim and stamped with their own source
    refs; memory and MCP context are separated and fail-soft (NOT_CONFIGURED /
    UNAVAILABLE) when providers are absent.

    Memory providers are consulted via a narrow, duck-typed protocol
    (``search``/``health``) so Phase 4 can drop in NullMemoryProvider /
    Mem0MemoryProvider without touching this signature.
    """
    wake = wake or {}
    role = _infer_role(agent, wake)
    trigger = wake.get("trigger") or wake.get("reason") or None
    trigger_type = wake.get("trigger_type") or wake.get("source") or None
    trigger_digest = wake.get("trigger_digest") or None
    wake_id = str(wake.get("wake_id") or wake.get("wake_job_id") or "")
    trace_id = str(wake.get("trace_id") or "") or None

    episodic_memory = _retrieve_episodic(memory_provider, symbols=symbols, plan_id=plan_id)
    research_merged = dict(research_memory or {})
    research_merged.setdefault(
        "retrieval_status",
        RETRIEVAL_OK if research_merged else RETRIEVAL_NOT_CONFIGURED,
    )

    ext = dict(external_read_context or {})
    ext.setdefault("availability", RETRIEVAL_OK if ext.get("mcp_calls") else RETRIEVAL_NOT_CONFIGURED)

    return build_context_envelope(
        agent=agent,
        role=role,
        wake_id=wake_id,
        trace_id=trace_id,
        trigger=trigger,
        trigger_type=trigger_type,
        trigger_digest=trigger_digest,
        decision=decision,
        office_truth=office_truth,
        active_intent=active_intent,
        episodic_memory=episodic_memory,
        research_memory=research_merged,
        external_read_context=ext,
        specialist_context=specialist_context,
        source_refs=source_refs,
        memory_provider=_provider_name(memory_provider),
    )


def _infer_role(agent: str, wake: dict[str, Any]) -> str:
    role = str(wake.get("role") or wake.get("target_agent") or "")
    if role:
        return role
    # Alex is the default CIO synthesis role; specialists are delegated.
    agent_l = str(agent).lower()
    if "guardian" in agent_l:
        return "risk_guardian"
    if "ledger" in agent_l:
        return "ledger"
    if "steph" in agent_l or "maria" in agent_l:
        return "specialist"
    return "cio_synthesis"


def _provider_name(provider: Optional[Any]) -> Optional[str]:
    if provider is None:
        return None
    return getattr(provider, "name", None) or type(provider).__name__


def _retrieve_episodic(
    provider: Optional[Any],
    *,
    symbols: Optional[list[str]] = None,
    plan_id: Optional[str] = None,
) -> dict[str, Any]:
    """Consult an optional memory provider. Fail-soft, never raises.

    Returns an episodic_memory section. When no provider is present the
    section is explicitly NOT_CONFIGURED (never silently "empty but consulted").
    """
    if provider is None:
        return _empty_memory(None)
    query = {"symbols": list(symbols or []), "plan_id": plan_id}
    try:
        health = getattr(provider, "health", lambda: False)()
        if not health:
            return {
                "query": query,
                "memory_ids": [],
                "records": [],
                "conflicts": [],
                "retrieval_status": RETRIEVAL_UNAVAILABLE,
                "provider": _provider_name(provider),
            }
        result = provider.search(query=query, symbols=symbols, plan_id=plan_id)
        records = list(result.get("records") or []) if isinstance(result, dict) else []
        return {
            "query": query,
            "memory_ids": [r.get("memory_id") for r in records if isinstance(r, dict)],
            "records": records,
            "conflicts": list(result.get("conflicts") or []) if isinstance(result, dict) else [],
            "retrieval_status": RETRIEVAL_OK if records else RETRIEVAL_EMPTY,
            "provider": _provider_name(provider),
        }
    except Exception as exc:  # noqa: BLE001 — fail-soft boundary
        return {
            "query": query,
            "memory_ids": [],
            "records": [],
            "conflicts": [],
            "retrieval_status": RETRIEVAL_ERROR,
            "provider": _provider_name(provider),
            "error": type(exc).__name__,
        }
