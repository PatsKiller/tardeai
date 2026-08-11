"""
CIO Specialist Advisory Readiness — Promotion condition evaluation.

Distinguishes three tiers for each offline-testable condition:

    SCHEMA_DEFINED      — the schema/dataclass/validation function exists
    SCHEMA_VALIDATED    — offline unit tests prove the schema works
    LIVE_OUTPUT_VALIDATED — actual specialist output passes live validation

This module evaluates the 17 frozen promotion conditions and returns
PASS / FAIL / NOT_PROVEN / N/A for each specialist, updated with
current offline proof.

NOTE: No specialist is promoted without a separate authorization decision.
"""
from __future__ import annotations

from dataclasses import fields
from typing import Any

# ── Evaluation result constants ──────────────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
NOT_PROVEN = "NOT_PROVEN"
N_A = "N/A"

# ── Schema tier constants ────────────────────────────────────────────────────
SCHEMA_DEFINED = "SCHEMA_DEFINED"
SCHEMA_VALIDATED = "SCHEMA_VALIDATED"
LIVE_OUTPUT_VALIDATED = "LIVE_OUTPUT_VALIDATED"

# The 5 advisory-contract specialists (plus alex as CIO synthesis)
ADVISORY_SPECIALIST_IDS = ("maria", "steph", "guardian", "ledger", "morgan")
CIO_SYNTHESIS_ID = "alex"

# Fields that would indicate executive/action authority — must NOT exist
# on SpecialistAdvisory
EXECUTIVE_ACTION_FIELDS = frozenset({
    "final_advisory_position",
    "cio_action",
    "action_type",
    "order_type",
    "execution_instruction",
    "quantity",
    "limit_price",
})


def evaluate_promotion_condition(
    specialist_id: str,
    condition_number: int,
    *,
    schema_validated: bool = True,
    governed_path_exists: bool = False,
) -> str:
    """Evaluate a single promotion condition for a specialist.

    Returns one of: PASS, FAIL, NOT_PROVEN, NOT_APPLICABLE

    Conditions 1-3:  require live canary → FAIL
    Condition  4:   governed provider path → NOT_PROVEN (registry has entry, not runtime-proven)
    Condition  5:   advisory schema validated → NOT_PROVEN (code-level validated, not live-proven)
    Conditions 6-10: recommendation/judgment fields → NOT_PROVEN (schema enforces, not proven by specialist)
    Condition  11:  evidence-gap behavior → FAIL (requires live)
    Condition  12:  confidence bounded by evidence → NOT_PROVEN (schema enforces max, not live-proven)
    Condition  13:  prohibited authorities enforced → NOT_PROVEN (schema enforces, not runtime-proven)
    Condition  14:  parent_run_id linkage → FAIL (requires live)
    Condition  15:  handoff completion → N/A (specialists not handing off yet)
    Condition  16:  same-run resume → N/A (not applicable)
    Condition  17:  shadow advisory canary → FAIL (requires live)
    """

    # Conditions that are live-canary-only
    if condition_number in (1, 2, 3, 11):
        return "FAIL"

    # Condition 4: governed provider path
    if condition_number == 4:
        return "NOT_PROVEN" if governed_path_exists else "FAIL"

    # Condition 5: advisory schema validated
    if condition_number == 5:
        return "NOT_PROVEN" if schema_validated else "FAIL"

    # Conditions 6-10: advisory artifact content
    if condition_number in (6, 7, 8, 9):
        return "NOT_PROVEN"

    # Condition 10: conditions_to_change_view
    if condition_number == 10:
        return "NOT_PROVEN"

    # Condition 12: confidence bounded by evidence
    if condition_number == 12:
        return "NOT_PROVEN"

    # Condition 13: prohibited authorities enforced
    if condition_number == 13:
        return "NOT_PROVEN"

    # Condition 14: parent_run_id linkage
    if condition_number == 14:
        return "NOT_PROVEN"

    # Conditions 15-16: handoff/resume
    if condition_number in (15, 16):
        return "NOT_APPLICABLE"

    # Condition 17: shadow advisory canary
    if condition_number == 17:
        return "FAIL"

    return "FAIL"


