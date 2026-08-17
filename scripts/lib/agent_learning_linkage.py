"""agent_learning_linkage.py — Learning loop lineage + feedback/outcome invariants (Phase 7).

READ_ONLY_ADVISORY. Pure and deterministic.

This module ties the learning loop together without ever mutating a store. It
provides:

  * a canonical lineage model linking a wake → trace → decision → case →
    operator feedback → follow-up → measured outcome → darwin score →
    reflection → lesson candidate;
  * a deterministic lineage digest for audit/replay;
  * the CRITICAL feedback-vs-outcome invariant: operator dispositions
    (REJECT / ACK / DONE / RATE / DEFER / NOTE) are FEEDBACK, never investment
    outcomes. A REJECT is not an investment loss; an ACK/DONE is not a win;
    a RATE is not alpha. Only a matured, measured investment-result marker is a
    MEASURED_INVESTMENT_OUTCOME;
  * `propose_memory_write()` — the ONLY sanctioned way a reflection may become a
    memory record. It returns a CANDIDATE (status CANDIDATE, admit_status
    CANDIDATE); a separate admit-style gate decides the final status. This module
    never writes to any provider/store directly;
  * `link_memory_refs()` — attach lineage refs to a memory record.

No broker / order / stop / 2FA / risk-policy mutation. No network. No secrets.
No strategy write or promote side effect of any kind.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.agent_context_envelope import canonical_json, sha256_hex

# ── Lineage model (ordered) ────────────────────────────────────────────────
LINEAGE_STEPS = (
    "wake_id",
    "trace_id",
    "decision_id",
    "case_id",
    "operator_feedback",
    "follow_up",
    "measured_outcome",
    "darwin_score",
    "reflection",
    "lesson_candidate",
)

# ── Authority ──────────────────────────────────────────────────────────────
AUTHORITY_READ_ONLY_ADVISORY = "READ_ONLY_ADVISORY"

# ── Memory-candidate admission states ──────────────────────────────────────
MEMORY_STATUS_CANDIDATE = "CANDIDATE"
ADMIT_STATUS_CANDIDATE = "CANDIDATE"
ADMIT_STATUS_ADMITTED = "ADMITTED"
ADMIT_STATUS_REJECTED = "REJECTED"

# ── Feedback-vs-outcome invariant ──────────────────────────────────────────
# Operator dispositions. These are FEEDBACK, NEVER investment outcomes.
FEEDBACK_NOT_OUTCOME = frozenset({
    "REJECT",   # operator rejected the recommendation — NOT an investment loss
    "ACK",      # operator acknowledged — NOT a win
    "DONE",     # operator marked done — NOT a win
    "RATE",     # operator rated the call — NOT alpha
    "DEFER",    # operator deferred — NOT an outcome
    "NOTE",     # operator left a note — NOT an outcome
})

# Explicit measured investment-outcome dispositions. Only these (when paired with
# the matured/measured flags in `is_measured_outcome`) are investment results.
MEASURED_OUTCOME_DISPOSITIONS = frozenset({
    "MEASURED_INVESTMENT_OUTCOME",
    "MEASURED_OUTCOME",
    "INVESTMENT_OUTCOME_MATURED",
    "MATURED_INVESTMENT_OUTCOME",
})

FEEDBACK_CLASS = "FEEDBACK"
OUTCOME_CLASS = "MEASURED_INVESTMENT_OUTCOME"
UNCLASSIFIED_CLASS = "UNCLASSIFIED"


def _norm(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def build_lineage(
    *,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    case_id: Optional[str] = None,
    operator_feedback: Any = None,
    follow_up: Any = None,
    measured_outcome: Any = None,
    darwin_score: Any = None,
    reflection: Any = None,
    lesson_candidate: Any = None,
) -> dict[str, Any]:
    """Return an ordered lineage dict. Missing steps are explicit ``None``.

    The key order is fixed by ``LINEAGE_STEPS`` so the digest is stable
    regardless of call-site argument ordering.
    """
    values: dict[str, Any] = {
        "wake_id": wake_id,
        "trace_id": trace_id,
        "decision_id": decision_id,
        "case_id": case_id,
        "operator_feedback": operator_feedback,
        "follow_up": follow_up,
        "measured_outcome": measured_outcome,
        "darwin_score": darwin_score,
        "reflection": reflection,
        "lesson_candidate": lesson_candidate,
    }
    return {step: values.get(step) for step in LINEAGE_STEPS}


def lineage_digest(lineage: Any) -> str:
    """Deterministic content digest of a lineage dict."""
    body = lineage if isinstance(lineage, dict) else build_lineage()
    return "lin_" + sha256_hex(canonical_json(body), 16)


def classify_feedback_vs_outcome(disposition: Any) -> str:
    """Classify a disposition string as FEEDBACK vs MEASURED_INVESTMENT_OUTCOME.

    CRITICAL invariant: operator dispositions (REJECT/ACK/DONE/RATE/DEFER/NOTE)
    are FEEDBACK. Only an explicit measured-investment-outcome disposition is a
    MEASURED_INVESTMENT_OUTCOME. Anything else is UNCLASSIFIED (never silently
    assumed to be an outcome).
    """
    key = _norm(disposition)
    if not key:
        return UNCLASSIFIED_CLASS
    if key in FEEDBACK_NOT_OUTCOME:
        return FEEDBACK_CLASS
    if key in MEASURED_OUTCOME_DISPOSITIONS:
        return OUTCOME_CLASS
    return UNCLASSIFIED_CLASS


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "measured", "matured"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return False


def is_measured_outcome(record: Any) -> bool:
    """True only if ``record`` is a matured, measured investment-result marker.

    Fail-closed: requires (a) a recognized measured-outcome disposition, and
    (b) BOTH the ``measured`` and ``matured`` flags. Operator feedback is NEVER
    a measured outcome, and an unrecognized disposition is never assumed to be
    one (even with flags present).
    """
    if not isinstance(record, dict):
        return False
    disposition = record.get("disposition") or record.get("outcome") or ""
    if classify_feedback_vs_outcome(disposition) == FEEDBACK_CLASS:
        return False
    if classify_feedback_vs_outcome(disposition) != OUTCOME_CLASS:
        return False
    measured = _truthy(record.get("measured")) or _truthy(record.get("outcome_measured"))
    matured = _truthy(record.get("matured")) or _truthy(record.get("outcome_matured"))
    return measured and matured


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def propose_memory_write(
    reflection: Any,
    *,
    memory_type: str,
    content: Any,
    source_event_ids: Any,
    source_refs: Any = None,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    case_id: Optional[str] = None,
) -> dict[str, Any]:
    """Propose a memory CANDIDATE from a reflection. Never writes to any store.

    The ONLY sanctioned path for reflection output to become memory. Returns a
    candidate record (status CANDIDATE, admit_status CANDIDATE) carrying full
    provenance and lineage. A separate admit-style gate decides the final status
    (ADMITTED / REJECTED); this module does not perform that mutation.

    No provider/store is touched and no write/promote action is emitted.
    """
    event_ids = _as_list(source_event_ids)
    refs = _as_list(source_refs)
    lineage = build_lineage(
        wake_id=wake_id,
        trace_id=trace_id,
        decision_id=decision_id,
        case_id=case_id,
        reflection=reflection,
    )
    body = {
        "memory_type": str(memory_type or ""),
        "content": content,
        "source_event_ids": sorted(str(e) for e in event_ids),
    }
    memory_id = "mem_" + sha256_hex(canonical_json(body), 16)
    return {
        "memory_id": memory_id,
        "status": MEMORY_STATUS_CANDIDATE,
        "admit_status": ADMIT_STATUS_CANDIDATE,
        "memory_type": str(memory_type or ""),
        "content": content,
        "reflection": reflection,
        "reflection_digest": sha256_hex(canonical_json(reflection), 16),
        "source_event_ids": sorted(str(e) for e in event_ids),
        "source_refs": list(refs),
        "lineage": lineage,
        "lineage_digest": lineage_digest(lineage),
        "provenance": {
            "generated_by": "agent_learning_linkage.propose_memory_write",
            "authority": AUTHORITY_READ_ONLY_ADVISORY,
            "write_attempted": False,
            "promote_attempted": False,
            "memory_digest": sha256_hex(canonical_json(body), 16),
        },
        "authority": AUTHORITY_READ_ONLY_ADVISORY,
    }


def admit_memory_candidate(
    candidate: dict[str, Any],
    *,
    admit: bool,
    reason: Optional[str] = None,
    admitted_by: Optional[str] = None,
) -> dict[str, Any]:
    """Pure admit-style gate: return the candidate with a final status.

    Read-only by design — it returns a copy with ``status``/``admit_status`` set,
    it does NOT write to any provider/store. Callers decide whether (and where)
    to persist the ADMITTED record.
    """
    out = dict(candidate)
    final = ADMIT_STATUS_ADMITTED if admit else ADMIT_STATUS_REJECTED
    out["status"] = final
    out["admit_status"] = final
    out["admitted_by"] = admitted_by
    if reason is not None:
        out["admit_reason"] = reason
    return out


def link_memory_refs(
    record: Any,
    *,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    case_id: Optional[str] = None,
) -> dict[str, Any]:
    """Attach lineage refs to a memory record. Returns a copy (never mutates)."""
    out = dict(record) if isinstance(record, dict) else {}
    existing = out.get("lineage")
    base = dict(existing) if isinstance(existing, dict) else {}
    merged = build_lineage(
        wake_id=wake_id if wake_id is not None else base.get("wake_id"),
        trace_id=trace_id if trace_id is not None else base.get("trace_id"),
        decision_id=decision_id if decision_id is not None else base.get("decision_id"),
        case_id=case_id if case_id is not None else base.get("case_id"),
        operator_feedback=base.get("operator_feedback"),
        follow_up=base.get("follow_up"),
        measured_outcome=base.get("measured_outcome"),
        darwin_score=base.get("darwin_score"),
        reflection=base.get("reflection"),
        lesson_candidate=base.get("lesson_candidate"),
    )
    out["lineage"] = merged
    out["lineage_digest"] = lineage_digest(merged)
    for key, value in (
        ("wake_id", wake_id),
        ("trace_id", trace_id),
        ("decision_id", decision_id),
        ("case_id", case_id),
    ):
        if value is not None:
            out[key] = value
    return out
