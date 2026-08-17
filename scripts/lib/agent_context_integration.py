"""agent_context_integration.py — Context-aware agent integration (Phase 5).

READ_ONLY_ADVISORY. SHADOW-COMPARE ONLY.

This module builds the adapters + helpers that let Alex and the specialists
reason on *scoped*, *budgeted*, *honest* context — WITHOUT changing any live
Alex/specialist behavior. Nothing here mutates a decision, a store, a broker,
or a policy. The only "output" that matters is a shadow diff: did the extra
context change what the agent would do?

What it provides:

  * ``SPECIALIST_SCOPES``          — which content domains each specialist may see
  * ``build_specialist_sub_envelope`` — a scoped, trace-linked sub-envelope
  * ``record_retrieval_before_reasoning`` — honest retrieval markers recorded
    BEFORE synthesis (never pretend the agent had full context)
  * ``CONTEXT_BUDGET_ORDER`` + ``apply_context_budget`` — deterministic
    truncation that drops lowest-priority context first and never drops
    canonical truth
  * ``shadow_compare``             — an explicit baseline-vs-augmented diff report

All functions are pure, deterministic, fail-soft, and never raise on bad input.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.agent_context_envelope import (
    AUTHORITY_READ_ONLY_ADVISORY,
    RETRIEVAL_EMPTY,
    RETRIEVAL_ERROR,
    RETRIEVAL_NOT_CONFIGURED,
    RETRIEVAL_OK,
    RETRIEVAL_UNAVAILABLE,
    SECTION_ACTIVE_INTENT,
    SECTION_DECISION,
    SECTION_EPISODIC_MEMORY,
    SECTION_EXTERNAL_READ,
    SECTION_GOVERNANCE,
    SECTION_OFFICE_TRUTH,
    SECTION_PROVENANCE,
    SECTION_RESEARCH_MEMORY,
    SECTION_SPECIALIST,
    canonical_json,
    context_envelope_digest,
)

# ── Retrieval markers (surfaced BEFORE reasoning) ──────────────────────────
MARKER_MEMORY_NOT_CONSULTED = "MEMORY_NOT_CONSULTED"
MARKER_RESEARCH_UNAVAILABLE = "RESEARCH_UNAVAILABLE"
MARKER_MCP_NOT_AVAILABLE = "MCP_NOT_AVAILABLE"
MARKER_MEMORY_EMPTY = "MEMORY_EMPTY"

# ── Specialist scoping ─────────────────────────────────────────────────────
# Which content domains each specialist may see. Governance + provenance are
# STRUCTURAL (authority + trace linkage), never scoped away — they carry no
# content and are always copied. Unknown specialists are fail-closed (empty
# scope) so they receive no content domains at all.
SPECIALIST_SCOPES: dict[str, tuple[str, ...]] = {
    # risk guardian: truth + decision + constraints. No research, no external
    # read, no operator memory, no other-specialist views.
    "guardian": (
        SECTION_DECISION,
        SECTION_OFFICE_TRUTH,
        SECTION_ACTIVE_INTENT,
    ),
    # steph (research specialist): deep-research scope. Research + external
    # read; no operator memory, no other-specialist views.
    "steph": (
        SECTION_DECISION,
        SECTION_OFFICE_TRUTH,
        SECTION_ACTIVE_INTENT,
        SECTION_RESEARCH_MEMORY,
        SECTION_EXTERNAL_READ,
    ),
    # maria (front-door specialist): operator-communication scope. Operator
    # explicit memory + other specialist views + active thesis; no deep
    # research, no external read.
    "maria": (
        SECTION_DECISION,
        SECTION_ACTIVE_INTENT,
        SECTION_EPISODIC_MEMORY,
        SECTION_SPECIALIST,
    ),
    # ledger: canonical truth only. Decision + holdings/cash/tax truth; no
    # memory, no research, no external read, no specialist views.
    "ledger": (
        SECTION_DECISION,
        SECTION_OFFICE_TRUTH,
    ),
}

# The content domains that are subject to scoping. Governance + provenance are
# always copied regardless of scope.
_SCOPED_CONTENT_DOMAINS = (
    SECTION_DECISION,
    SECTION_OFFICE_TRUTH,
    SECTION_ACTIVE_INTENT,
    SECTION_EPISODIC_MEMORY,
    SECTION_RESEARCH_MEMORY,
    SECTION_EXTERNAL_READ,
    SECTION_SPECIALIST,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep(value: Any) -> Any:
    return deepcopy(value)


# ── Specialist sub-envelope ────────────────────────────────────────────────


def build_specialist_sub_envelope(
    parent_envelope: dict,
    specialist: str,
    question: str,
) -> dict[str, Any]:
    """Derive a scoped sub-envelope from a parent ContextEnvelope.

    Only the content domains allowed for ``specialist`` are copied; governance
    and provenance are always copied (authority + trace linkage). The result
    carries ``parent_wake_id`` / ``parent_trace_id`` for trace linkage and a
    ``subcontext_digest`` computed via ``context_envelope_digest`` on a
    deterministic projection (so the question + the scoped sections are what
    the digest covers).

    Unknown specialist names are fail-closed: they receive an empty content
    scope (identity + governance + provenance + the question only).
    """
    parent = parent_envelope if isinstance(parent_envelope, dict) else {}
    key = str(specialist or "").strip().lower()
    scope = SPECIALIST_SCOPES.get(key, ())
    wake_id = parent.get("wake_id")
    trace_id = parent.get("trace_id")

    sub: dict[str, Any] = {
        "context_envelope_version": parent.get("context_envelope_version"),
        "sub_envelope": True,
        "wake_id": wake_id,
        "trace_id": trace_id,
        "parent_wake_id": wake_id,
        "parent_trace_id": trace_id,
        "agent": parent.get("agent"),
        "specialist": key,
        "specialist_question": question,
        "created_at": _now_iso(),
    }

    for section in scope:
        if section in parent:
            sub[section] = _deep(parent[section])

    if SECTION_GOVERNANCE in parent:
        sub[SECTION_GOVERNANCE] = _deep(parent[SECTION_GOVERNANCE])
    prov = _deep(parent.get(SECTION_PROVENANCE)) if isinstance(parent.get(SECTION_PROVENANCE), dict) else {}
    sub[SECTION_PROVENANCE] = prov

    sub["subcontext_digest"] = context_envelope_digest(_sub_projection(sub, question))
    prov["subcontext_digest"] = sub["subcontext_digest"]
    return sub


def _sub_projection(sub: dict[str, Any], question: str) -> dict[str, Any]:
    """Deterministic projection the subcontext digest is computed over.

    The question is folded into ``trigger`` so distinct questions yield
    distinct subcontext digests. Missing sections become ``{}`` inside
    ``context_envelope_digest`` (deterministic).
    """
    return {
        "context_envelope_version": sub.get("context_envelope_version"),
        "wake_id": sub.get("wake_id"),
        "trace_id": sub.get("trace_id"),
        "agent": sub.get("agent"),
        "role": None,
        "trigger": question,
        "trigger_type": "SPECIALIST_QUESTION",
        "trigger_digest": None,
        SECTION_DECISION: sub.get(SECTION_DECISION),
        SECTION_OFFICE_TRUTH: sub.get(SECTION_OFFICE_TRUTH),
        SECTION_ACTIVE_INTENT: sub.get(SECTION_ACTIVE_INTENT),
        SECTION_EPISODIC_MEMORY: sub.get(SECTION_EPISODIC_MEMORY),
        SECTION_RESEARCH_MEMORY: sub.get(SECTION_RESEARCH_MEMORY),
        SECTION_EXTERNAL_READ: sub.get(SECTION_EXTERNAL_READ),
        SECTION_SPECIALIST: sub.get(SECTION_SPECIALIST),
        SECTION_GOVERNANCE: sub.get(SECTION_GOVERNANCE),
    }


# ── Retrieval status recorded BEFORE reasoning ─────────────────────────────

# Retrieval statuses that mean the source could not be consulted.
_MEMORY_NOT_CONSULTED_STATUSES = frozenset(
    {RETRIEVAL_NOT_CONFIGURED, RETRIEVAL_UNAVAILABLE, RETRIEVAL_ERROR}
)


def record_retrieval_before_reasoning(envelope: dict[str, Any]) -> dict[str, Any]:
    """Record honest retrieval status BEFORE final synthesis.

    Returns a copy of ``envelope`` (never mutates) with:
      * a ``retrieval_marker`` on the memory / research / external sections
      * a top-level ``retrieval_audit`` block listing markers + a
        ``full_context_available`` flag.

    If a source could not be retrieved it is marked explicitly
    (``MEMORY_NOT_CONSULTED`` / ``RESEARCH_UNAVAILABLE`` /
    ``MCP_NOT_AVAILABLE``) — the agent must never pretend it had full context.
    """
    env = _deep(envelope) if isinstance(envelope, dict) else {}
    env.setdefault(SECTION_EPISODIC_MEMORY, {})
    env.setdefault(SECTION_RESEARCH_MEMORY, {})
    env.setdefault(SECTION_EXTERNAL_READ, {})

    mem = env[SECTION_EPISODIC_MEMORY]
    research = env[SECTION_RESEARCH_MEMORY]
    external = env[SECTION_EXTERNAL_READ]

    mem_status = mem.get("retrieval_status")
    research_status = research.get("retrieval_status")
    ext_avail = external.get("availability")

    if mem_status in _MEMORY_NOT_CONSULTED_STATUSES:
        memory_marker: Optional[str] = MARKER_MEMORY_NOT_CONSULTED
    elif mem_status == RETRIEVAL_EMPTY:
        memory_marker = MARKER_MEMORY_EMPTY
    else:
        memory_marker = None

    research_marker: Optional[str]
    if research_status == RETRIEVAL_OK:
        research_marker = None
    else:
        research_marker = MARKER_RESEARCH_UNAVAILABLE

    mcp_marker: Optional[str]
    if ext_avail == RETRIEVAL_OK:
        mcp_marker = None
    else:
        mcp_marker = MARKER_MCP_NOT_AVAILABLE

    markers = [m for m in (memory_marker, research_marker, mcp_marker) if m]
    blockers = [m for m in markers if m != MARKER_MEMORY_EMPTY]

    if memory_marker:
        mem["retrieval_marker"] = memory_marker
    if research_marker:
        research["retrieval_marker"] = research_marker
    if mcp_marker:
        external["retrieval_marker"] = mcp_marker

    env["retrieval_audit"] = {
        "phase": "BEFORE_REASONING",
        "recorded_at": _now_iso(),
        "full_context_available": not blockers,
        "markers": markers,
        "sources": {
            "memory": {"retrieval_status": mem_status, "marker": memory_marker},
            "research": {"retrieval_status": research_status, "marker": research_marker},
            "external": {"availability": ext_avail, "marker": mcp_marker},
        },
    }
    return env


# ── Context budget ─────────────────────────────────────────────────────────

# Deterministic budget priority: HIGHEST first. Canonical truth is position 0
# and is NEVER dropped. Lower-confidence memory (the 7th conceptual priority)
# is dropped first *within* episodic_memory, before the section itself is
# dropped — see ``_drop_low_confidence_memory``.
CONTEXT_BUDGET_ORDER = (
    SECTION_OFFICE_TRUTH,     # 1 canonical truth — never dropped
    SECTION_DECISION,         # 2 decision / evidence
    SECTION_ACTIVE_INTENT,    # 3 active thesis / constraints
    SECTION_EPISODIC_MEMORY,  # 4 operator explicit memory
    SECTION_RESEARCH_MEMORY,  # 5 relevant cases / research
    SECTION_EXTERNAL_READ,    # 6 external read context
    # 7 lower-confidence memory — dropped first inside episodic_memory
)

LOW_CONFIDENCE_THRESHOLD = 0.5
_LOW_CONFIDENCE_STATUSES = frozenset({"DISPUTED", "EXPIRED", "RETRACTED", "SUPERSEDED"})
_BUDGET_STUB = {"budget_truncated": True, "reason": "CONTEXT_BUDGET_EXCEEDED"}


def _estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    return max(1, len(canonical_json(value)) // 4)


def _is_budget_stub(value: Any) -> bool:
    return isinstance(value, dict) and value.get("budget_truncated") is True


def _content_tokens(env: dict[str, Any]) -> int:
    total = 0
    for section in CONTEXT_BUDGET_ORDER:
        value = env.get(section)
        if value is None or _is_budget_stub(value):
            continue
        total += _estimate_tokens(value)
    return total


def _is_low_confidence(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    conf = record.get("confidence")
    if conf is not None:
        try:
            if float(conf) < LOW_CONFIDENCE_THRESHOLD:
                return True
        except (TypeError, ValueError):
            pass
    status = str(record.get("status") or "").strip().upper()
    if status in _LOW_CONFIDENCE_STATUSES:
        return True
    if record.get("contradicts"):
        return True
    if str(record.get("admit_status") or "").strip().upper() == "REJECTED":
        return True
    return False


def _drop_low_confidence_memory(env: dict[str, Any]) -> list[str]:
    """Drop low-confidence records from episodic_memory in-place.

    Returns the list of dropped memory_ids. The section keeps its
    high-confidence (operator explicit) records and is annotated so the trace
    shows exactly which memory was dropped.
    """
    section = env.get(SECTION_EPISODIC_MEMORY)
    if not isinstance(section, dict):
        return []
    records = section.get("records")
    if not isinstance(records, list) or not records:
        return []

    kept: list[Any] = []
    dropped_ids: list[str] = []
    for rec in records:
        mid = str(rec.get("memory_id") or "") if isinstance(rec, dict) else ""
        if _is_low_confidence(rec):
            if mid:
                dropped_ids.append(mid)
        else:
            kept.append(rec)

    if not dropped_ids:
        return []

    section["records"] = kept
    section["memory_ids"] = [
        r.get("memory_id") for r in kept if isinstance(r, dict) and r.get("memory_id")
    ]
    section["low_confidence_dropped"] = dropped_ids
    section["budget_low_confidence_truncated"] = True
    return dropped_ids


def apply_context_budget(
    envelope: dict[str, Any],
    budget_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministically truncate context to a token budget.

    Returns ``(budgeted_envelope, truncation_metadata)``. Sections are dropped
    lowest-priority-first (external read → research → memory → active intent →
    decision); canonical truth (``office_truth``) is never dropped. Inside
    ``episodic_memory``, low-confidence records are dropped before the whole
    section. ``truncation_metadata`` records everything that was truncated so
    it is visible in a trace.
    """
    env = _deep(envelope) if isinstance(envelope, dict) else {}
    budget = max(0, int(budget_tokens or 0))

    original = _content_tokens(env)
    metadata: dict[str, Any] = {
        "budget_tokens": budget,
        "original_tokens": original,
        "final_tokens": original,
        "within_budget": original <= budget,
        "dropped_sections": [],
        "canonical_truth_preserved": True,
        "memory_low_confidence_dropped": [],
        "details": [],
        "authority": AUTHORITY_READ_ONLY_ADVISORY,
    }

    if original <= budget:
        return env, metadata

    for section in reversed(CONTEXT_BUDGET_ORDER):
        if section == SECTION_OFFICE_TRUTH:
            continue  # canonical truth is never dropped
        if section not in env or _is_budget_stub(env.get(section)):
            continue
        if _content_tokens(env) <= budget:
            break

        # Episodic memory: drop low-confidence records first (the 7th, lowest
        # priority) before dropping the whole section.
        if section == SECTION_EPISODIC_MEMORY:
            before = _content_tokens(env)
            dropped_ids = _drop_low_confidence_memory(env)
            after = _content_tokens(env)
            if dropped_ids:
                metadata["memory_low_confidence_dropped"].extend(dropped_ids)
                metadata["details"].append(
                    {
                        "section": section,
                        "action": "dropped_low_confidence_memory",
                        "memory_ids": dropped_ids,
                        "tokens_saved": max(0, before - after),
                    }
                )
            if _content_tokens(env) <= budget:
                break

        # Drop the whole section.
        before = _content_tokens(env)
        metadata["dropped_sections"].append(section)
        env[section] = _deep(_BUDGET_STUB)
        after = _content_tokens(env)
        metadata["details"].append(
            {
                "section": section,
                "action": "dropped_section",
                "tokens_saved": max(0, before - after),
            }
        )

    metadata["final_tokens"] = _content_tokens(env)
    metadata["within_budget"] = metadata["final_tokens"] <= budget
    metadata["canonical_truth_preserved"] = (
        SECTION_OFFICE_TRUTH in env and not _is_budget_stub(env.get(SECTION_OFFICE_TRUTH))
    )
    return env, metadata