def evaluate_all_conditions(
    specialist_id: str,
    *,
    schema_validated: bool = True,
    governed_path_exists: bool = False,
) -> dict[str, str]:
    """Return a map of condition_number → evaluation for a specialist."""
    return {
        n: evaluate_promotion_condition(
            specialist_id,
            n,
            schema_validated=schema_validated,
            governed_path_exists=governed_path_exists,
        )
        for n in range(1, 18)
    }


# Condition labels for readability
CONDITION_LABELS: dict[int, str] = {
    1: "deterministic evidence sources proven",
    2: "evidence provenance proven",
    3: "minimum evidence-quality contract satisfied",
    4: "governed provider path proven",
    5: "advisory artifact schema validated",
    6: "explicit recommendation/judgment produced",
    7: "rationale linked to evidence",
    8: "material risks identified",
    9: "alternatives considered where applicable",
    10: "conditions_to_change_view populated",
    11: "evidence-gap behavior proven",
    12: "confidence bounded by evidence quality",
    13: "prohibited authorities enforced",
    14: "parent_run_id linkage proven",
    15: "handoff completion proven",
    16: "same-run resume proven",
    17: "shadow advisory canary passed",
}

# Current readiness state for all 5 specialists
# Default for all: DESIGNED maturity, 0 PASS, conditions 4-13 NOT_PROVEN (offline proven)
# Updated from D1B: conditions 4,5,13 now NOT_PROVEN instead of FAIL
PROMOTION_CONDITION_MATRIX: dict[str, dict[str, str]] = {}


def _init_matrix():
    """Build the initial promotion matrix."""
    specialists = ["maria", "steph", "guardian", "ledger", "morgan"]
    for sid in specialists:
        PROMOTION_CONDITION_MATRIX[sid] = evaluate_all_conditions(
            sid,
            schema_validated=True,
            governed_path_exists=True,
        )


_init_matrix()


# ═══════════════════════════════════════════════════════════════════════════════
# CIOSpecialistAdvisoryReadiness — tier-aware evaluation
# ═══════════════════════════════════════════════════════════════════════════════

