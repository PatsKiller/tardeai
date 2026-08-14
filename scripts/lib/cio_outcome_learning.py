"""cio_outcome_learning.py — Phase 10 outcome learning: close the loop.

The final missing edge of the two-way loop (Phase 5) is the CIO-side feeder:
operator disposition + a measured outcome must write BACK into (a) durable
learning candidates and (b) the reverse-factor sample sizes the scorer's
reliability gate reads. This module is that feeder, deterministic and pure.

    operator disposition  ─┐
    measured outcome      ─┼─▶ outcome_signal ─▶ derive_learning_candidates
    (POSITIVE/NEGATIVE/…) ─┤                      derive_reverse_writebacks
                          ─┘                      build_calibration
                                      │
                                      ▼
        grade_and_learn() ─▶ CIOOutcomeStore + CIOLearningCandidateStore
                             + reverse writeback directives + calibration

Safety invariants (mirror the rest of the office):
  * READ_ONLY_ADVISORY — never touches broker/order/stop/2FA/provider.
  * Learning candidates are effect-constrained to `CIOLearningCandidateStore.ALLOWED_EFFECTS`
    (retrieval_weighting / confidence_calibration / research_checklist /
    communication_improvement / routing_proposal) — never policy/broker/tax.
  * Reverse writebacks are *directives*: they are returned for the live two-way
    executor to apply through the existing governed writers (`write_realized_outcome`,
    `write_options_edge`, `write_hermes_research`). This module does not invent a
    second write path.
  * Fail-closed: an unmeasured outcome (`UNKNOWN`/`NOT_MEASURABLE` + a passive
    disposition) produces NO learning candidates and NO writebacks. Learning is
    never fabricated from a non-signal.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.two_way_curation import (
    REVERSE_FACTORS,
    calibrate_reverse_weights,
    outcome_verdict_to_ledger,
)

AUTHORITY = "READ_ONLY_ADVISORY"
LEARNING_VERSION = "OutcomeLearning@v1"

# Canonical reverse-factor base weights — mirrors config/hermes_score_weights.yaml
# v9 so the calibration summary here matches what the live scorer applies.
DEFAULT_REVERSE_BASE_WEIGHTS: dict[str, float] = {
    "thesis_outcome": 0.057,
    "options_edge": 0.045,
    "hermes_research": 0.055,
}

# ─────────────────────────────────────────────────────────────────────────────
# Disposition normalization (both vocabularies → one canonical set)
# ─────────────────────────────────────────────────────────────────────────────
#
# Two producers write operator dispositions:
#   * the Phase 8 UI (`decision_dispositions.jsonl`): ack / defer / done / reject
#   * the CIOOutcomeStore: ACKNOWLEDGED / ACCEPTED / DEFERRED / REJECTED / DONE / CANCELLED
# Learning must read both through one lens.

_DISPOSITION_ALIASES: dict[str, str] = {
    "ack": "ACKNOWLEDGED",
    "acknowledge": "ACKNOWLEDGED",
    "acknowledged": "ACKNOWLEDGED",
    "accept": "ACCEPTED",
    "accepted": "ACCEPTED",
    "defer": "DEFERRED",
    "deferred": "DEFERRED",
    "done": "DONE",
    "reject": "REJECTED",
    "rejected": "REJECTED",
    "cancel": "CANCELLED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
}

# Dispositions that indicate the operator agreed/acted on the decision.
_AGREE_DISPOSITIONS = frozenset({"ACCEPTED", "DONE"})
# Dispositions that indicate disagreement.
_DISAGREE_DISPOSITIONS = frozenset({"REJECTED"})


def normalize_disposition(raw: Any) -> Optional[str]:
    """Map either disposition vocabulary to a canonical uppercase disposition.

    Unknown / empty input returns None so callers fail closed rather than
    guessing a signal.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    key = s.lower()
    if key in _DISPOSITION_ALIASES:
        return _DISPOSITION_ALIASES[key]
    up = s.upper()
    if up in ("ACKNOWLEDGED", "ACCEPTED", "DEFERRED", "REJECTED", "DONE", "CANCELLED"):
        return up
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Outcome signal (pure)
# ─────────────────────────────────────────────────────────────────────────────