# ── Shadow compare ─────────────────────────────────────────────────────────


def _norm_token(value: Any) -> str:
    return str(value or "").strip().upper()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def shadow_compare(
    baseline_decision: dict[str, Any],
    augmented_decision: dict[str, Any],
) -> dict[str, Any]:
    """Diff a baseline decision against an augmented (context-enriched) one.

    ``same`` is True when the advisory action is unchanged (same
    ``current_action`` and ``act_now``). The remaining fields report exactly
    WHAT context differed — memory ids, MCP context, specialist inputs,
    notification, follow-up — so a shadow run can see *why* an action moved,
    not merely that it did.
    """
    b = baseline_decision if isinstance(baseline_decision, dict) else {}
    a = augmented_decision if isinstance(augmented_decision, dict) else {}

    b_action = _norm_token(b.get("current_action") if "current_action" in b else b.get("action"))
    a_action = _norm_token(a.get("current_action") if "current_action" in a else a.get("action"))
    b_act_now = bool(b.get("act_now"))
    a_act_now = bool(a.get("act_now"))

    action_changed = (b_action != a_action) or (b_act_now != a_act_now)
    same = not action_changed

    b_size = _estimate_tokens(b)
    a_size = _estimate_tokens(a)
    size_changed = b_size != a_size

    b_mem = _as_list(b.get("memory_ids_used") if b.get("memory_ids_used") is not None else b.get("memory_ids"))
    a_mem = _as_list(a.get("memory_ids_used") if a.get("memory_ids_used") is not None else a.get("memory_ids"))
    mem_added = [m for m in a_mem if m not in b_mem]
    mem_removed = [m for m in b_mem if m not in a_mem]

    b_mcp = _as_list(b.get("mcp_context_used") if b.get("mcp_context_used") is not None else b.get("mcp_calls"))
    a_mcp = _as_list(a.get("mcp_context_used") if a.get("mcp_context_used") is not None else a.get("mcp_calls"))
    mcp_added = [m for m in a_mcp if m not in b_mcp]
    mcp_removed = [m for m in b_mcp if m not in a_mcp]

    b_spec = _as_list(b.get("specialists") if b.get("specialists") is not None else b.get("specialist_context"))
    a_spec = _as_list(a.get("specialists") if a.get("specialists") is not None else a.get("specialist_context"))
    spec_added = [s for s in a_spec if s not in b_spec]
    spec_removed = [s for s in b_spec if s not in a_spec]

    notification_changed = canonical_json(b.get("notification")) != canonical_json(a.get("notification"))
    follow_up_changed = canonical_json(b.get("follow_up")) != canonical_json(a.get("follow_up"))

    why: list[str] = []
    if action_changed:
        why.append(
            f"action changed: {b.get('current_action') or b.get('action')!r} -> "
            f"{a.get('current_action') or a.get('action')!r}"
        )
    if size_changed:
        why.append(f"size changed: ~{b_size} -> ~{a_size} tokens")
    if mem_added:
        why.append(f"memory ids added: {mem_added}")
    if mem_removed:
        why.append(f"memory ids removed: {mem_removed}")
    if mcp_added:
        why.append(f"mcp context added: {mcp_added}")
    if mcp_removed:
        why.append(f"mcp context removed: {mcp_removed}")
    if spec_added:
        why.append(f"specialist input added: {spec_added}")
    if spec_removed:
        why.append(f"specialist input removed: {spec_removed}")
    if notification_changed:
        why.append("notification changed")
    if follow_up_changed:
        why.append("follow_up changed")
    if not why:
        why.append("no material difference")

    return {
        "same": same,
        "action_changed": action_changed,
        "size_changed": size_changed,
        "why": why,
        "memory_ids_used": {
            "baseline": b_mem,
            "augmented": a_mem,
            "added": mem_added,
            "removed": mem_removed,
            "changed": bool(mem_added or mem_removed),
        },
        "mcp_context_used": {
            "baseline": b_mcp,
            "augmented": a_mcp,
            "added": mcp_added,
            "removed": mcp_removed,
            "changed": bool(mcp_added or mcp_removed),
        },
        "specialists_changed": {
            "baseline": b_spec,
            "augmented": a_spec,
            "added": spec_added,
            "removed": spec_removed,
            "changed": bool(spec_added or spec_removed),
        },
        "notification_changed": notification_changed,
        "follow_up_changed": follow_up_changed,
        "authority": AUTHORITY_READ_ONLY_ADVISORY,
    }
