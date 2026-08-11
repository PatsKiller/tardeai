"""CIO Advisory Schema — Typed advisory artifacts for specialist agents and Alex.

Defines the frozen advisory contract: SpecialistAdvisory (per-specialist position)
and AlexCIOAdvisory (final CIO synthesis). Includes validation functions that
reject fact-dump-only responses — every advisory MUST contain an explicit
recommendation, rationale linked to evidence, and position.

Gate-D component. Provider-call-free — pure schema and validation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Advisory position enum — the frozen advisory contract
# ═══════════════════════════════════════════════════════════════════════════════

class SpecialistAdvisoryPosition(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    NEUTRAL = "NEUTRAL"
    DEFER = "DEFER"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# ═══════════════════════════════════════════════════════════════════════════════
# Typed advisory dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EvidenceSource:
    source_id: str
    domain: str
    quality_state: str          # AVAILABLE | PARTIAL | STALE | DATA_UNAVAILABLE
    as_of: str = ""
    source_ref: str = ""


@dataclass
class RiskFlag:
    risk_id: str
    description: str
    severity: str               # HIGH | MEDIUM | LOW
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class ConditionToChangeView:
    condition: str
    new_position_if_met: str
    rationale: str


@dataclass
class SpecialistAdvisory:
    """Per-specialist advisory artifact — the frozen advisory contract.

    Every specialist MUST produce:
      - An explicit position (SUPPORT/OPPOSE/NEUTRAL/DEFER/INSUFFICIENT_EVIDENCE)
      - A recommendation (what should Alex/the system DO?)
      - Rationale linked to evidence sources
      - Material risks identified
      - Conditions that would change their view

    Prohibited: fact-dump-only responses with no position, blind data dumps,
    executing any action (read-only advisory only).
    """
    specialist_id: str
    parent_run_id: str
    run_purpose: str
    position: SpecialistAdvisoryPosition
    recommendation: str
    rationale: str
    evidence_sources: list[EvidenceSource]
    evidence_summary: str
    confidence: float                          # 0.0-1.0, bounded by evidence quality
    confidence_basis: str                      # e.g. "FULL_EVIDENCE", "PARTIAL_EVIDENCE", "STALE_EVIDENCE"
    material_risks: list[RiskFlag]
    alternatives_considered: list[str]
    conditions_to_change_view: list[ConditionToChangeView]
    evidence_gaps: list[str]
    deficiencies_acknowledged: list[str]
    advisory_artifact_id: str = ""
    created_at: str = ""

    @property
    def has_explicit_judgment(self) -> bool:
        return bool(self.recommendation and self.rationale)

    @property
    def is_fact_dump_only(self) -> bool:
        has_judgment = self.has_explicit_judgment
        has_position = self.position is not None
        return not has_judgment or not has_position

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["position"] = self.position.value if isinstance(self.position, SpecialistAdvisoryPosition) else self.position
        d["evidence_sources"] = [
            {k: v for k, v in asdict(es).items() if v}
            for es in self.evidence_sources
        ]
        d["material_risks"] = [asdict(r) for r in self.material_risks]
        d["conditions_to_change_view"] = [asdict(c) for c in self.conditions_to_change_view]
        return {k: v for k, v in d.items() if v or k == "position"}

    def compute_content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class AlexCIOAdvisory:
    """Alex's final CIO synthesis advisory — reconciles all specialist positions.

    Alex MUST:
      - Acknowledge ALL specialist positions, not just majority
      - Note material disagreements and how they were resolved
      - Produce an explicit final_advisory_position
      - Never blind-vote across specialists
      - Justify why dissenting views were overruled (not ignored)
    """
    parent_run_id: str
    final_advisory_position: str              # BUY | SELL | SELL_TAXABLE | TRIM | HOLD | NO_ACTION | DEFER
    recommendation: str
    specialist_positions: dict[str, str]       # specialist_id → position
    material_disagreements: list[str]
    how_disagreements_were_resolved: str
    actionability: str                         # READY_FOR_OPERATOR | NEEDS_MORE_EVIDENCE | CONFLICT_UNRESOLVED
    evidence_quality_summary: str
    confidence: float                          # 0.0-1.0
    confidence_basis: str
    material_risks: list[RiskFlag]
    rationale_linked_to_evidence: str
    alternatives_considered: list[str]
    conditions_to_change_view: list[ConditionToChangeView]
    evidence_gaps: list[str]
    advisory_artifact_id: str = ""
    created_at: str = ""

    @property
    def has_resolved_disagreements(self) -> bool:
        if not self.material_disagreements:
            return True
        return bool(self.how_disagreements_were_resolved)

    @property
    def is_blind_vote(self) -> bool:
        if self.material_disagreements and not self.how_disagreements_were_resolved:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["material_risks"] = [asdict(r) for r in self.material_risks]
        d["conditions_to_change_view"] = [asdict(c) for c in self.conditions_to_change_view]
        return {k: v for k, v in d.items() if v}

    def compute_content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# Validation — reject fact-dump-only responses
# ═══════════════════════════════════════════════════════════════════════════════

FACT_DUMP_PATTERNS = (
    "here is the data",
    "here are the facts",
    "summary of",
    "data dump",
    "raw data",
    "as requested",
    "per the data",
)


def validate_specialist_advisory(advisory: SpecialistAdvisory) -> list[str]:
    errors: list[str] = []

    if advisory.is_fact_dump_only:
        errors.append(
            f"Specialist '{advisory.specialist_id}' produced a fact-dump-only advisory "
            f"— no explicit judgment or position"
        )

    if not advisory.specialist_id:
        errors.append("specialist_id is required")

    if not advisory.parent_run_id:
        errors.append("parent_run_id is required")

    if not advisory.recommendation:
        errors.append("recommendation is required — specialist must recommend an action")

    if not advisory.rationale:
        errors.append("rationale is required — specialist must explain why")

    if not advisory.evidence_sources:
        errors.append("at least one evidence_source is required")

    if advisory.confidence < 0.0 or advisory.confidence > 1.0:
        errors.append(
            f"confidence {advisory.confidence} out of range [0.0, 1.0]"
        )

    rec_lower = advisory.recommendation.lower()
    for pattern in FACT_DUMP_PATTERNS:
        if rec_lower.startswith(pattern):
            errors.append(
                f"Recommendation appears to be a fact dump: "
                f"'{advisory.recommendation[:80]}...'"
            )
            break

    if not advisory.conditions_to_change_view:
        errors.append(
            "conditions_to_change_view is required — specialist must state "
            "what would change their view"
        )

    return errors


def validate_alex_advisory(advisory: AlexCIOAdvisory) -> list[str]:
    errors: list[str] = []

    if not advisory.parent_run_id:
        errors.append("parent_run_id is required")

    if not advisory.final_advisory_position:
        errors.append("final_advisory_position is required")

    if not advisory.recommendation:
        errors.append("recommendation is required")

    if not advisory.specialist_positions:
        errors.append("specialist_positions is required — must document all specialist views")

    if advisory.material_disagreements and not advisory.how_disagreements_were_resolved:
        errors.append(
            "Material disagreements exist but how_disagreements_were_resolved is empty. "
            "Alex must explain how disagreements were resolved, not blind-vote."
        )

    if advisory.confidence < 0.0 or advisory.confidence > 1.0:
        errors.append(
            f"confidence {advisory.confidence} out of range [0.0, 1.0]"
        )

    if not advisory.rationale_linked_to_evidence:
        errors.append("rationale_linked_to_evidence is required")

    valid_positions = set(p.value for p in SpecialistAdvisoryPosition)
    for spec_id, pos in advisory.specialist_positions.items():
        if pos not in valid_positions and pos not in ("SUPPORT_WITH_CONDITIONS",):
            errors.append(
                f"Unknown position '{pos}' for specialist '{spec_id}'. "
                f"Valid: {sorted(valid_positions)}"
            )

    return errors


def validate_cioe_executive_advisory(advisory: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    
    required_fields = (
        "specialist_id", "parent_run_id", "run_purpose",
        "position", "recommendation", "rationale",
    )
    for field in required_fields:
        if field not in advisory or not advisory[field]:
            errors.append(f"Missing required field: {field}")

    if "evidence_sources" not in advisory or not advisory["evidence_sources"]:
        errors.append("evidence_sources is required — at least one evidence source must be cited")

    if advisory.get("confidence") is not None:
        conf = float(advisory["confidence"])
        if conf < 0.0 or conf > 1.0:
            errors.append(f"confidence {conf} out of range [0.0, 1.0]")

    pos = advisory.get("position")
    valid = {p.value for p in SpecialistAdvisoryPosition}
    if pos and pos not in valid and pos != "SUPPORT_WITH_CONDITIONS":
        errors.append(f"Invalid position '{pos}'. Valid: {sorted(valid)}")

    if not advisory.get("conditions_to_change_view"):
        errors.append("conditions_to_change_view is required")

    recommendation = (advisory.get("recommendation") or "").lower()
    for pattern in FACT_DUMP_PATTERNS:
        if recommendation.startswith(pattern):
            errors.append(
                f"Recommendation appears to be a fact dump: "
                f"'{advisory['recommendation'][:80]}...'"
            )
            break

    return errors
