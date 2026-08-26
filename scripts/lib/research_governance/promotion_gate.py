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

FAIL-CLOSED semantics: a gate is PASS only when the evidence it requires is
positively present, correctly bound to the hypothesis, NUMERICALLY self-consistent,
and — for a Grade A/B empirical claim — produced by the governed engine and
carried by a verified ``GovernedResultReceipt`` inside one immutable
``PromotionEvidenceBundle``. A bare typed result (even with a valid self-digest)
is NOT provenance and is rejected.

Grade ceiling (never bypassable):
  A/B -> CIO_CONTEXT_ELIGIBLE (only if the profile fully passes)
  C   -> EXPLORATORY_SHADOW (never live CIO context)
  D   -> SOURCE_ONLY (no material CIO influence)
  X   -> INVALIDATED (never promoted; blocks)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Optional

from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass
from .receipts import GovernedResult, PromotionEvidenceBundle
from .results import (
    DSRResult,
    MethodApplicability,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    RobustnessItem,
    RobustnessResult,
    influence_allowed,
)

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

_CONFIRMATORY_MT_METHODS = {"bonferroni", "holm"}

_ROBUSTNESS_FIELDS = [
    "sample_n", "benchmark", "subperiods", "regimes", "costs",
    "outlier_dependence", "lookahead_control", "survivorship_control", "limitations",
]

_CRITICAL_NA_BLOCKED = {"sample_n", "benchmark", "lookahead_control", "limitations"}
_CONDITIONAL_NA = {"survivorship_control", "costs", "outlier_dependence", "subperiods", "regimes"}

# Canonical checklist evaluator (single source of truth shared with the governed
# robustness producer so a governed result cannot diverge from what the gate checks).
from . import robustness as _robustness_evaluator


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


def _grade(ctx: dict) -> Optional[str]:
    g = ctx.get("evidence_grade")
    if isinstance(g, EvidenceGrade):
        return g.value
    return str(g) if g else None


def _is_empirical(ctx: dict) -> bool:
    return _evidence_type(ctx) in _EMPIRICAL_TYPES


def _grade_ab(ctx: dict) -> bool:
    return _grade(ctx) in {"A", "B"}


def _bundle(ctx: dict) -> Optional[PromotionEvidenceBundle]:
    b = ctx.get("evidence_bundle")
    return b if isinstance(b, PromotionEvidenceBundle) else None


def _parse_date(v: Any):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        try:
            return datetime.fromisoformat(s).date()
        except ValueError:
            return date.fromisoformat(s)
    raise ValueError(f"not a date: {v!r}")


# -- governed result validation ----------------------------------------------

def _validate_governed(gr: Any, name: str) -> list[str]:
    """Validate a governed result receipt + its typed result ([] == OK)."""
    problems: list[str] = []
    if not isinstance(gr, GovernedResult):
        return [f"{name} must be a governed result (bare typed/dict rejected)"]
    if not gr.receipt.verify():
        problems.append(f"{name} receipt digest does not verify")
    problems.extend(f"{name} receipt: {p}" for p in gr.receipt.validate())
    if not gr.receipt.binds_result(gr.result):
        problems.append(f"{name} receipt does not bind its result digest")
    if not gr.result.verify():
        problems.append(f"{name} result digest does not verify")
    validate = getattr(gr.result, "validate", None)
    if callable(validate):
        problems.extend(f"{name} numeric/self-consistency: {p}" for p in validate())
    return problems


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
    bundle = _bundle(ctx)
    if bundle is not None:
        fr = bundle.frozen_family_receipt
        if not fr.verify():
            return GateState.FAIL, "frozen family receipt definition_digest does not verify"
        if fr.family_id != bundle.trial_family_id:
            return GateState.FAIL, "frozen family receipt family_id != bundle trial_family_id"
        if not fr.confirmatory:
            return GateState.FAIL, "frozen family is not confirmatory"
        return GateState.PASS, "hypothesis frozen (verified FrozenTrialFamilyReceipt)"
    if _grade_ab(ctx):
        return GateState.FAIL, "Grade A/B requires a governed bundle with a frozen family receipt"
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
    bundle = _bundle(ctx)
    if bundle is not None:
        if bundle.code_sha and bundle.dataset_hash:
            return GateState.PASS, "code and dataset hashes recorded (bundle identity)"
        return GateState.FAIL, "missing code_sha or dataset_hash in bundle identity"
    if _has(ctx, "code_sha") and _has(ctx, "dataset_hash"):
        return GateState.PASS, "code and dataset hashes recorded"
    return GateState.FAIL, "missing code_sha or dataset_hash"


