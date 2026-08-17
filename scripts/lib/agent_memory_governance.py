"""agent_memory_governance.py — MemoryRecord@v1 + admission & conflict rules (Phase 4).

READ_ONLY_ADVISORY. Memory is NON_AUTHORITATIVE_CONTEXT: it is never truth, never
policy, and never a price/holding/cash/risk/broker fact. This module enforces
that boundary at admission time (build_memory_record, admit_status) and at
retrieval time (resolve_conflict, retrieve_for_context).

Pure and deterministic. No broker / order / stop / 2FA / Telegram side effects.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.agent_context_envelope import (
    MEMORY_AUTHORITY_NON_AUTHORITATIVE,
    RETRIEVAL_EMPTY,
    RETRIEVAL_ERROR,
    RETRIEVAL_NOT_CONFIGURED,
    RETRIEVAL_OK,
    RETRIEVAL_UNAVAILABLE,
    canonical_json,
    redact_secrets,
    sha256_hex,
)

MEMORY_VERSION = "1.0"

# ── Memory types ───────────────────────────────────────────────────────────
MEMORY_TYPE_EPISODIC = "EPISODIC"
MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE = "OPERATOR_EXPLICIT_PREFERENCE"
MEMORY_TYPE_OPERATOR_INFERRED_PREFERENCE = "OPERATOR_INFERRED_PREFERENCE"
MEMORY_TYPE_AGENT_COMMITMENT = "AGENT_COMMITMENT"
MEMORY_TYPE_CASE_SUMMARY = "CASE_SUMMARY"
MEMORY_TYPE_RESEARCH_REFERENCE = "RESEARCH_REFERENCE"
MEMORY_TYPE_PROCEDURAL_HINT = "PROCEDURAL_HINT"

MEMORY_TYPES = (
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
    MEMORY_TYPE_OPERATOR_INFERRED_PREFERENCE,
    MEMORY_TYPE_AGENT_COMMITMENT,
    MEMORY_TYPE_CASE_SUMMARY,
    MEMORY_TYPE_RESEARCH_REFERENCE,
    MEMORY_TYPE_PROCEDURAL_HINT,
)

# ── Statuses ───────────────────────────────────────────────────────────────
STATUS_CANDIDATE = "CANDIDATE"
STATUS_ACTIVE = "ACTIVE"
STATUS_DISPUTED = "DISPUTED"
STATUS_EXPIRED = "EXPIRED"
STATUS_RETRACTED = "RETRACTED"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUS_REJECT = "REJECT"

# Types that may be admitted ACTIVE (explicit operator statement / agent
# commitment / durable case event), provided provenance is present.
_ADMIT_ACTIVE_TYPES = (
    MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
    MEMORY_TYPE_AGENT_COMMITMENT,
    MEMORY_TYPE_CASE_SUMMARY,
)

# ── Forbidden authoritative fields ────────────────────────────────────────
# A memory whose subject/field touches any of these is trying to speak about
# canonical financial truth (which memory can never override). Substrings are
# normalized (underscores/hyphens -> spaces) before matching with word
# boundaries, so "current_price" and "current price" both match.
FORBIDDEN_AUTHORITATIVE_FIELDS = (
    "current price",
    "price",
    "market value",
    "shares",
    "quantity",
    "position",
    "positions",
    "holding",
    "holdings",
    "cash",
    "cash balance",
    "tax balance",
    "risk limit",
    "broker auth state",
    "order state",
    "order status",
    "stop state",
    "stop status",
    "freshness",
    "freshness status",
    "policy",
    "policy config",
)


def _normalize_field(value: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(value).strip().lower())


def _build_forbidden_re(fields: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(f) for f in fields)
    return re.compile(r"\b(?:" + alternation + r")\b")


_FORBIDDEN_RE = _build_forbidden_re(FORBIDDEN_AUTHORITATIVE_FIELDS)

# Token-shaped literals that must never be admitted into memory.
_SECRET_SHAPED_RE = re.compile(
    r"(?i)(sk-[a-z0-9]{8,}|ghp_[a-z0-9]{10,}|xox[baprs]-[a-z0-9-]{8,}|"
    r"AKIA[0-9A-Z]{16}|[0-9a-f]{32,})"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _is_expired(record: dict[str, Any]) -> bool:
    if record.get("status") == STATUS_EXPIRED:
        return True
    exp = record.get("expires_at")
    if not exp:
        return False
    ts = _parse_ts(exp)
    return ts > 0 and ts < time.time()


def _estimate_tokens(record: dict[str, Any]) -> int:
    try:
        import json

        return max(1, len(json.dumps(record, sort_keys=True, default=str)) // 4)
    except (TypeError, ValueError):
        return 1


def _bound(records: list[dict[str, Any]], top_k: int, budget_tokens: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used = 0
    for r in records[:top_k]:
        t = _estimate_tokens(r)
        if budget_tokens and used + t > budget_tokens and out:
            break
        out.append(r)
        used += t
    return out


def _contains_secret(value: Any) -> bool:
    if value is None:
        return False
    s = str(value)
    if _SECRET_SHAPED_RE.search(s):
        return True
    return redact_secrets(s) != s


def _content_digest(subject: Any, content: Any) -> str:
    return sha256_hex(canonical_json({"subject": subject, "content": content}), 32)


# ── Authority boundary predicate ──────────────────────────────────────────


def is_forbidden_authoritative(subject_or_field: Any) -> bool:
    """True if a memory subject/field names canonical financial truth.

    Memory about price, cash, holdings, market value, risk limit, broker/order/
    stop state, freshness, or policy config must never be treated as a fact —
    canonical truth outranks memory, always.
    """
    if subject_or_field is None:
        return False
    norm = _normalize_field(subject_or_field)
    if not norm:
        return False
    return bool(_FORBIDDEN_RE.search(norm))


# ── MemoryRecord@v1 builder ───────────────────────────────────────────────


def build_memory_record(
    *,
    memory_type: str,
    subject: str,
    content: str,
    memory_id: Optional[str] = None,
    scope: Optional[dict[str, Any]] = None,
    symbols: Optional[list[str]] = None,
    decision_ids: Optional[list[str]] = None,
    plan_ids: Optional[list[str]] = None,
    case_ids: Optional[list[str]] = None,
    source_event_ids: Optional[list[str]] = None,
    source_refs: Optional[list[str]] = None,
    source_kind: Optional[str] = None,
    created_at: Optional[str] = None,
    valid_from: Optional[str] = None,
    expires_at: Optional[str] = None,
    last_confirmed_at: Optional[str] = None,
    confidence: float = 0.5,
    sensitivity: Optional[str] = None,
    status: str = STATUS_CANDIDATE,
    supersedes: Optional[list[str]] = None,
    contradicts: Optional[list[str]] = None,
    provider: str = "local",
) -> dict[str, Any]:
    """Build a MemoryRecord@v1, computing a deterministic content_digest.

    Raises ValueError when:
      * provenance is missing (both source_event_ids and source_refs empty), or
      * content/subject is secret- or token-shaped.

    Memory is always marked NON_AUTHORITATIVE_CONTEXT; admission never changes
    that authority class.
    """
    source_event_ids = list(source_event_ids or [])
    source_refs = list(source_refs or [])
    if not source_event_ids and not source_refs:
        raise ValueError(
            "memory record requires provenance: source_event_ids or source_refs must be non-empty"
        )
    if _contains_secret(content) or _contains_secret(subject):
        raise ValueError(
            "memory record content/subject contains secret- or token-shaped text; admission rejected"
        )
    content_digest = _content_digest(subject, content)
    memory_id = memory_id or ("mem_" + content_digest)
    return {
        "memory_version": MEMORY_VERSION,
        "memory_id": memory_id,
        "memory_type": memory_type,
        "scope": scope or {},
        "subject": subject,
        "symbols": list(symbols or []),
        "decision_ids": list(decision_ids or []),
        "plan_ids": list(plan_ids or []),
        "case_ids": list(case_ids or []),
        "content": content,
        "source_event_ids": source_event_ids,
        "source_refs": source_refs,
        "source_kind": source_kind,
        "created_at": created_at or _now_iso(),
        "valid_from": valid_from,
        "expires_at": expires_at,
        "last_confirmed_at": last_confirmed_at,
        "confidence": confidence,
        "authority_class": MEMORY_AUTHORITY_NON_AUTHORITATIVE,
        "sensitivity": sensitivity,
        "status": status,
        "supersedes": list(supersedes or []),
        "contradicts": list(contradicts or []),
        "content_digest": content_digest,
        "provider": provider,
    }


# ── Admission policy ──────────────────────────────────────────────────────


def admit_status(
    memory_type: str,
    *,
    subject: Optional[str] = None,
    source_kind: Optional[str] = None,
    provenance_ok: bool = True,
) -> str:
    """Return the status a memory may be admitted under.

      * No provenance -> REJECT.
      * Forbidden-authoritative subject -> REJECT (memory may not speak to
        price/cash/holdings/risk/broker facts).
      * Explicit operator statement / agent commitment / durable case event ->
        ACTIVE.
      * Inferred preference, episodic recollection, research reference, or
        procedural hint -> CANDIDATE (context only, never policy).
    """
    if not provenance_ok:
        return STATUS_REJECT
    if subject is not None and is_forbidden_authoritative(subject):
        return STATUS_REJECT
    if memory_type in _ADMIT_ACTIVE_TYPES:
        return STATUS_ACTIVE
    return STATUS_CANDIDATE


# ── Conflict resolution ───────────────────────────────────────────────────

_PRIORITY = {
    MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE: 3,
    MEMORY_TYPE_AGENT_COMMITMENT: 2,
    MEMORY_TYPE_CASE_SUMMARY: 2,
    MEMORY_TYPE_OPERATOR_INFERRED_PREFERENCE: 1,
    MEMORY_TYPE_EPISODIC: 0,
    MEMORY_TYPE_RESEARCH_REFERENCE: 0,
    MEMORY_TYPE_PROCEDURAL_HINT: 0,
}


def _pick_primary(records: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not records:
        return None
    return sorted(
        records,
        key=lambda r: (
            -_PRIORITY.get(r.get("memory_type"), 0),
            -_recency(r),
            str(r.get("memory_id", "")),
        ),
    )[0]


def _recency(record: dict[str, Any]) -> float:
    return max(_parse_ts(record.get("valid_from")), _parse_ts(record.get("created_at")))


def resolve_conflict(
    memories: list[dict[str, Any]],
    canonical_truth_override: bool = False,
) -> dict[str, Any]:
    """Resolve a set of memory records into primary context + conflict metadata.

    Rules:
      * Canonical truth always wins — when ``canonical_truth_override`` is True,
        no memory becomes primary.
      * Newer explicit operator preference supersedes older explicit preference.
      * Disputed memories remain visible as conflict metadata, not primary.
      * Expired / retracted / superseded memories are excluded from primary.
    """
    recs = [m for m in memories if isinstance(m, dict)]
    expired = [m for m in recs if _is_expired(m)]
    superseded = [m for m in recs if m.get("status") in (STATUS_SUPERSEDED, STATUS_RETRACTED)]
    disputed = [m for m in recs if m.get("status") == STATUS_DISPUTED]
    primary_pool = [m for m in recs if m not in expired and m not in superseded and m not in disputed]
    primary = None if canonical_truth_override else _pick_primary(primary_pool)
    conflicts: list[dict[str, Any]] = []
    for m in disputed:
        conflicts.append(
            {
                "memory_id": m.get("memory_id"),
                "reason": m.get("dispute_reason"),
                "subject": m.get("subject"),
            }
        )
    return {
        "primary": primary,
        "conflicts": conflicts,
        "excluded_expired": [m.get("memory_id") for m in expired],
        "excluded_superseded": [m.get("memory_id") for m in superseded],
        "canonical_truth_override": bool(canonical_truth_override),
    }


# ── Retrieval for context ─────────────────────────────────────────────────


def _empty_result(query: Any, symbols: Any, scope: Any, provider_name: Optional[str], status: str, error: Optional[str] = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "query": query,
        "symbols": list(symbols or []),
        "scope": scope,
        "supporting": [],
        "counter_memory": [],
        "conflicts": [],
        "retrieval_status": status,
        "provider": provider_name,
    }
    if error is not None:
        out["error"] = error
    return out


def retrieve_for_context(
    memory_provider: Any,
    *,
    query: Any,
    symbols: Optional[list[str]] = None,
    scope: Optional[dict[str, Any]] = None,
    top_k: int = 8,
    budget_tokens: int = 1500,
) -> dict[str, Any]:
    """Retrieve supporting + counter-memory for a context, fail-soft.

    A missing provider is NOT_CONFIGURED; a broken/malformed provider is ERROR.
    Expired/retracted/superseded records are dropped from supporting context;
    disputed records are surfaced as conflicts. Output is bounded by top_k and
    an approximate token budget.
    """
    provider_name = None
    if memory_provider is not None:
        provider_name = getattr(memory_provider, "name", None) or type(memory_provider).__name__
    if memory_provider is None:
        return _empty_result(query, symbols, scope, None, RETRIEVAL_NOT_CONFIGURED)

    try:
        health = memory_provider.health()
    except Exception as exc:  # noqa: BLE001 — fail-soft boundary
        return _empty_result(query, symbols, scope, provider_name, RETRIEVAL_ERROR, type(exc).__name__)

    if isinstance(health, dict):
        hstatus = health.get("status")
        if hstatus in ("NOT_CONFIGURED", RETRIEVAL_NOT_CONFIGURED):
            return _empty_result(query, symbols, scope, provider_name, RETRIEVAL_NOT_CONFIGURED)
    elif not health:
        return _empty_result(query, symbols, scope, provider_name, RETRIEVAL_UNAVAILABLE)

    try:
        result = memory_provider.search(
            query=query, scope=scope, symbols=symbols, top_k=top_k, budget_tokens=budget_tokens
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft boundary
        return _empty_result(query, symbols, scope, provider_name, RETRIEVAL_ERROR, type(exc).__name__)

    if not isinstance(result, dict):
        return _empty_result(query, symbols, scope, provider_name, RETRIEVAL_ERROR, "MalformedResponse")

    supporting = [r for r in (result.get("supporting") or result.get("records") or []) if isinstance(r, dict)]
    counter = [r for r in (result.get("counter_memory") or result.get("counter") or []) if isinstance(r, dict)]
    # Defensive re-filter: never put expired/retracted/superseded into primary.
    supporting = [r for r in supporting if not _is_expired(r) and r.get("status") not in (STATUS_RETRACTED, STATUS_SUPERSEDED)]
    supporting = _bound(supporting, top_k, budget_tokens)
    counter = _bound(counter, top_k, budget_tokens)

    conflicts = list(result.get("conflicts") or []) if isinstance(result.get("conflicts"), list) else []
    for r in counter:
        if r.get("status") == STATUS_DISPUTED:
            conflicts.append({"memory_id": r.get("memory_id"), "reason": r.get("dispute_reason")})

    status = result.get("retrieval_status")
    if status not in (RETRIEVAL_OK, RETRIEVAL_EMPTY, RETRIEVAL_NOT_CONFIGURED, RETRIEVAL_UNAVAILABLE, RETRIEVAL_ERROR):
        status = RETRIEVAL_OK if (supporting or counter) else RETRIEVAL_EMPTY

    return {
        "query": query,
        "symbols": list(symbols or []),
        "scope": scope,
        "supporting": supporting,
        "counter_memory": counter,
        "conflicts": conflicts,
        "retrieval_status": status,
        "provider": provider_name,
    }
