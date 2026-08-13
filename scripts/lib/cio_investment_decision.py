"""InvestmentDecision@v1 — the canonical, hash-pinned CIO decision envelope.

One artifact, one truth: every final investment recommendation produced by the
converged office is an `InvestmentDecision@v1`. It pins:

  - the CHAIR (Alex) final position
  - the COMMITTEE result (cio_committee.convene)
  - the EVIDENCE spine (list of EvidenceRef@v1 from cio_evidence_ref)
  - actionability and the conditions that would change the view
  - a deterministic decision_id (content hash) for downstream idempotency

Downstream consumers (action ledger, notification outbox, outcome store,
two-way curation) all key off decision_id so one decision yields exactly one
action and one operator notification.

Pure, provider-call-free. No broker/order/stop/2FA authority. No writes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_committee import CommitteeResult, convene, CommitteeVote
from scripts.lib.cio_evidence_ref import (
    EvidenceRef,
    gate_action,
    QUALITY_STATE_AVAILABLE,
)

SCHEMA_VERSION = "InvestmentDecision@v1"

# ── Final position enum (chair) ───────────────────────────────────────────────

POSITION_BUY = "BUY"
POSITION_SELL = "SELL"
POSITION_SELL_TAXABLE = "SELL_TAXABLE"
POSITION_TRIM = "TRIM"
POSITION_HOLD = "HOLD"
POSITION_NO_ACTION = "NO_ACTION"
POSITION_DEFER = "DEFER"

VALID_FINAL_POSITIONS = frozenset({
    POSITION_BUY,
    POSITION_SELL,
    POSITION_SELL_TAXABLE,
    POSITION_TRIM,
    POSITION_HOLD,
    POSITION_NO_ACTION,
    POSITION_DEFER,
})

# Positions that lean toward acting (and therefore require an evidence gate).
EXECUTION_POSITIONS = frozenset({
    POSITION_BUY,
    POSITION_SELL,
    POSITION_SELL_TAXABLE,
    POSITION_TRIM,
})

# ── Actionability enum ────────────────────────────────────────────────────────

ACTIONABILITY_READY = "READY_FOR_OPERATOR"
ACTIONABILITY_NEEDS_EVIDENCE = "NEEDS_MORE_EVIDENCE"
ACTIONABILITY_CONFLICT = "CONFLICT_UNRESOLVED"

VALID_ACTIONABILITY = frozenset({
    ACTIONABILITY_READY,
    ACTIONABILITY_NEEDS_EVIDENCE,
    ACTIONABILITY_CONFLICT,
})

# ── Fact-dump rejection patterns (shared with cio_advisory_schema) ────────────

FACT_DUMP_PATTERNS = (
    "here is the data",
    "here are the facts",
    "summary of",
    "data dump",
    "raw data",
    "as requested",
    "per the data",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonicalize(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _content_hash(decision: "InvestmentDecision") -> str:
    """Deterministic content hash over the decision's *material* fields.

    Excludes bookkeeping identifiers/timestamps that vary across re-construction
    (decision_id, created_at, evidence ref_id, evidence observed_at) so that the
    same logical decision always hashes identically. Provenance fields (source,
    source_record_id, source_timestamp, quality_state, value_hash) are retained.
    """
    evidence: list[dict[str, Any]] = []
    for r in decision.evidence_refs:
        d = r.to_dict()
        d.pop("ref_id", None)
        d.pop("observed_at", None)
        evidence.append(d)

    body: dict[str, Any] = {
        "schema_version": decision.schema_version,
        "parent_run_id": decision.parent_run_id,
        "final_position": decision.final_position,
        "actionability": decision.actionability,
        "confidence": decision.confidence,
        "symbols": [str(s).upper() for s in decision.symbols],
        "authority": decision.authority,
        "committee": decision.committee.to_dict(),
        "evidence_refs": evidence,
        "required_domains": list(decision.required_domains),
        "rationale_linked_to_evidence": decision.rationale_linked_to_evidence,
        "conditions_to_change_view": list(decision.conditions_to_change_view),
        "material_risks": list(decision.material_risks),
        "how_disagreements_were_resolved": decision.how_disagreements_were_resolved,
    }
    return hashlib.sha256(_canonicalize(body).encode("utf-8")).hexdigest()


@dataclass
class InvestmentDecision:
    """Canonical CIO decision envelope. See module docstring."""

    parent_run_id: str
    final_position: str
    committee: CommitteeResult
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    rationale_linked_to_evidence: str = ""
    conditions_to_change_view: list[str] = field(default_factory=list)
    material_risks: list[str] = field(default_factory=list)
    actionability: str = ACTIONABILITY_NEEDS_EVIDENCE
    how_disagreements_were_resolved: str = ""
    required_domains: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    confidence: float = 0.5
    authority: str = "READ_ONLY_ADVISORY"
    schema_version: str = SCHEMA_VERSION
    decision_id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.final_position not in VALID_FINAL_POSITIONS:
            raise ValueError(
                f"Invalid final_position {self.final_position!r}; "
                f"expected one of {sorted(VALID_FINAL_POSITIONS)}"
            )
        if self.actionability not in VALID_ACTIONABILITY:
            raise ValueError(
                f"Invalid actionability {self.actionability!r}; "
                f"expected one of {sorted(VALID_ACTIONABILITY)}"
            )
        if self.authority != "READ_ONLY_ADVISORY":
            raise ValueError("authority must be READ_ONLY_ADVISORY")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if not self.created_at:
            self.created_at = _now()
        if not self.decision_id:
            self.decision_id = _content_hash(self)

    # ── helpers ───────────────────────────────────────────────────────────

    @property
    def is_execution(self) -> bool:
        return self.final_position in EXECUTION_POSITIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "parent_run_id": self.parent_run_id,
            "final_position": self.final_position,
            "actionability": self.actionability,
            "confidence": self.confidence,
            "symbols": [str(s).upper() for s in self.symbols],
            "authority": self.authority,
            "committee": self.committee.to_dict(),
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
            "required_domains": list(self.required_domains),
            "rationale_linked_to_evidence": self.rationale_linked_to_evidence,
            "conditions_to_change_view": list(self.conditions_to_change_view),
            "material_risks": list(self.material_risks),
            "how_disagreements_were_resolved": self.how_disagreements_were_resolved,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        return _canonicalize(self.to_dict())

    def validate(self) -> list[str]:
        """Fail-closed validation. Returns a list of errors (empty = valid)."""
        errors: list[str] = []

        if not self.parent_run_id:
            errors.append("parent_run_id is required")
        if not self.rationale_linked_to_evidence:
            errors.append("rationale_linked_to_evidence is required")
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}")

        # Fact-dump rejection
        rec = self.rationale_linked_to_evidence.lower()
        for pattern in FACT_DUMP_PATTERNS:
            if rec.startswith(pattern):
                errors.append(
                    f"rationale appears to be a fact dump: {self.rationale_linked_to_evidence[:80]}..."
                )
                break

        # Committee quorum + consensus coherence
        if not self.committee.quorum_met:
            errors.append(
                f"committee quorum not met ({self.committee.consensus}) — cannot finalize"
            )

        # Actionability coherence
        if self.committee.consensus == "BLOCKED_DEFENSE":
            errors.append("defense veto blocks finalization")
        if self.committee.consensus == "MIXED" and self.actionability == ACTIONABILITY_READY:
            errors.append(
                "committee is MIXED (conflict unresolved) — cannot be READY_FOR_OPERATOR "
                "without a resolved chair override"
            )

        # Material disagreement must be resolved if marked READY
        if (
            self.committee.material_disagreements
            and self.actionability == ACTIONABILITY_READY
            and not self.how_disagreements_were_resolved
        ):
            errors.append(
                "material disagreements exist but how_disagreements_were_resolved is empty "
                "— Alex must explain the resolution, not blind-vote"
            )

        # Evidence gate for execution-leaning positions
        if self.is_execution:
            gate = gate_action(self.evidence_refs, self.required_domains)
            if not gate["ok"]:
                errors.append(
                    f"execution position {self.final_position} fails evidence gate: "
                    f"missing={gate['missing_domains']} blocking={gate['blocking_domains']}"
                )

        # Conditions to change view required for any non-defer decision
        if self.final_position != POSITION_DEFER and not self.conditions_to_change_view:
            errors.append("conditions_to_change_view is required")

        return errors

    def is_valid(self) -> bool:
        return not self.validate()


# ── Builders ──────────────────────────────────────────────────────────────────


def build_decision(
    *,
    parent_run_id: str,
    final_position: str,
    committee_votes: list[CommitteeVote],
    evidence_refs: list[EvidenceRef],
    rationale_linked_to_evidence: str,
    conditions_to_change_view: list[str],
    material_risks: Optional[list[str]] = None,
    actionability: str = ACTIONABILITY_NEEDS_EVIDENCE,
    how_disagreements_were_resolved: str = "",
    required_domains: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
    confidence: float = 0.5,
    quorum: int = 3,
) -> InvestmentDecision:
    """Construct a decision from committee votes + evidence, computing consensus."""
    committee = convene(committee_votes, quorum=quorum)
    decision = InvestmentDecision(
        parent_run_id=parent_run_id,
        final_position=final_position,
        committee=committee,
        evidence_refs=list(evidence_refs),
        rationale_linked_to_evidence=rationale_linked_to_evidence,
        conditions_to_change_view=list(conditions_to_change_view),
        material_risks=list(material_risks or []),
        actionability=actionability,
        how_disagreements_were_resolved=how_disagreements_were_resolved,
        required_domains=list(required_domains or []),
        symbols=[str(s).upper() for s in (symbols or [])],
        confidence=confidence,
    )
    return decision


def decision_to_action_payload(
    decision: InvestmentDecision,
    *,
    title: str = "",
) -> dict[str, Any]:
    """Map an InvestmentDecision@v1 to a CIO action-ledger payload.

    idempotency_key = decision_id → one decision yields at most one action.
    Execution positions are NOT authorized here; the action is advisory only.
    """
    return {
        "cio_action_id": f"action_{decision.decision_id[:12]}",
        "idempotency_key": f"decision:{decision.decision_id}",
        "title": title or f"CIO decision: {decision.final_position} {','.join(decision.symbols) or 'book'}",
        "recommendation": decision.rationale_linked_to_evidence,
        "why_now": " ; ".join(decision.committee.material_disagreements) or "committee consensus",
        "evidence_refs": [r.to_dict() for r in decision.evidence_refs],
        "affected_symbols": list(decision.symbols),
        "operator_decision_required": decision.actionability == ACTIONABILITY_READY,
        "followup_condition": " ; ".join(decision.conditions_to_change_view)[:500],
        "cio_artifact_id": decision.decision_id,
        "origin_run_id": decision.parent_run_id,
    }
