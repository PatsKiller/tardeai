"""Controlled curation for CommunicationEvent (Phase 5).

Default DETERMINISTIC. LLMs only for approved classes. Protected facts
(prices, quantities, accounts, risk limits, approvals, timestamps,
authorities) must never be mutated by LLM output — any mutation forces
DETERMINISTIC FALLBACK with failure evidence on CurationReceipt.

This module never calls real LLM APIs. Callers supply precomputed curated
text to ``apply_llm_curation_result``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.comms.identity import protected_facts_hash_for

# ---------------------------------------------------------------------------
# Curation modes
# ---------------------------------------------------------------------------

DETERMINISTIC = "DETERMINISTIC"
TEMPLATE = "TEMPLATE"
LLM_SUMMARY = "LLM_SUMMARY"
LLM_CHALLENGE = "LLM_CHALLENGE"
HUMAN_EDIT = "HUMAN_EDIT"

VALID_CURATION_MODES = (
    DETERMINISTIC,
    TEMPLATE,
    LLM_SUMMARY,
    LLM_CHALLENGE,
    HUMAN_EDIT,
)

FALLBACK_REASON_PROTECTED_FACT_MUTATION = "protected_fact_mutation"
FALLBACK_REASON_CURATION_UNAVAILABLE = "CURATION_UNAVAILABLE"
POLICY_ALLOW = "allow"
POLICY_DENY_DETERMINISTIC = "deny_deterministic"
POLICY_FALLBACK_DETERMINISTIC = "fallback_deterministic"

# ---------------------------------------------------------------------------
# Tier policy (message_class → allowed modes)
# ---------------------------------------------------------------------------

# Tier 0 — never LLM: approvals, protection, broker/account facts, orders,
# health, outages, thresholds, audit notices.
TIER0_DETERMINISTIC_CLASSES = frozenset(
    {
        "approval",
        "protection_incident",
        "broker_fact",
        "order_state",
        "risk_limit",
        "account_fact",
        "health",
        "outage",
        "threshold",
        "audit_notice",
        "operator_alert",
    }
)

# Tier 1 — template composition of deterministic facts.
TIER1_TEMPLATE_CLASSES = frozenset(
    {
        "digest",
        "digest_item",
        "status_report",
        "ops_summary",
    }
)

# Tier 2 — LLM_SUMMARY allowed (research / advisory narrative only).
TIER2_LLM_SUMMARY_CLASSES = frozenset(
    {
        "research",
        "research_brief",
        "advisory",
        "advisory_recommendation",
        "thesis_update",
        "intelligence_summary",
    }
)

# Tier 3 — LLM_CHALLENGE when novelty/conflict flags are set (subset of Tier 2).
TIER3_CHALLENGE_CLASSES = frozenset(
    {
        "research",
        "research_brief",
        "advisory",
        "advisory_recommendation",
        "thesis_update",
    }
)

# Keys (and nested keys) that LLM curation must not alter.
PROTECTED_FACT_KEYS = frozenset(
    {
        "price",
        "prices",
        "quantity",
        "quantities",
        "qty",
        "size",
        "notional",
        "account",
        "account_id",
        "accounts",
        "portfolio_id",
        "risk_limit",
        "risk_limits",
        "limit",
        "limits",
        "approval",
        "approval_id",
        "authorization_or_order_id",
        "order_id",
        "intent_id",
        "action_token",
        "timestamp",
        "timestamps",
        "observed_at",
        "created_at",
        "expires_at",
        "authority",
        "authorities",
        "signed_intent",
        "operator_action_required",
        "operator_action_type",
    }
)

# In-process receipt store (optional light persistence for tests / dry runs).
_RECEIPTS: dict[str, "CurationReceipt"] = {}
_receipt_lock = threading.Lock()


def _stable_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash_material(obj: Any) -> str:
    return hashlib.sha256(_stable_dumps(obj).encode("utf-8")).hexdigest()


def extract_protected_subset(facts: dict[str, Any] | None) -> dict[str, Any]:
    """Return nested dict containing only PROTECTED_FACT_KEYS (deep)."""
    if not facts:
        return {}

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in PROTECTED_FACT_KEYS:
                    out[k] = copy.deepcopy(v)
                elif isinstance(v, (dict, list)):
                    nested = _walk(v)
                    if nested not in (None, {}, []):
                        out[k] = nested
            return out
        if isinstance(node, list):
            items = []
            for item in node:
                nested = _walk(item)
                if nested not in (None, {}, []):
                    items.append(nested)
            return items
        return None

    result = _walk(facts)
    return result if isinstance(result, dict) else {}


def preserve_protected_facts(before: dict, after: dict) -> bool:
    """Deep-compare protected keys between before/after fact dicts."""
    return extract_protected_subset(before) == extract_protected_subset(after)


@dataclass
class CurationReceipt:
    """CurationReceipt@v1 — provenance for how a message body was produced."""

    curation_mode: str
    provider: str | None = None
    model: str | None = None
    prompt_template_id: str | None = None
    prompt_template_version: str | None = None
    input_hashes: dict[str, str] = field(default_factory=dict)
    output_hash: str | None = None
    retrieved_context_ids: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    token_cost: float | None = None
    fallback_reason: str | None = None
    fact_preservation_ok: bool = True
    protected_facts_before_hash: str | None = None
    protected_facts_after_hash: str | None = None
    policy_decision: str = POLICY_ALLOW
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_curation_mode(
    message_class: str,
    *,
    novelty: bool = False,
    conflict: bool = False,
) -> str:
    """Choose curation mode from message_class and optional challenge flags.

    Default is DETERMINISTIC. LLM modes only for approved Tier 2/3 classes.
    """
    cls = (message_class or "").strip()
    if not cls or cls in TIER0_DETERMINISTIC_CLASSES:
        return DETERMINISTIC
    if cls in TIER3_CHALLENGE_CLASSES and (novelty or conflict):
        return LLM_CHALLENGE
    if cls in TIER2_LLM_SUMMARY_CLASSES:
        return LLM_SUMMARY
    if cls in TIER1_TEMPLATE_CLASSES:
        return TEMPLATE
    return DETERMINISTIC


def _body_fields(
    *,
    sanitized_body: str | None,
    short_summary: str | None,
    curation_mode: str,
    protected_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "sanitized_body": sanitized_body,
        "short_summary": short_summary,
        "curation_mode": curation_mode,
        "protected_facts": copy.deepcopy(protected_facts or {}),
    }


def curate_deterministic(
    event: CommunicationEvent,
    *,
    template: str | None = None,
) -> tuple[dict[str, Any], CurationReceipt]:
    """Produce body fields without LLM. Optional simple template fill."""
    facts = dict(event.protected_facts or {})
    before_hash = protected_facts_hash_for(facts)

    if template:
        try:
            body = template.format(
                sanitized_body=event.sanitized_body or "",
                short_summary=event.short_summary or "",
                subject_key=event.subject_key,
                event_type=event.event_type,
                message_class=event.message_class,
                **{k: v for k, v in facts.items() if isinstance(v, (str, int, float, bool))},
            )
        except (KeyError, ValueError):
            body = event.sanitized_body or template
        mode = TEMPLATE
        template_id = "inline_template"
        template_version = "1"
    else:
        body = event.sanitized_body or ""
        if facts and not body:
            # Stable deterministic rendering of protected facts only.
            body = _stable_dumps(facts)
        mode = DETERMINISTIC
        template_id = None
        template_version = None

    summary = event.short_summary or (body[:160] if body else None)
    output_hash = _hash_material({"sanitized_body": body, "short_summary": summary})
    receipt = CurationReceipt(
        curation_mode=mode,
        provider=None,
        model=None,
        prompt_template_id=template_id,
        prompt_template_version=template_version,
        input_hashes={
            "protected_facts": before_hash,
            "sanitized_body": _hash_material(event.sanitized_body or ""),
        },
        output_hash=output_hash,
        retrieved_context_ids=[],
        latency_ms=0,
        token_cost=0.0,
        fallback_reason=None,
        fact_preservation_ok=True,
        protected_facts_before_hash=before_hash,
        protected_facts_after_hash=before_hash,
        policy_decision=POLICY_ALLOW,
        event_id=event.event_id,
    )
    body_out = _body_fields(
        sanitized_body=body,
        short_summary=summary,
        curation_mode=mode,
        protected_facts=facts,
    )
    return body_out, receipt


def apply_llm_curation_result(
    *,
    event: CommunicationEvent,
    curated_body: str,
    protected_facts_after: dict[str, Any] | None = None,
    provider: str | None = None,
    model: str | None = None,
    prompt_template_id: str | None = None,
    prompt_template_version: str | None = None,
    retrieved_context_ids: list[str] | None = None,
    latency_ms: int | None = None,
    token_cost: float | None = None,
    short_summary: str | None = None,
    requested_mode: str | None = None,
) -> tuple[dict[str, Any], CurationReceipt]:
    """Accept precomputed LLM text; fall back if protected facts mutated.

    Does not call any LLM. If ``protected_facts_after`` mutates protected keys
    relative to ``event.protected_facts``, force DETERMINISTIC FALLBACK,
    restore facts from before, and record failure evidence on the receipt.
    """
    facts_before = dict(event.protected_facts or {})
    facts_after = dict(
        protected_facts_after if protected_facts_after is not None else facts_before
    )
    before_hash = protected_facts_hash_for(facts_before)
    after_hash = protected_facts_hash_for(facts_after)
    ok = preserve_protected_facts(facts_before, facts_after)

    mode = requested_mode or select_curation_mode(event.message_class)
    # Tier 0 always deterministic — requested LLM mode cannot override.
    if event.message_class in TIER0_DETERMINISTIC_CLASSES:
        body, receipt = curate_deterministic(event)
        receipt.policy_decision = POLICY_DENY_DETERMINISTIC
        receipt.fallback_reason = FALLBACK_REASON_CURATION_UNAVAILABLE
        receipt.provider = provider
        receipt.model = model
        receipt.input_hashes["requested_mode"] = _hash_material(mode)
        receipt.protected_facts_before_hash = before_hash
        receipt.protected_facts_after_hash = after_hash
        if not ok:
            receipt.fact_preservation_ok = False
            receipt.fallback_reason = FALLBACK_REASON_PROTECTED_FACT_MUTATION
            receipt.policy_decision = POLICY_FALLBACK_DETERMINISTIC
            body["protected_facts"] = copy.deepcopy(facts_before)
        return body, receipt

    if not ok:
        # Restore protected facts; use deterministic body; evidence on receipt.
        restored = copy.deepcopy(facts_before)
        det_body, det_receipt = curate_deterministic(event)
        det_receipt.curation_mode = DETERMINISTIC
        det_receipt.provider = provider
        det_receipt.model = model
        det_receipt.prompt_template_id = prompt_template_id
        det_receipt.prompt_template_version = prompt_template_version
        det_receipt.retrieved_context_ids = list(retrieved_context_ids or [])
        det_receipt.latency_ms = latency_ms
        det_receipt.token_cost = token_cost
        det_receipt.fallback_reason = FALLBACK_REASON_PROTECTED_FACT_MUTATION
        det_receipt.fact_preservation_ok = False
        det_receipt.protected_facts_before_hash = before_hash
        det_receipt.protected_facts_after_hash = after_hash
        det_receipt.policy_decision = POLICY_FALLBACK_DETERMINISTIC
        det_receipt.input_hashes = {
            "protected_facts_before": before_hash,
            "protected_facts_after": after_hash,
            "curated_body_rejected": _hash_material(curated_body or ""),
        }
        det_receipt.event_id = event.event_id
        body_out = _body_fields(
            sanitized_body=det_body["sanitized_body"],
            short_summary=det_body["short_summary"],
            curation_mode=DETERMINISTIC,
            protected_facts=restored,
        )
        return body_out, det_receipt

    summary = short_summary
    if summary is None:
        summary = (curated_body or "")[:160] or event.short_summary
    output_hash = _hash_material(
        {"sanitized_body": curated_body, "short_summary": summary}
    )
    receipt = CurationReceipt(
        curation_mode=mode if mode in (LLM_SUMMARY, LLM_CHALLENGE, HUMAN_EDIT) else LLM_SUMMARY,
        provider=provider,
        model=model,
        prompt_template_id=prompt_template_id,
        prompt_template_version=prompt_template_version,
        input_hashes={
            "protected_facts": before_hash,
            "source_body": _hash_material(event.sanitized_body or ""),
        },
        output_hash=output_hash,
        retrieved_context_ids=list(retrieved_context_ids or []),
        latency_ms=latency_ms,
        token_cost=token_cost,
        fallback_reason=None,
        fact_preservation_ok=True,
        protected_facts_before_hash=before_hash,
        protected_facts_after_hash=after_hash,
        policy_decision=POLICY_ALLOW,
        event_id=event.event_id,
    )
    body_out = _body_fields(
        sanitized_body=curated_body,
        short_summary=summary,
        curation_mode=receipt.curation_mode,
        protected_facts=facts_after,
    )
    return body_out, receipt


def store_curation_receipt(event_id: str, receipt: CurationReceipt) -> None:
    """Persist receipt in the in-process memory map keyed by event_id."""
    if not event_id:
        raise ValueError("event_id required to store curation receipt")
    receipt.event_id = event_id
    with _receipt_lock:
        _RECEIPTS[event_id] = receipt


def get_curation_receipt(event_id: str) -> CurationReceipt | None:
    with _receipt_lock:
        return _RECEIPTS.get(event_id)


def reset_curation_receipts() -> None:
    """Test helper: clear in-process receipt store."""
    with _receipt_lock:
        _RECEIPTS.clear()


def memory_receipts_snapshot() -> dict[str, dict[str, Any]]:
    with _receipt_lock:
        return {k: v.to_dict() for k, v in _RECEIPTS.items()}
