"""CIO committee synthesis — specialist advisories → committee → InvestmentDecision@v1.

Phase 4 wiring (deterministic, provider-call-free). This is the bridge between
the frozen specialist advisory contract and the canonical decision envelope:

    [SpecialistAdvisory...]  --vote_from_specialist_advisory-->  CommitteeVote...
        --convene-->  CommitteeResult  --reconcile_committee-->  final position
        --build_decision-->  InvestmentDecision@v1  --recommendations_from_decision-->
        recommendation rows consumed by CIORunWorker._write_actions

Alex is the CHAIR: he proposes an `intended_position` and the committee gates it.
This module never invents evidence, never executes, and is READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from scripts.lib.cio_committee import (
    CommitteeResult,
    convene,
    vote_from_specialist_advisory,
)
from scripts.lib.cio_investment_decision import (
    InvestmentDecision,
    build_decision,
    POSITION_BUY,
    POSITION_SELL,
    POSITION_SELL_TAXABLE,
    POSITION_TRIM,
    POSITION_HOLD,
    POSITION_NO_ACTION,
    POSITION_DEFER,
    EXECUTION_POSITIONS,
    ACTIONABILITY_READY,
    ACTIONABILITY_NEEDS_EVIDENCE,
    ACTIONABILITY_CONFLICT,
    VALID_FINAL_POSITIONS,
)

# ── Chair reconciliation ──────────────────────────────────────────────────────


def reconcile_committee(
    intended_position: str,
    committee_result: CommitteeResult,
    *,
    how_disagreements_were_resolved: str = "",
) -> dict[str, Any]:
    """Map a committee result to Alex's reconciled final position + actionability.

    Rules (fail-closed):
      1. BLOCKED_QUORUM            → DEFER / NEEDS_MORE_EVIDENCE
      2. BLOCKED_DEFENSE           → execution intent downgraded to HOLD;
                                     non-execution intent kept but surfaced as CONFLICT_UNRESOLVED
      3. UNANIMOUS/CONSENSUS_OPPOSE → execution intent downgraded to HOLD;
                                     non-execution intent kept, NEEDS_MORE_EVIDENCE
      4. MIXED                     → chair may resolve (READY) or not (CONFLICT_UNRESOLVED)
      5. CONSENSUS_NEUTRAL         → execution intent → DEFER; else kept, NEEDS_MORE_EVIDENCE
      6. UNANIMOUS/CONSENSUS_SUPPORT → position stands, READY_FOR_OPERATOR
    """
    if intended_position not in VALID_FINAL_POSITIONS:
        raise ValueError(f"Invalid intended_position {intended_position!r}")

    is_execution = intended_position in EXECUTION_POSITIONS
    consensus = committee_result.consensus

    def _downgrade(to: str, actionability: str, note: str) -> dict[str, Any]:
        return {
            "final_position": to,
            "actionability": actionability,
            "resolution": note,
            "overridden": to != intended_position,
        }

    if consensus == "BLOCKED_QUORUM":
        return _downgrade(
            POSITION_DEFER, ACTIONABILITY_NEEDS_EVIDENCE,
            "quorum not met — insufficient committee input to finalize",
        )

    if consensus == "BLOCKED_DEFENSE":
        if is_execution:
            return _downgrade(
                POSITION_HOLD, ACTIONABILITY_CONFLICT,
                "defense veto overrides execution intent — hold",
            )
        return _downgrade(
            intended_position, ACTIONABILITY_CONFLICT,
            "defense veto present; non-execution position retained but surfaced",
        )

    if consensus in ("UNANIMOUS_OPPOSE", "CONSENSUS_OPPOSE"):
        if is_execution:
            return _downgrade(
                POSITION_HOLD, ACTIONABILITY_NEEDS_EVIDENCE,
                f"committee {consensus} overrides execution intent — hold",
            )
        return _downgrade(
            intended_position, ACTIONABILITY_NEEDS_EVIDENCE,
            f"committee {consensus}; non-execution position retained",
        )

    if consensus == "MIXED":
        if how_disagreements_were_resolved:
            return _downgrade(
                intended_position, ACTIONABILITY_READY,
                f"chair resolved mixed committee: {how_disagreements_were_resolved}",
            )
        return _downgrade(
            intended_position, ACTIONABILITY_CONFLICT,
            "mixed committee unresolved — chair must document a resolution",
        )

    if consensus == "CONSENSUS_NEUTRAL":
        if is_execution:
            return _downgrade(
                POSITION_DEFER, ACTIONABILITY_NEEDS_EVIDENCE,
                "committee neutral — execution deferred pending a decision",
            )
        return _downgrade(
            intended_position, ACTIONABILITY_NEEDS_EVIDENCE,
            "committee neutral — no actionable mandate",
        )

    # UNANIMOUS_SUPPORT / CONSENSUS_SUPPORT
    return _downgrade(
        intended_position, ACTIONABILITY_READY,
        f"committee {consensus} supports the proposal",
    )


# ── Synthesis ─────────────────────────────────────────────────────────────────


def synthesize_decision(
    *,
    parent_run_id: str,
    intended_position: str,
    specialist_advisories: Iterable[Any],
    evidence_refs: Iterable[Any],
    rationale_linked_to_evidence: str,
    conditions_to_change_view: list[str],
    required_domains: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
    material_risks: Optional[list[str]] = None,
    how_disagreements_were_resolved: str = "",
    quorum: int = 3,
    confidence: float = 0.5,
) -> InvestmentDecision:
    """Full deterministic pipeline: advisories → committee → decision.

    Raises ValueError if any specialist advisory is malformed (fail-closed).
    """
    votes = [vote_from_specialist_advisory(a) for a in specialist_advisories]
    committee = convene(votes, quorum=quorum)

    reconciled = reconcile_committee(
        intended_position,
        committee,
        how_disagreements_were_resolved=how_disagreements_were_resolved,
    )

    decision = build_decision(
        parent_run_id=parent_run_id,
        final_position=reconciled["final_position"],
        committee_votes=votes,
        evidence_refs=list(evidence_refs),
        rationale_linked_to_evidence=rationale_linked_to_evidence,
        conditions_to_change_view=list(conditions_to_change_view),
        material_risks=list(material_risks or []),
        actionability=reconciled["actionability"],
        how_disagreements_were_resolved=how_disagreements_were_resolved,
        required_domains=list(required_domains or []),
        symbols=list(symbols or []),
        confidence=confidence,
        quorum=quorum,
    )
    return decision


# ── Recommendations (consumed by CIORunWorker._write_actions) ─────────────────

# final_position → CIO action type (cio_action_validator vocabulary)
_FINAL_POSITION_TO_ACTION_TYPE = {
    POSITION_BUY: "BUY",
    POSITION_SELL: "SELL",
    POSITION_SELL_TAXABLE: "SELL_TAXABLE",
    POSITION_TRIM: "TRIM",
    POSITION_HOLD: "HOLD",
    POSITION_NO_ACTION: "NO_ACTION",
    POSITION_DEFER: "NO_ACTION",
}


def recommendations_from_decision(decision: InvestmentDecision) -> list[dict[str, Any]]:
    """Map an InvestmentDecision@v1 to CIO-run recommendation rows.

    Each row carries `action` and `action_type` so `determine_action_type` and
    `create_action` both resolve. DEFER maps to a NO_ACTION status row (the
    deferral is captured in `followup_condition` / `recommended_action`).
    """
    action_type = _FINAL_POSITION_TO_ACTION_TYPE.get(
        decision.final_position, "NO_ACTION"
    )
    title = (
        f"{decision.final_position} {','.join(decision.symbols) or 'book'}"
        f" · committee {decision.committee.consensus}"
    )
    return [
        {
            "action": action_type,
            "action_type": action_type,
            "title": title,
            "description": decision.rationale_linked_to_evidence,
            "domain": "GENERAL",
            "priority": "HIGH" if decision.actionability == ACTIONABILITY_READY else "NORMAL",
            "recommended_action": (
                f"Operator review required. {decision.how_disagreements_were_resolved}"
                if decision.actionability == ACTIONABILITY_READY
                else decision.how_disagreements_were_resolved or "Observe / defer."
            ),
            "rationale": decision.rationale_linked_to_evidence,
            "evidence_refs": [r.to_dict() for r in decision.evidence_refs],
            "cio_decision_id": decision.decision_id,
        }
    ]


# ── CIORunWorker synthesis_fn factory ─────────────────────────────────────────


def build_committee_synthesis_fn(
    *,
    intended_position: Optional[str] = None,
    required_domains: Optional[list[str]] = None,
    quorum: int = 3,
    evidence_refs: Optional[Iterable[Any]] = None,
    rationale_linked_to_evidence: Optional[str] = None,
    conditions_to_change_view: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
) -> Callable[..., dict[str, Any]]:
    """Return a `synthesis_fn` callable compatible with CIORunWorker.

    Signature: fn(run, snapshot, specialist_result, hermes_result) -> dict

    The returned dict is the synthesis_data the worker consumes directly:
    `recommendations` (for _write_actions), `decision` (InvestmentDecision@v1),
    `decision_id`, `final_position`, `committee`, and `summary`.

    `intended_position` may be a str or a callable(run) -> str. Specialist
    advisories are read from `specialist_result["artifacts"]` (list of
    SpecialistAdvisory or dicts). Evidence refs are read from `evidence_refs`
    or, if omitted, from `snapshot`. Chair context (`rationale`, conditions,
    symbols) is taken from the run projection, then from these factory defaults,
    then sensible empty fallbacks — so a run projection that predates the
    committee contract still synthesizes deterministically.
    """
    from scripts.lib.cio_evidence_ref import EvidenceRef

    def _resolve_intended(run: dict[str, Any]) -> str:
        if callable(intended_position):
            return intended_position(run)
        if intended_position:
            return intended_position
        return str(run.get("intended_position") or POSITION_NO_ACTION)

    def fn(
        run: dict[str, Any],
        snapshot: dict[str, Any],
        specialist_result: dict[str, Any],
        hermes_result: dict[str, Any],
    ) -> dict[str, Any]:
        advisories = list(specialist_result.get("artifacts") or [])
        refs: list[Any] = list(evidence_refs or [])
        # If no explicit refs and the snapshot carries EvidenceRef objects, use them.
        if not refs:
            for r in snapshot.get("evidence_refs") or []:
                if isinstance(r, EvidenceRef) or (isinstance(r, dict) and "domain" in r):
                    refs.append(r)

        rationale = (
            str(run.get("rationale_linked_to_evidence"))
            or (rationale_linked_to_evidence or "")
            or str(snapshot.get("summary"))
            or "CIO advisory synthesis."
        )
        conditions = list(run.get("conditions_to_change_view") or conditions_to_change_view or [])

        decision = synthesize_decision(
            parent_run_id=str(run.get("run_id") or ""),
            intended_position=_resolve_intended(run),
            specialist_advisories=advisories,
            evidence_refs=refs,
            rationale_linked_to_evidence=rationale,
            conditions_to_change_view=conditions,
            required_domains=required_domains or list(run.get("required_domains") or []),
            symbols=list(run.get("symbols") or symbols or []),
            how_disagreements_were_resolved=str(
                run.get("how_disagreements_were_resolved") or ""
            ),
            quorum=quorum,
        )

        # Fail-closed: an invalid decision produces NO recommendations so the
        # worker creates a STATUS action instead of an execution action. Errors
        # are surfaced in the summary for operator escalation.
        #
        # NOTE: CIORunWorker._cio_synthesis wraps this return as
        # {"artifact_id", "result": <this dict>, "mode"}; _write_actions then
        # reads result["recommendations"] and result["summary"] directly.
        validation_errors = decision.validate()
        if validation_errors:
            return {
                "decision_id": decision.decision_id,
                "decision": decision.to_dict(),
                "final_position": decision.final_position,
                "committee": decision.committee.to_dict(),
                "summary": (
                    f"CIO decision blocked by committee/evidence gate: "
                    + "; ".join(validation_errors)
                ),
                "recommendations": [],
                "blocked": True,
                "block_reason_code": "DECISION_GATE",
                "block_detail": validation_errors,
            }

        return {
            "decision_id": decision.decision_id,
            "decision": decision.to_dict(),
            "final_position": decision.final_position,
            "committee": decision.committee.to_dict(),
            "summary": decision.rationale_linked_to_evidence,
            "recommendations": recommendations_from_decision(decision),
        }

    return fn