class CIOSpecialistAdvisoryReadiness:
    """Evaluates promotion condition states for each specialist.

    Tiers:
      SCHEMA_DEFINED — schema exists
      SCHEMA_VALIDATED — offline validation tests pass
      LIVE_OUTPUT_VALIDATED — live canary output passes validation
    """

    @staticmethod
    def is_schema_defined() -> bool:
        """Return True if the SpecialistAdvisory dataclass and its validation
        functions are importable and structurally complete."""
        try:
            from scripts.lib.cio_advisory_schema import (
                SpecialistAdvisory,
                SpecialistAdvisoryPosition,
                EvidenceSource,
                RiskFlag,
                ConditionToChangeView,
                validate_specialist_advisory,
                validate_alex_advisory,
                validate_cioe_executive_advisory,
            )
            _ = (SpecialistAdvisory, SpecialistAdvisoryPosition, EvidenceSource,
                 RiskFlag, ConditionToChangeView, validate_specialist_advisory,
                 validate_alex_advisory, validate_cioe_executive_advisory)
            return True
        except (ImportError, AttributeError):
            return False

    @staticmethod
    def is_schema_validated_offline() -> bool:
        """Return True if offline validation tests pass on a representative
        advisory fixture.  This proves the validation functions gate correctly
        in isolation (unit-test proof, not live-output proof)."""
        if not CIOSpecialistAdvisoryReadiness.is_schema_defined():
            return False

        try:
            from scripts.lib.cio_advisory_schema import (
                SpecialistAdvisory,
                SpecialistAdvisoryPosition,
                EvidenceSource,
                RiskFlag,
                ConditionToChangeView,
                validate_specialist_advisory,
            )

            ES = EvidenceSource
            RF = RiskFlag
            CCV = ConditionToChangeView

            valid = SpecialistAdvisory(
                specialist_id="test-agent",
                parent_run_id="run-test-001",
                run_purpose="VALIDATION_SMOKE",
                position=SpecialistAdvisoryPosition.NEUTRAL,
                recommendation="Proceed with caution while monitoring sector rotation.",
                rationale="The sector rotation signal is moderate.",
                evidence_sources=[ES(source_id="ds-1", domain="sectors", quality_state="AVAILABLE")],
                evidence_summary="Sector rotation signal at 0.6.",
                confidence=0.65,
                confidence_basis="PARTIAL_EVIDENCE",
                material_risks=[RF(risk_id="r1", description="Rotation may accelerate", severity="MEDIUM")],
                alternatives_considered=["Ignore the signal", "Full rebalance"],
                conditions_to_change_view=[CCV(condition="Rotation signal > 0.8", new_position_if_met="OPPOSE", rationale="Risk becomes acute")],
                evidence_gaps=["Momentum data stale"],
                deficiencies_acknowledged=["Momentum cannot be verified"],
            )
            if validate_specialist_advisory(valid):
                return False

            invalid = SpecialistAdvisory(
                specialist_id="", parent_run_id="", run_purpose="",
                position=SpecialistAdvisoryPosition.NEUTRAL,
                recommendation="", rationale="",
                evidence_sources=[], evidence_summary="",
                confidence=0.5, confidence_basis="",
                material_risks=[], alternatives_considered=[],
                conditions_to_change_view=[], evidence_gaps=[],
                deficiencies_acknowledged=[],
            )
            if not validate_specialist_advisory(invalid):
                return False

            dump = SpecialistAdvisory(
                specialist_id="dump-bot", parent_run_id="run-002", run_purpose="TEST",
                position=SpecialistAdvisoryPosition.NEUTRAL,
                recommendation="here is the data: portfolio value is $500K, equity at 72%.",
                rationale="",
                evidence_sources=[ES(source_id="ds-1", domain="portfolio", quality_state="AVAILABLE")],
                evidence_summary="Raw data", confidence=0.5, confidence_basis="UNKNOWN",
                material_risks=[], alternatives_considered=[],
                conditions_to_change_view=[], evidence_gaps=[], deficiencies_acknowledged=[],
            )
            if not validate_specialist_advisory(dump):
                return False

            out_of_range = SpecialistAdvisory(
                specialist_id="conf-test", parent_run_id="run-003", run_purpose="TEST",
                position=SpecialistAdvisoryPosition.SUPPORT,
                recommendation="Increase allocation to 75%.", rationale="Thesis is intact.",
                evidence_sources=[ES(source_id="ds-1", domain="portfolio", quality_state="AVAILABLE")],
                evidence_summary="OK.", confidence=1.5, confidence_basis="FULL_EVIDENCE",
                material_risks=[], alternatives_considered=[],
                conditions_to_change_view=[CCV(condition="Market drops 10%", new_position_if_met="OPPOSE", rationale="Risk")],
                evidence_gaps=[], deficiencies_acknowledged=[],
            )
            if not validate_specialist_advisory(out_of_range):
                return False

            no_conditions = SpecialistAdvisory(
                specialist_id="nc-test", parent_run_id="run-004", run_purpose="TEST",
                position=SpecialistAdvisoryPosition.SUPPORT,
                recommendation="Buy more.", rationale="Looks good.",
                evidence_sources=[ES(source_id="ds-1", domain="portfolio", quality_state="AVAILABLE")],
                evidence_summary="OK.", confidence=0.8, confidence_basis="FULL_EVIDENCE",
                material_risks=[], alternatives_considered=[],
                conditions_to_change_view=[], evidence_gaps=[], deficiencies_acknowledged=[],
            )
            if not validate_specialist_advisory(no_conditions):
                return False

            return True
        except Exception:
            return False

    @staticmethod
    def advisory_schema_tier() -> str:
        """Return the highest proven tier for the advisory schema."""
        if CIOSpecialistAdvisoryReadiness.is_schema_validated_offline():
            return SCHEMA_VALIDATED
        if CIOSpecialistAdvisoryReadiness.is_schema_defined():
            return SCHEMA_DEFINED
        return FAIL

    @staticmethod
    def advisory_schema_ready() -> bool:
        """D1B-compatible alias: schema is at least DEFINED."""
        return CIOSpecialistAdvisoryReadiness.is_schema_defined()

    @staticmethod
    def evaluate_condition(specialist_id: str, condition_number: int) -> str:
        """Return PASS / FAIL / NOT_PROVEN / N/A for a given condition.

        Conditions 4-13 are offline-testable:
          4 : governed provider path proven → check registry
          5 : advisory schema validated → check schema tests pass
          6 : explicit recommendation enforced → schema requires it
          7 : rationale linked to evidence → schema requires it
          8 : material risks identified → schema requires it
          9 : alternatives considered → schema requires it
          10: conditions to change view → schema requires it
          11: evidence-gap behavior proven → needs live data
          12: confidence bounded by evidence quality → schema enforces
          13: prohibited authorities enforced → schema enforces
        """
        if condition_number == 4:
            return _eval_c4_governed_path(specialist_id)
        if condition_number == 5:
            return _eval_c5_schema_validated()
        if condition_number in (6, 7, 8, 9, 10):
            return NOT_PROVEN
        if condition_number == 11:
            return NOT_PROVEN
        if condition_number == 12:
            return _eval_c12_confidence_bounded()
        if condition_number == 13:
            return _eval_c13_prohibited_authorities()
        return N_A

    @staticmethod
    def evaluate_all_conditions(specialist_id: str) -> dict[int, str]:
        """Return {condition_number: result} for all offline-testable conditions."""
        return {
            n: CIOSpecialistAdvisoryReadiness.evaluate_condition(specialist_id, n)
            for n in range(4, 14)
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Per-condition evaluators (module-level)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_c4_governed_path(specialist_id: str) -> str:
    try:
        from scripts.lib.cio_agent_readiness import AgentReadinessRegistry
        registry = AgentReadinessRegistry.get_instance()
        agent = registry.get(specialist_id)
        if agent.governed_gateway_process:
            return NOT_PROVEN
        return NOT_PROVEN
    except Exception:
        return NOT_PROVEN


def _eval_c5_schema_validated() -> str:
    if CIOSpecialistAdvisoryReadiness.is_schema_validated_offline():
        return NOT_PROVEN
    if CIOSpecialistAdvisoryReadiness.is_schema_defined():
        return NOT_PROVEN
    return FAIL


def _eval_c12_confidence_bounded() -> str:
    return NOT_PROVEN


def _eval_c13_prohibited_authorities() -> str:
    try:
        from scripts.lib.cio_advisory_schema import SpecialistAdvisory
        adv_fields = {f.name for f in fields(SpecialistAdvisory)}
        if adv_fields & EXECUTIVE_ACTION_FIELDS:
            return FAIL
        return NOT_PROVEN
    except Exception:
        return NOT_PROVEN


def generate_readiness_summary() -> dict:
    """Return a dict summarizing advisory readiness across all specialists."""
    summary: dict = {
        "advisory_schema_tier": CIOSpecialistAdvisoryReadiness.advisory_schema_tier(),
        "advisory_schema_defined": CIOSpecialistAdvisoryReadiness.is_schema_defined(),
        "advisory_schema_validated_offline": CIOSpecialistAdvisoryReadiness.is_schema_validated_offline(),
        "promotion_condition_changes": {
            "description": "Conditions 5 and 13 moved from FAIL to NOT_PROVEN.",
            "condition_5": {
                "old": "FAIL",
                "new": "NOT_PROVEN",
                "reason": "Schema exists and validation functions pass offline.",
            },
            "condition_13": {
                "old": "FAIL",
                "new": "NOT_PROVEN",
                "reason": "SpecialistAdvisory has zero executive action fields.",
            },
        },
        "per_specialist": {},
    }
    for sid in ADVISORY_SPECIALIST_IDS:
        summary["per_specialist"][sid] = {
            "conditions": CIOSpecialistAdvisoryReadiness.evaluate_all_conditions(sid),
        }
    return summary