# One of: hit (thesis/decision validated), miss (invalidated), neutral (graded,
# no edge either way), skip (no measurable signal — no learning).
SIGNAL_HIT = "hit"
SIGNAL_MISS = "miss"
SIGNAL_NEUTRAL = "neutral"
SIGNAL_SKIP = "skip"


def outcome_signal(operator_disposition: Any, outcome_status: Any) -> str:
    """Derive the learning signal from a measured outcome + disposition.

    The measured `outcome_status` is authoritative. When it is not yet
    measurable (UNKNOWN / NOT_MEASURABLE), the operator disposition is used as a
    weaker proxy: an agreement is a (proxy) hit, a rejection is a (proxy) miss,
    a deferral is neutral. A passive acknowledgement with no measurement is a
    skip — no learning is invented.
    """
    os_ = str(outcome_status or "").strip().upper()
    if os_ == "POSITIVE":
        return SIGNAL_HIT
    if os_ == "NEGATIVE":
        return SIGNAL_MISS
    if os_ == "MIXED":
        return SIGNAL_NEUTRAL

    d = normalize_disposition(operator_disposition)
    if d in _DISAGREE_DISPOSITIONS:
        return SIGNAL_MISS
    if d in _AGREE_DISPOSITIONS:
        return SIGNAL_HIT
    if d == "DEFERRED":
        return SIGNAL_NEUTRAL
    return SIGNAL_SKIP


# ─────────────────────────────────────────────────────────────────────────────
# Learning candidate derivation (pure, effect-constrained)
# ─────────────────────────────────────────────────────────────────────────────