def _gate_4_in_sample_reproduced(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    metric = ctx.get("in_sample_metric")
    if metric is None:
        return GateState.FAIL, "no in-sample reproduction metric"
    if isinstance(metric, (int, float)) and (metric != metric):  # NaN check
        return GateState.FAIL, "in-sample metric is NaN"
    if not isinstance(metric, (int, float)):
        return GateState.FAIL, "in-sample metric must be numeric"
    threshold = ctx.get("in_sample_threshold")
    if threshold is None:
        return GateState.FAIL, "in-sample threshold must be preregistered (no implicit pass)"
    if isinstance(threshold, (int, float)) and (threshold != threshold):
        return GateState.FAIL, "in-sample threshold is NaN"
    if not isinstance(threshold, (int, float)):
        return GateState.FAIL, "in-sample threshold must be numeric"
    if metric < threshold:
        return GateState.FAIL, f"in-sample metric {metric} below preregistered threshold {threshold}"
    return GateState.PASS, "in-sample reproduction meets preregistered threshold"


def _family_bound(ctx: dict, res: Any) -> bool:
    """Statistical result must be bound to the current frozen trial family."""
    fam_id = ctx.get("trial_family_id")
    fdh = ctx.get("family_definition_hash")
    hyp_id = ctx.get("hypothesis_id")
    if fam_id and getattr(res, "trial_family_id", None) and res.trial_family_id != fam_id:
        return False
    if fdh and getattr(res, "family_definition_hash", None) and res.family_definition_hash != fdh:
        return False
    if hyp_id and getattr(res, "tested_hypothesis_id", None) and res.tested_hypothesis_id != hyp_id:
        return False
    if hyp_id and getattr(res, "hypothesis_id", None) and res.hypothesis_id != hyp_id:
        return False
    return True


def _gate_5_oos_supported(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    bundle = _bundle(ctx)
    if bundle is not None:
        o = bundle.oos_receipt
        if not o.verify():
            return GateState.FAIL, "OOS receipt digest does not verify"
        if o.untouched is not True:
            return GateState.FAIL, "OOS receipt is not untouched (consumed/rerun)"
        if o.trial_family_id != bundle.trial_family_id:
            return GateState.FAIL, "OOS receipt bound to a different family"
        return GateState.PASS, "untouched OOS segment (registry-generated OOS receipt)"
    if _grade_ab(ctx):
        return GateState.FAIL, "Grade A/B requires a governed bundle with an OOS receipt"
    if ctx.get("oos_supported") is not True:
        return GateState.FAIL, "oos_supported must be True"
    if ctx.get("oos_untouched") is not True:
        return GateState.FAIL, "oos_untouched must be True (missing or consumed => FAIL)"
    return GateState.PASS, "untouched OOS segment supports hypothesis"


def _gate_6_multiple_testing_applied(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    bundle = _bundle(ctx)
    if bundle is not None:
        problems = _validate_governed(bundle.multiple_testing, "multiple_testing")
        if problems:
            return GateState.FAIL, "; ".join(problems)
        mt = bundle.multiple_testing.result
    else:
        if _grade_ab(ctx):
            return GateState.FAIL, ("Grade A/B multiple_testing requires a governed receipt "
                                    "(bare typed/dict rejected)")
        mt = ctx.get("multiple_testing")
        if not isinstance(mt, MultipleTestingResult):
            return GateState.FAIL, "multiple_testing must be a typed MultipleTestingResult (dict rejected)"
        if not mt.verify():
            return GateState.FAIL, "multiple_testing result digest does not verify"
        problems = mt.validate()
        if problems:
            return GateState.FAIL, f"multiple_testing numeric/self-consistency: {problems}"
    if mt.status != "OK":
        return GateState.FAIL, f"multiple_testing status != OK: {mt.status}"
    if mt.rejected is not True:
        return GateState.FAIL, "hypothesis did not survive multiple-testing correction"
    if mt.complete_family is not True:
        return GateState.FAIL, "multiple_testing family incomplete"
    if mt.approx:
        return GateState.FAIL, "multiple_testing approximation not governed for confirmatory use"
    if not _family_bound(ctx, mt):
        return GateState.FAIL, "multiple_testing bound to a different family/hypothesis"
    if _grade_ab(ctx) and mt.method.lower() not in _CONFIRMATORY_MT_METHODS:
        return GateState.FAIL, f"confirmatory Grade A/B requires Bonferroni/Holm, got {mt.method}"
    return GateState.PASS, "survives multiple-testing correction on the correct frozen family"


def _gate_7_reality_check_passed(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    bundle = _bundle(ctx)
    if bundle is not None:
        problems = _validate_governed(bundle.reality_check, "reality_check")
        if problems:
            return GateState.FAIL, "; ".join(problems)
        rc = bundle.reality_check.result
    else:
        if _grade_ab(ctx):
            return GateState.FAIL, ("Grade A/B reality_check requires a governed receipt "
                                    "(bare typed/dict rejected)")
        rc = ctx.get("reality_check")
        if not isinstance(rc, RealityCheckResult):
            return GateState.FAIL, "reality_check must be a typed RealityCheckResult (dict rejected)"
        if not rc.verify():
            return GateState.FAIL, "reality_check result digest does not verify"
        problems = rc.validate()
        if problems:
            return GateState.FAIL, f"reality_check numeric/self-consistency: {problems}"
    if rc.status != "OK":
        return GateState.FAIL, f"reality_check status != OK: {rc.status}"
    if not _family_bound(ctx, rc):
        return GateState.FAIL, "reality_check bound to a different family/hypothesis"
    if not rc.trial_family_id:
        return GateState.FAIL, "reality_check missing trial_family_id"
    p = rc.bootstrap_pvalue
    alpha = ctx.get("reality_check_alpha", rc.alpha)
    if p is None or p > alpha:
        return GateState.FAIL, f"reality check p={p} > alpha={alpha}"
    return GateState.PASS, f"reality check p={p:.4f} <= alpha={alpha} on frozen family"


def _robustness_problems(rob: RobustnessResult) -> list[str]:
    return _robustness_evaluator.evaluate_robustness(rob.items)


def _gate_8_robust(ctx: dict) -> tuple[GateState, str]:
    na = _empirical_only(ctx)
    if na:
        return na
    bundle = _bundle(ctx)
    if bundle is not None:
        problems = _validate_governed(bundle.robustness, "robustness")
        if problems:
            return GateState.FAIL, "; ".join(problems)
        rob = bundle.robustness.result
    else:
        if _grade_ab(ctx):
            return GateState.FAIL, ("Grade A/B robustness requires a governed receipt "
                                    "(bare typed/dict rejected)")
        rob = ctx.get("robustness")
        if not isinstance(rob, RobustnessResult):
            return GateState.FAIL, "robustness must be a typed RobustnessResult (dict rejected)"
        if not rob.verify():
            return GateState.FAIL, "robustness result digest does not verify"
    fails = _robustness_problems(rob)
    if fails:
        return GateState.FAIL, f"robustness unsatisfied: {fails}"
    return GateState.PASS, "robustness checklist satisfied (critical fields PASS; conditional NA reasoned)"


def _gate_9_graded_and_influence(ctx: dict) -> tuple[GateState, str]:
    grade = _grade(ctx)
    if grade is None:
        return GateState.FAIL, "no evidence grade"
    if grade not in _GRADE_CEILING:
        return GateState.FAIL, f"invalid evidence grade {grade}"
    influence = ctx.get("influence_class")
    if isinstance(influence, InfluenceClass):
        influence = influence.value
    if influence is None:
        return GateState.FAIL, "no influence class assigned"
    et = _evidence_type(ctx)
    if et is None:
        return GateState.FAIL, "no evidence type"
    if not influence_allowed(et.value, influence):
        return GateState.FAIL, f"influence class {influence} incompatible with evidence type {et.value}"
    if ctx.get("claims_trade_authority") is True:
        return GateState.FAIL, "research may not claim broker/order/stop authority"
    return GateState.PASS, f"grade {grade}, influence {influence}"


def _gate_10_decision_use_audit(ctx: dict) -> tuple[GateState, str]:
    if ctx.get("live_research_use") is True:
        rec = ctx.get("decision_use_audit")
        try:
            from .decision_use_audit import is_authentic_audit
        except Exception:
            return GateState.FAIL, "decision-use audit module missing"
        if not is_authentic_audit(rec):
            return GateState.FAIL, "live research use without authentic decision-use audit"
        return GateState.PASS, "live decision-use audited"
    if ctx.get("decision_use_audit_contract") is True:
        return GateState.PASS, "decision-use audit contract present"
    return GateState.NOT_APPLICABLE, "no live research use in this context"


def _gate_11_live_degradation(ctx: dict) -> tuple[GateState, str]:
    if ctx.get("live_research_use") is True:
        deg = ctx.get("degradation_decision")
        if not isinstance(deg, dict) or deg.get("action") not in {"keep", "degrade", "retire"}:
            return GateState.FAIL, "live research use without degradation decision"
        return GateState.PASS, f"degradation {deg.get('action')}"
    if ctx.get("live_degradation_contract") is True:
        return GateState.PASS, "live degradation/retirement monitoring contract present"
    return GateState.NOT_APPLICABLE, "no live research use in this context"


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


def _method_applicability_ok(ctx: dict) -> tuple[bool, str]:
    """P0-7/P0-2: for Grade A/B empirical, govern DSR/PBO/RC/purged-CV applicability.

    Every REQUIRED method needs a VERIFIED governed receipt (never a bare typed
    result); NOT_APPLICABLE needs an approved reason; UNAVAILABLE does not count.
    """
    bundle = _bundle(ctx)
    app = bundle.method_applicability if bundle is not None else ctx.get("method_applicability")
    if not isinstance(app, MethodApplicability):
        return False, "Grade A/B empirical requires a MethodApplicability record"

    governed_map = {
        "dsr": bundle.dsr if bundle is not None else None,
        "pbo": bundle.pbo if bundle is not None else None,
        "reality_check": bundle.reality_check if bundle is not None else None,
    }
    for label, req in (("dsr", app.dsr), ("pbo", app.pbo),
                       ("reality_check", app.reality_check), ("purged_cv", app.purged_cv)):
        if req.state == "REQUIRED":
            if label == "purged_cv":
                if ctx.get("purged_cv_applied") is not True:
                    return False, "PURGED_CV REQUIRED but purged_cv_applied is not True"
                continue
            gr = governed_map[label]
            problems = _validate_governed(gr, label)
            if problems:
                return False, "; ".join(problems)
            res = gr.result
            if res.status != "OK":
                return False, f"{label} REQUIRED but result is not OK"
            if label == "pbo" and res.approx:
                return False, "PBO REQUIRED but result is approximate (not governed)"
        elif req.state == "NOT_APPLICABLE":
            if not req.reason.strip():
                return False, f"{label} NOT_APPLICABLE requires an approved reason"
        elif req.state == "UNAVAILABLE":
            return False, f"{label} UNAVAILABLE does not count as controlled evidence"
        else:
            return False, f"{label} has invalid applicability state {req.state!r}"
    return True, "method applicability satisfied"


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
            ("freshness", "freshness",
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
    """P0-9: COMPUTE freshness from dates, never trust a caller boolean."""
    verified_at = ctx.get("verified_at")
    current_as_of = ctx.get("current_as_of")
    effective_date = ctx.get("effective_date")
    next_reverify_at = ctx.get("next_reverify_at")
    if not verified_at or not current_as_of:
        return GateState.FAIL, "policy missing verified_at or current_as_of"
    if not effective_date:
        return GateState.FAIL, "policy missing effective_date"
    try:
        cur = _parse_date(current_as_of)
        verified = _parse_date(verified_at)
        effective = _parse_date(effective_date)
    except ValueError as exc:
        return GateState.FAIL, f"policy dates unparseable: {exc}"
    if effective > cur and ctx.get("future_effective") is not True:
        return GateState.FAIL, f"effective_date {effective} after current_as_of {cur} (future-effective not declared)"
    if next_reverify_at:
        try:
            next_reverify = _parse_date(next_reverify_at)
        except ValueError as exc:
            return GateState.FAIL, f"next_reverify_at unparseable: {exc}"
        if cur > next_reverify:
            return GateState.FAIL, f"reverification overdue: current_as_of {cur} > next_reverify_at {next_reverify}"
    if verified > cur:
        return GateState.FAIL, f"verified_at {verified} after current_as_of {cur}"
    return GateState.PASS, "policy fresh (computed: verified/effective/current/reverify coherent)"


def _valuation_calibration(ctx: dict) -> tuple[GateState, str]:
    cal = ctx.get("calibration")
    if not isinstance(cal, dict) or not cal:
        return GateState.FAIL, "valuation calibration must be structured evidence"
    for key in ("calibration_dataset", "calibration_metric", "validation_split"):
        if not cal.get(key):
            return GateState.FAIL, f"valuation calibration missing {key}"
    return GateState.PASS, "valuation calibration structured (dataset + metric + split)"


def run_promotion_gate(ctx: dict) -> dict:
    """Run RG-0..RG-11 plus type-specific gates; apply the grade ceiling.

    For a Grade A/B empirical claim, statistical evidence must be a verified
    governed ``GovernedResult`` inside one immutable ``PromotionEvidenceBundle``
    (``ctx["evidence_bundle"]``). A bare typed result — even with a valid
    self-digest — is rejected.
    """
    report: dict[str, Any] = {"gate_results": {}, "overall": GateState.PASS.value,
                              "promotion_state": None, "grade_ceiling": None}

    et = _evidence_type(ctx)
    if et is None:
        report["overall"] = GateState.FAIL.value
        report["promotion_state"] = "INVALIDATED"
        report["_reason"] = "evidence_type missing/invalid"
        return report

    bundle = _bundle(ctx)

    for gid, name, fn in _GATES:
        state, reason = fn(ctx)
        report["gate_results"][gid] = {"name": name, "state": state.value, "reason": reason}

    type_gates = _type_specific_gates(ctx)
    for key, name, fn in type_gates:
        state, reason = fn(ctx)
        report["gate_results"][key] = {"name": name, "state": state.value, "reason": reason}

    grade_s = _grade(ctx) or ""
    ceiling = _GRADE_CEILING.get(grade_s, "INVALIDATED")
    report["grade_ceiling"] = ceiling

    if grade_s == EvidenceGrade.X.value:
        report["promotion_state"] = "INVALIDATED"
        report["overall"] = GateState.FAIL.value
        report["_reason"] = "grade X (invalidated) can never be promoted"
        return report

    required = list(_REQUIRED_SHARED)
    if _is_empirical(ctx):
        required.extend(_EMPIRICAL_GATES)
    required.extend(key for key, _n, _f in type_gates)

    failed = [g for g in required
              if report["gate_results"][g]["state"] != GateState.PASS.value]

    # Grade A/B empirical: require a verified governed bundle.
    if _is_empirical(ctx) and _grade_ab(ctx):
        if bundle is None:
            failed.append("evidence_bundle")
            report["evidence_bundle"] = ("Grade A/B empirical requires a governed "
                                         "PromotionEvidenceBundle")
        else:
            bundle_problems = bundle.validate_bundle()
            if bundle_problems:
                failed.append("evidence_bundle")
                report["evidence_bundle"] = "; ".join(bundle_problems)
        ok, reason = _method_applicability_ok(ctx)
        report["method_applicability"] = reason
        if not ok:
            failed.append("method_applicability")

    if failed:
        report["promotion_state"] = "SOURCE_ONLY"
        report["overall"] = GateState.FAIL.value
        report["_failed_required"] = failed
        return report

    report["promotion_state"] = ceiling
    report["overall"] = GateState.PASS.value
    return report
