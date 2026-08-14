"""Research governance — promotion gate RG-0..RG-11 (PR-R1).

The promotion ladder for a single hypothesis/fact, deliberately ASYMMETRIC and
TYPE-AWARE. The authority model:

  * methodology evidence MAY BLOCK a promotion,
  * deterministic instrument mechanics MAY establish CONDITIONAL mechanical facts,
  * risk evidence MAY VETO or size down,
  * valuation research MAY alter a valuation RANGE,
  * portfolio-construction research MAY change candidate SIZING,
  * seasonality MAY modify STAGING/TIMING,

  ... and NONE of them independently creates trade authority.

RG ladder (restored to the approved plan):
  RG-0  source_registered
  RG-1  source_claim_complete
  RG-2  hypothesis_frozen          (empirical only)
  RG-3  reproducible               (empirical only)
  RG-4  in_sample_reproduced       (empirical only)
  RG-5  oos_supported              (empirical only)
  RG-6  multiple_testing_applied   (empirical only)
  RG-7  reality_check_passed       (empirical only)
  RG-8  robust                     (empirical only)
  RG-9  graded_and_influence       (shared; grade + influence + no authority)
  RG-10 decision_use_audit         (contract-only in R1; live in R4)
  RG-11 live_degradation_retirement(contract-only in R1; live in R4)

FAIL-CLOSED semantics (the point of this subsystem): a gate is PASS only when
the evidence it requires is positively present and correctly bound to the
hypothesis being promoted. A MISSING field is a FAIL, never a PASS. In
particular, statistical evidence (multiple-testing, Reality Check) must be
BOUND to the current frozen trial family by ID + hash, not merely present.

Type-specific requirements replace the empirical ladder for non-empirical facts.

Grade ceiling (never bypassable):
  A/B -> CIO_CONTEXT_ELIGIBLE (only if the profile fully passes)
  C   -> EXPLORATORY_SHADOW (never live CIO context)
  D   -> SOURCE_ONLY (no material CIO influence)
  X   -> INVALIDATED (never promoted; blocks)

Pure, deterministic. Operates over a context dict; returns a full report.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass

GATE_IDS: tuple[str, ...] = tuple(f"RG-{i}" for i in range(12))

_EMPIRICAL_TYPES = {EvidenceType.EMPIRICAL_STRATEGY, EvidenceType.EMPIRICAL_FACTOR,
                    EvidenceType.SEASONALITY}

_GRADE_CEILING = {
    EvidenceGrade.A.value: "CIO_CONTEXT_ELIGIBLE",
    EvidenceGrade.B.value: "CIO_CONTEXT_ELIGIBLE",
    EvidenceGrade.C.value: "EXPLORATORY_SHADOW",
    EvidenceGrade.D.value: "SOURCE_ONLY",
    EvidenceGrade.X.value: "INVALIDATED",
}

# Required institutional evidence checklist for Grade A/B empirical/seasonality
# robustness. Each key maps to whether it is required (True) for promotion.
_ROBUSTNESS_REQUIRED = [
    "sample_n",
    "benchmark",
    "subperiods",
    "regimes",
    "costs",
    "outlier_dependence",
    "lookahead_control",
    "survivorship_control",
    "limitations",
]


def _has(ctx: dict, key: str) -> bool:
    return bool(ctx.get(key))


def _evidence_type(ctx: dict) -> Optional[EvidenceType]:
    raw = ctx.get("evidence_type")
    if raw is None:
        return None
    if isinstance(raw, EvidenceType):
        return raw
    try:
        return EvidenceType(raw)
    except ValueError:
        return None


def _is_empirical(ctx: dict) -> bool:
    return _evidence_type(ctx) in _EMPIRICAL_TYPES


def _family_matches(ctx: dict, evidence: dict) -> bool:
    """Statistical evidence must be bound to the current frozen trial family.

    Checks every binding field that is present on BOTH the context and the
    evidence. If the context declares a family/hypothesis/hash and the evidence
    declares a different one, it fails. If the evidence omits the binding field,
    the gate's own required-field check catches that omission.
    """
    ctx_fam = ctx.get("trial_family_id")
    ctx_hash = ctx.get("family_definition_hash")
    ctx_hyp = ctx.get("hypothesis_id")

    if ctx_fam:
        if evidence.get("trial_family_id") and evidence["trial_family_id"] != ctx_fam:
            return False
        if evidence.get("family_id") and evidence["family_id"] != ctx_fam:
            return False
    if ctx_hash and evidence.get("family_definition_hash") and evidence["family_definition_hash"] != ctx_hash:
        return False
    if ctx_hyp and evidence.get("tested_hypothesis_id") and evidence["tested_hypothesis_id"] != ctx_hyp:
        return False
    return True


# -- RG gates ----------------------------------------------------------------

def _gate_0_source_registered(ctx: dict) -> tuple[GateState, str]:
    if _has(ctx, "source_id"):
        return GateState.PASS, "source registered"
    return GateState.FAIL, "no source_id"


def _gate_1_source_claim_complete(ctx: dict) -> tuple[GateState, str]:
    if _has(ctx, "claim") and _has(ctx, "page_or_section") and _has(ctx, "scope"):
        return GateState.PASS, "claim has text, citation, and scope"
    return GateState.FAIL, "claim incomplete (needs text + page/section + scope)"


def _empirical_only(ctx: dict) -> tuple[GateState, str] | None:
    """Return NOT_APPLICABLE for non-empirical types; None = proceed (empirical)."""
    et = _evidence_type(ctx)
    if et is None:
        return GateState.FAIL, "evidence_type missing"
    if et not in _EMPIRICAL_TYPES:
        return GateState.NOT_APPLICABLE, f"empirical gate not required for {et.value}"
    return None


def _gate_2_hypothesis_frozen(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    if not _has(ctx, "protocol_hash"):
        return GateState.FAIL, "no protocol_hash"
    if not _has(ctx, "trial_family_id"):
        return GateState.FAIL, "no trial_family_id"
    if ctx.get("family_frozen") is not True:
        return GateState.FAIL, "family not frozen"
    if not _has(ctx, "family_definition_hash"):
        return GateState.FAIL, "family_definition_hash required for confirmatory family"
    return GateState.PASS, "hypothesis frozen in trial registry"


def _gate_3_reproducible(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    if _has(ctx, "code_sha") and _has(ctx, "dataset_hash"):
        return GateState.PASS, "code and dataset hashes recorded"
    return GateState.FAIL, "missing code_sha or dataset_hash"


def _gate_4_in_sample_reproduced(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    metric = ctx.get("in_sample_metric")
    threshold = ctx.get("in_sample_threshold")
    if metric is None:
        return GateState.FAIL, "no in-sample reproduction metric"
    if threshold is not None and metric < threshold:
        return GateState.FAIL, f"in-sample metric {metric} below threshold {threshold}"
    return GateState.PASS, "in-sample reproduction meets preregistered threshold"


def _gate_5_oos_supported(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    if ctx.get("oos_supported") is not True:
        return GateState.FAIL, "oos_supported must be True"
    if ctx.get("oos_untouched") is not True:
        return GateState.FAIL, "oos_untouched must be True (missing or consumed => FAIL)"
    return GateState.PASS, "untouched OOS segment supports hypothesis"


def _gate_6_multiple_testing_applied(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    mt = ctx.get("multiple_testing")
    if not isinstance(mt, dict):
        return GateState.FAIL, "multiple_testing result missing"
    for key in ("status", "method", "alpha", "family_id", "family_definition_hash",
                "trial_family_id", "tested_hypothesis_id", "raw_pvalue",
                "adjusted_pvalue", "rejected", "complete_family"):
        if key not in mt:
            return GateState.FAIL, f"multiple_testing missing required field: {key}"
    if mt.get("status") != "OK":
        return GateState.FAIL, f"multiple_testing status != OK: {mt.get('status')}"
    if mt.get("rejected") is not True:
        return GateState.FAIL, "hypothesis did not survive multiple-testing correction"
    if mt.get("complete_family") is not True:
        return GateState.FAIL, "multiple_testing family incomplete"
    if mt.get("approx") not in (None, False):
        return GateState.FAIL, "multiple_testing approximation not governed for confirmatory use"
    if not _family_matches(ctx, mt):
        return GateState.FAIL, "multiple_testing result bound to a different family/hypothesis"
    return GateState.PASS, "survives multiple-testing correction on the correct frozen family"


def _gate_7_reality_check_passed(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    rc = ctx.get("reality_check")
    if not isinstance(rc, dict):
        return GateState.FAIL, "no reality-check / data-snooping result"
    for key in ("status", "family_id", "family_definition_hash", "trial_family_id",
                "bootstrap_pvalue", "n_rules", "n_observations", "n_bootstrap",
                "bootstrap_method", "mean_block_length"):
        if key not in rc:
            return GateState.FAIL, f"reality_check missing required field: {key}"
    if rc.get("status") != "OK":
        return GateState.FAIL, f"reality_check status != OK: {rc.get('status')}"
    if rc.get("n_rules", 0) < 2:
        return GateState.FAIL, "reality_check is not a full searched family (>= 2 rules required)"
    if not _family_matches(ctx, rc):
        return GateState.FAIL, "reality_check bound to a different family/hypothesis"
    alpha = ctx.get("reality_check_alpha", 0.05)
    p = rc.get("bootstrap_pvalue")
    if p is None:
        return GateState.FAIL, "reality check produced no p-value"
    if p <= alpha:
        return GateState.PASS, f"reality check p={p:.4f} <= alpha={alpha} on frozen family"
    return GateState.FAIL, f"reality check p={p:.4f} > alpha={alpha}"


def _robustness_state(ctx: dict, key: str) -> str:
    """Return PASS / FAIL / NOT_APPLICABLE-with-reason for a checklist item."""
    rob = ctx.get("robustness")
    if not isinstance(rob, dict):
        return "FAIL"
    val = rob.get(key)
    if val is True:
        return "PASS"
    if val is False or val is None:
        return "FAIL"
    if isinstance(val, str):
        # A string reason is accepted only as an explicit NOT_APPLICABLE-with-reason.
        reason = val.strip().lower()
        if reason.startswith("not_applicable") or reason.startswith("not applicable") or reason.startswith("na:"):
            return "NOT_APPLICABLE"
    return "FAIL"


def _gate_8_robust(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    rob = ctx.get("robustness")
    if not isinstance(rob, dict) or not rob:
        return GateState.FAIL, "robustness evidence empty/missing"
    fails = []
    for key in _ROBUSTNESS_REQUIRED:
        state = _robustness_state(ctx, key)
        if state == "FAIL":
            fails.append(key)
    if fails:
        return GateState.FAIL, f"robustness missing/unsatisfied: {fails}"
    return GateState.PASS, "robustness checklist satisfied (sample N, benchmark, subperiods, regimes, costs, outlier, lookahead, survivorship, limitations)"


def _gate_9_graded_and_influence(ctx: dict) -> tuple[GateState, str]:
    grade = ctx.get("evidence_grade")
    if grade is None:
        return GateState.FAIL, "no evidence grade"
    grade_s = grade.value if isinstance(grade, EvidenceGrade) else str(grade)
    if grade_s not in _GRADE_CEILING:
        return GateState.FAIL, f"invalid evidence grade {grade_s}"
    influence = ctx.get("influence_class")
    valid = {c.value for c in InfluenceClass}
    if influence is None or str(influence) not in valid:
        return GateState.FAIL, "no valid influence class assigned"
    if ctx.get("claims_trade_authority") is True:
        return GateState.FAIL, "research may not claim broker/order/stop authority"
    return GateState.PASS, f"grade {grade_s}, influence {influence}"


def _gate_10_decision_use_audit(ctx: dict) -> tuple[GateState, str]:
    if ctx.get("decision_use_audit_contract") is True:
        return GateState.PASS, "decision-use audit contract present"
    return GateState.NOT_APPLICABLE, "live decision-use audit deferred to R4"


def _gate_11_live_degradation(ctx: dict) -> tuple[GateState, str]:
    if ctx.get("live_degradation_contract") is True:
        return GateState.PASS, "live degradation/retirement monitoring contract present"
    return GateState.NOT_APPLICABLE, "live degradation/retirement deferred to R4"


_GATES: list[tuple[str, str, Callable[[dict], tuple[GateState, str]]]] = [
    ("RG-0", "source_registered", _gate_0_source_registered),
    ("RG-1", "source_claim_complete", _gate_1_source_claim_complete),
    ("RG-2", "hypothesis_frozen", _gate_2_hypothesis_frozen),
    ("RG-3", "reproducible", _gate_3_reproducible),
    ("RG-4", "in_sample_reproduced", _gate_4_in_sample_reproduced),
    ("RG-5", "oos_supported", _gate_5_oos_supported),
    ("RG-6", "multiple_testing_applied", _gate_6_multiple_testing_applied),
    ("RG-7", "reality_check_passed", _gate_7_reality_check_passed),
    ("RG-8", "robust", _gate_8_robust),
    ("RG-9", "graded_and_influence", _gate_9_graded_and_influence),
    ("RG-10", "decision_use_audit", _gate_10_decision_use_audit),
    ("RG-11", "live_degradation_retirement", _gate_11_live_degradation),
]

_REQUIRED_SHARED = ("RG-0", "RG-1", "RG-9")
_EMPIRICAL_GATES = ("RG-2", "RG-3", "RG-4", "RG-5", "RG-6", "RG-7", "RG-8")


def _type_specific_gates(ctx: dict) -> list[tuple[str, str, Callable[[dict], tuple[GateState, str]]]]:
    et = _evidence_type(ctx)
    if et == EvidenceType.DETERMINISTIC_MECHANICS:
        return [
            ("mechanics_definition", "mechanics_definition",
             lambda c: (GateState.PASS, "definition present") if _has(c, "mechanics_definition")
             else (GateState.FAIL, "no mechanics definition")),
            ("units_convention", "units_convention",
             lambda c: (GateState.PASS, "units present") if _has(c, "units_convention")
             else (GateState.FAIL, "no units/convention")),
            ("reference_tests", "reference_tests",
             lambda c: (GateState.PASS, "reference tests passed") if c.get("reference_tests_passed") is True
             else (GateState.FAIL, "deterministic reference tests not passed")),
            ("source_as_of", "source_as_of",
             lambda c: (GateState.PASS, "source/as-of present") if _has(c, "source_as_of")
             else (GateState.FAIL, "no source/as-of for inputs")),
            ("implementation_validation", "implementation_validation",
             lambda c: (GateState.PASS, "implementation validated") if c.get("implementation_validation") is True
             else (GateState.FAIL, "implementation not validated against independent reference")),
        ]
    if et == EvidenceType.POLICY_OR_REGULATORY:
        return [
            ("authoritative_source", "authoritative_source",
             lambda c: (GateState.PASS, "authoritative source present") if _has(c, "authoritative_source")
             else (GateState.FAIL, "no authoritative source")),
            ("effective_date", "effective_date",
             lambda c: (GateState.PASS, "effective date present") if _has(c, "effective_date")
             else (GateState.FAIL, "no effective date")),
            ("jurisdiction", "jurisdiction",
             lambda c: (GateState.PASS, "jurisdiction present") if _has(c, "jurisdiction")
             else (GateState.FAIL, "no jurisdiction/scope")),
            ("freshness_policy", "freshness_policy",
             lambda c: _policy_freshness(c)),
        ]
    if et == EvidenceType.VALUATION_MODEL:
        return [
            ("model_identity", "model_identity",
             lambda c: (GateState.PASS, "model identity present") if _has(c, "model_identity")
             else (GateState.FAIL, "no model identity")),
            ("assumption_provenance", "assumption_provenance",
             lambda c: (GateState.PASS, "assumptions present") if _has(c, "assumption_provenance")
             else (GateState.FAIL, "no assumption provenance")),
            ("scenario_sensitivity", "scenario_sensitivity",
             lambda c: (GateState.PASS, "sensitivity present") if _has(c, "scenario_sensitivity")
             else (GateState.FAIL, "no scenario/sensitivity")),
            ("calibration", "calibration",
             lambda c: _valuation_calibration(c)),
        ]
    return []


def _policy_freshness(ctx: dict) -> tuple[GateState, str]:
    if not _has(ctx, "verified_at"):
        return GateState.FAIL, "policy missing verified_at"
    if not _has(ctx, "current_as_of"):
        return GateState.FAIL, "policy missing current_as_of"
    if ctx.get("freshness_expired") is True:
        return GateState.FAIL, "policy freshness expired (reverification overdue)"
    return GateState.PASS, "policy fresh (verified_at + current_as_of present, not expired)"


def _valuation_calibration(ctx: dict) -> tuple[GateState, str]:
    cal = ctx.get("calibration")
    if not isinstance(cal, dict) or not cal:
        return GateState.FAIL, "valuation calibration must be structured evidence"
    for key in ("calibration_dataset", "calibration_metric", "validation_split"):
        if not cal.get(key):
            return GateState.FAIL, f"valuation calibration missing {key}"
    return GateState.PASS, "valuation calibration structured (dataset + metric + split)"


def run_promotion_gate(ctx: dict) -> dict:
    """Run RG-0..RG-11 plus type-specific gates; apply the grade ceiling."""
    report: dict[str, Any] = {"gate_results": {}, "overall": GateState.PASS.value,
                              "promotion_state": None, "grade_ceiling": None}

    et = _evidence_type(ctx)
    if et is None:
        report["overall"] = GateState.FAIL.value
        report["promotion_state"] = "INVALIDATED"
        report["_reason"] = "evidence_type missing/invalid"
        return report

    for gid, name, fn in _GATES:
        state, reason = fn(ctx)
        report["gate_results"][gid] = {"name": name, "state": state.value, "reason": reason}

    type_gates = _type_specific_gates(ctx)
    for key, name, fn in type_gates:
        state, reason = fn(ctx)
        report["gate_results"][key] = {"name": name, "state": state.value, "reason": reason}

    required = list(_REQUIRED_SHARED)
    if _is_empirical(ctx):
        required.extend(_EMPIRICAL_GATES)
    required.extend(key for key, _n, _f in type_gates)

    failed = [g for g in required
              if report["gate_results"][g]["state"] != GateState.PASS.value]

    grade_s = (ctx.get("evidence_grade").value
               if isinstance(ctx.get("evidence_grade"), EvidenceGrade)
               else str(ctx.get("evidence_grade", "")))
    ceiling = _GRADE_CEILING.get(grade_s, "INVALIDATED")
    report["grade_ceiling"] = ceiling

    if grade_s == EvidenceGrade.X.value:
        report["promotion_state"] = "INVALIDATED"
        report["overall"] = GateState.FAIL.value
        report["_reason"] = "grade X (invalidated) can never be promoted"
        return report

    if failed:
        report["promotion_state"] = "SOURCE_ONLY"
        report["overall"] = GateState.FAIL.value
        report["_failed_required"] = failed
        return report

    report["promotion_state"] = ceiling
    report["overall"] = GateState.PASS.value
    return report