def derive_learning_candidates(
    *,
    cio_action_id: str,
    operator_disposition: Any,
    outcome_status: Any,
    result_summary: str = "",
    what_was_right: str = "",
    what_was_wrong: str = "",
    unknowns: str = "",
    parent_outcome_id: str = "",
    symbol: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Derive 0+ learning candidates from one graded outcome. Pure, no I/O.

    Every candidate's `proposed_effect` is one of the store's ALLOWED_EFFECTS.
    The rule set is deterministic and conservative: a candidate is minted only
    when the outcome text or signal supports it.
    """
    d = normalize_disposition(operator_disposition) or ""
    os_ = str(outcome_status or "").strip().upper()
    sig = outcome_signal(operator_disposition, outcome_status)
    cands: list[dict[str, Any]] = []

    def _mk(title: str, description: str, effect: str) -> dict[str, Any]:
        return {
            "lesson_title": title,
            "description": description,
            "proposed_effect": effect,
            "parent_action_id": cio_action_id,
            "parent_outcome_id": parent_outcome_id,
            "evidence": [
                e for e in (
                    f"outcome_status={os_ or 'UNKNOWN'}",
                    f"disposition={d or 'none'}",
                    (f"what_was_wrong={what_was_wrong[:200]}" if what_was_wrong.strip() else ""),
                    (f"what_was_right={what_was_right[:200]}" if what_was_right.strip() else ""),
                    (f"unknowns={unknowns[:200]}" if unknowns.strip() else ""),
                    (f"symbol={symbol}" if symbol else ""),
                ) if e
            ],
        }

    # 1. Something was wrong, or the outcome was negative, or the operator
    #    rejected it → calibrate confidence (the office over- or under-weighted).
    if what_was_wrong.strip() or os_ == "NEGATIVE" or d == "REJECTED":
        cands.append(_mk(
            "Calibrate confidence on this decision class",
            (
                "A graded outcome disagreed with the decision"
                f" ({os_ or d}). Revisit the confidence assigned to the"
                " inputs that drove it before the next same-class decision."
            ),
            "confidence_calibration",
        ))

    # 2. Something went right AND the outcome was positive → reinforce the
    #    retrieval weighting of the sources that produced the winning view.
    if what_was_right.strip() and (os_ == "POSITIVE" or d in _AGREE_DISPOSITIONS):
        cands.append(_mk(
            "Reinforce sources that produced a validated view",
            (
                "The decision validated. Upweight retrieval of the evidence"
                " sources behind this decision for the next same-class review."
            ),
            "retrieval_weighting",
        ))

    # 3. The outcome records open questions → add them to the research checklist.
    if unknowns.strip():
        cands.append(_mk(
            "Add open questions to the research checklist",
            f"Unresolved items to research before the next review: {unknowns[:240]}",
            "research_checklist",
        ))

    # 4. Operator rejection → route this decision class differently.
    if d == "REJECTED":
        cands.append(_mk(
            "Re-route rejected decision class",
            (
                "The operator rejected this decision. Re-route future same-class"
                " decisions through a different specialist or earlier operator review."
            ),
            "routing_proposal",
        ))

    # 5. Deferral → schedule a routing follow-up rather than dropping it.
    if d == "DEFERRED":
        cands.append(_mk(
            "Schedule follow-up for deferred decision",
            "The decision was deferred. Route a follow-up so it is re-opened, not forgotten.",
            "routing_proposal",
        ))

    # 6. A non-positive, non-agreed result with a summary → improve how the
    #    decision is communicated to the operator.
    if (
        result_summary.strip()
        and os_ not in ("POSITIVE",)
        and d not in _AGREE_DISPOSITIONS
        and sig != SIGNAL_SKIP
    ):
        cands.append(_mk(
            "Improve operator-facing communication",
            "The decision did not land as intended. Tighten how rationale and"
            " evidence are communicated in the operator brief.",
            "communication_improvement",
        ))

    return cands


# ─────────────────────────────────────────────────────────────────────────────
# Reverse writeback derivation (pure) — feeds two_way_curation writers
# ─────────────────────────────────────────────────────────────────────────────


def derive_reverse_writebacks(
    *,
    operator_disposition: Any,
    outcome_status: Any,
    symbol: Optional[str] = None,
    options_edge_score: Optional[float] = None,
    hermes_research_score: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Derive reverse-factor writeback directives for the two-way curation writers.

    Only a measured outcome (`hit`/`miss`/`neutral`) mints a thesis_outcome
    writeback; a `skip` signal mints nothing (no fabrication). A symbol is
    required for thesis/options/research writebacks because every reverse factor
    folds onto a per-symbol watchlist row.

    Evidence class is honest: a measured outcome (POSITIVE/NEGATIVE/MIXED) is
    `realized` (graded against an outcome); a disposition-only proxy (an
    agreement/rejection with no measurement yet) is labeled `proxy` so the
    scorer's reliability gate never conflates operator agreement with a realized
    trade outcome.
    """
    sig = outcome_signal(operator_disposition, outcome_status)
    wbs: list[dict[str, Any]] = []

    sym = str(symbol or "").strip().upper() or None
    measured = str(outcome_status or "").strip().upper() in ("POSITIVE", "NEGATIVE", "MIXED")
    evidence_class = "realized" if measured else "proxy"

    if sig != SIGNAL_SKIP and sym:
        realized_outcome, thesis_win = outcome_verdict_to_ledger(sig)
        # outcome_verdict_to_ledger maps hit→(win,True) miss→(loss,False)
        # neutral→(scratch,None). A neutral is still a graded sample (n=1).
        wbs.append({
            "factor": "thesis_outcome",
            "symbol": sym,
            "realized_outcome": realized_outcome,
            "thesis_win": thesis_win,
            "n": 1,
            "evidence_class": evidence_class,
        })

    if options_edge_score is not None and sym:
        wbs.append({
            "factor": "options_edge",
            "symbol": sym,
            "options_edge": round(max(0.0, min(100.0, float(options_edge_score))), 1),
            "n": 1,
            "evidence_class": "realized",
        })

    if hermes_research_score is not None and sym:
        wbs.append({
            "factor": "hermes_research",
            "symbol": sym,
            "score": round(max(0.0, min(100.0, float(hermes_research_score))), 1),
            "n": 1,
            "evidence_class": "proxy",
        })

    return wbs


# ─────────────────────────────────────────────────────────────────────────────
# Calibration (pure) — sample sizes → reliability-gated weights
# ─────────────────────────────────────────────────────────────────────────────


def aggregate_factor_samples(writebacks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate reverse writeback directives into {factor: {n, evidence_class}}."""
    agg: dict[str, dict[str, Any]] = {}
    for wb in writebacks or []:
        f = str(wb.get("factor") or "")
        if f not in REVERSE_FACTORS:
            continue
        a = agg.setdefault(f, {"n": 0, "evidence_class": wb.get("evidence_class")})
        try:
            a["n"] += int(wb.get("n") or 1)
        except (TypeError, ValueError):
            a["n"] += 1
    return agg


def build_calibration(
    *,
    base_weights: Optional[dict[str, float]] = None,
    sample_sizes: Optional[dict[str, Optional[int]]] = None,
    evidence_class: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Reliability-gate a reverse-weight map against sample sizes.

    Wraps `two_way_curation.calibrate_reverse_weights`. Effective weight can
    never exceed base weight; a factor below its `n_min` is damped, a factor at
    `n=0`/unknown is dropped to zero.
    """
    base = {**DEFAULT_REVERSE_BASE_WEIGHTS, **(base_weights or {})}
    sizes = dict(sample_sizes or {})
    return calibrate_reverse_weights(base, sizes, evidence_class=evidence_class)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator — grade one action and close the learning loop
# ─────────────────────────────────────────────────────────────────────────────


def grade_and_learn(
    *,
    outcome_store: Any,
    learning_store: Any,
    cio_action_id: str,
    operator_disposition: Any,
    outcome_status: Any = "UNKNOWN",
    result_summary: str = "",
    what_was_right: str = "",
    what_was_wrong: str = "",
    unknowns: str = "",
    symbol: Optional[str] = None,
    context_refs: Optional[list[str]] = None,
    base_weights: Optional[dict[str, float]] = None,
    options_edge_score: Optional[float] = None,
    hermes_research_score: Optional[float] = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Record an outcome, then derive and persist learning + reverse writebacks.

    Returns the outcome event, the persisted learning candidates, the reverse
    writeback directives, and the reliability-gated calibration — the "learning
    spine" from disposition through to calibrated weights.
    """
    canonical_disp = normalize_disposition(operator_disposition)
    if canonical_disp is None:
        return {
            "ok": False,
            "authority": AUTHORITY,
            "error": "unknown_disposition",
            "raw_disposition": operator_disposition,
        }

    outcome_event = outcome_store.record_outcome(
        cio_action_id=cio_action_id,
        operator_disposition=canonical_disp,
        outcome_status=str(outcome_status or "UNKNOWN").strip().upper(),
        result_summary=result_summary,
        what_was_right=what_was_right,
        what_was_wrong=what_was_wrong,
        unknowns=unknowns,
        context_refs=context_refs or [],
        actor=actor,
    )

    parent_outcome_id = outcome_event.get("event_id") or ""

    candidates = derive_learning_candidates(
        cio_action_id=cio_action_id,
        operator_disposition=canonical_disp,
        outcome_status=outcome_status,
        result_summary=result_summary,
        what_was_right=what_was_right,
        what_was_wrong=what_was_wrong,
        unknowns=unknowns,
        parent_outcome_id=parent_outcome_id,
        symbol=symbol,
    )

    persisted: list[dict[str, Any]] = []
    for c in candidates:
        persisted.append(learning_store.create_candidate(
            lesson_title=c["lesson_title"],
            description=c["description"],
            proposed_effect=c["proposed_effect"],
            parent_outcome_id=c["parent_outcome_id"],
            parent_action_id=c["parent_action_id"],
            evidence=c["evidence"],
            actor=actor,
        ))

    writebacks = derive_reverse_writebacks(
        operator_disposition=canonical_disp,
        outcome_status=outcome_status,
        symbol=symbol,
        options_edge_score=options_edge_score,
        hermes_research_score=hermes_research_score,
    )

    samples = aggregate_factor_samples(writebacks)
    sample_sizes = {f: a["n"] for f, a in samples.items()}
    evidence_class = {
        f: a["evidence_class"] for f, a in samples.items() if a.get("evidence_class")
    }
    calibration = build_calibration(
        base_weights=base_weights,
        sample_sizes=sample_sizes,
        evidence_class=evidence_class,
    )

    return {
        "ok": True,
        "authority": AUTHORITY,
        "version": LEARNING_VERSION,
        "signal": outcome_signal(canonical_disp, outcome_status),
        "outcome": outcome_event,
        "outcome_id": parent_outcome_id,
        "candidates": persisted,
        "candidate_count": len(persisted),
        "writebacks": writebacks,
        "writeback_count": len(writebacks),
        "sample_sizes": sample_sizes,
        "calibration": calibration,
    }
