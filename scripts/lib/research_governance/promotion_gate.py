"""Research governance — promotion gate RG-0..RG-11 (PR-R1).

The promotion ladder for a single hypothesis/fact. It is deliberately
asymmetric, reflecting the authority model the whole subsystem exists to
enforce:

  * methodology evidence MAY BLOCK a promotion,
  * deterministic instrument mechanics MAY establish CONDITIONAL mechanical facts,
  * risk evidence MAY VETO or size down,
  * valuation research MAY alter a valuation RANGE,
  * portfolio-construction research MAY change candidate SIZING,
  * seasonality MAY modify STAGING/TIMING,

  ... and NONE of them independently creates trade authority.

The gate never grants broker/order/stop authority. Its highest output is
READ_ONLY_ADVISORY promotion into live cognition (still deferred to R4).

Pure, deterministic. Operates over a context dict; returns a full report.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .enums import GateState, InfluenceClass

GATE_IDS: tuple[str, ...] = tuple(f"RG-{i}" for i in range(12))


def _has(ctx: dict, key: str) -> bool:
    return bool(ctx.get(key))


def _gate_0_source_registered(ctx: dict) -> tuple[GateState, str]:
    if _has(ctx, "source_id"):
        return GateState.PASS, "source registered"
    return GateState.FAIL, "no source_id"

def _gate_1_source_claim_complete(ctx: dict) -> tuple[GateState, str]:
    if _has(ctx, "claim") and _has(ctx, "page_or_section") and _has(ctx, "scope"):
        return GateState.PASS, "claim has text, citation, and scope"
    return GateState.FAIL, "claim incomplete (needs text + page/section + scope)"

def _gate_2_hypothesis_frozen(ctx: dict) -> tuple[GateState, str]:
    if _has(ctx, "protocol_hash") and _has(ctx, "trial_family_id"):
        frozen = ctx.get("family_frozen")
        if frozen:
            return GateState.PASS, "hypothesis frozen in trial registry"
        return GateState.FAIL, "trial family not frozen"
    return GateState.FAIL, "no protocol_hash / trial_family_id"

def _gate_3_reproducible(ctx: dict) -> tuple[GateState, str]:
    if _has(ctx, "code_sha") and _has(ctx, "dataset_hash"):
        return GateState.PASS, "code and dataset hashes recorded"
    return GateState.FAIL, "missing code_sha or dataset_hash"

def _gate_4_in_sample_reproduced(ctx: dict) -> tuple[GateState, str]:
    metric = ctx.get("in_sample_metric")
    threshold = ctx.get("in_sample_threshold")
    if metric is None:
        return GateState.FAIL, "no in-sample reproduction metric"
    if threshold is not None and metric < threshold:
        return GateState.FAIL, f"in-sample metric {metric} below threshold {threshold}"
    return GateState.PASS, "in-sample reproduction meets preregistered threshold"

def _gate_5_oos_supported(ctx: dict) -> tuple[GateState, str]:
    oos = ctx.get("oos_supported")
    oos_untouched = ctx.get("oos_untouched")
    if oos is None:
        return GateState.FAIL, "no OOS result"
    if oos is not True:
        return GateState.FAIL, "OOS did not support the hypothesis"
    if oos_untouched is False:
        return GateState.FAIL, "OOS segment was consumed/tuned — not valid untouched evidence"
    return GateState.PASS, "untouched OOS segment supports hypothesis"

def _gate_6_multiple_testing_applied(ctx: dict) -> tuple[GateState, str]:
    mt = ctx.get("multiple_testing")
    if mt is None:
        return GateState.FAIL, "no multiple-testing result"
    if mt.get("rejected_any") is True:
        return GateState.PASS, "survives multiple-testing correction"
    return GateState.FAIL, "does not survive multiple-testing correction"

def _gate_7_reality_check_passed(ctx: dict) -> tuple[GateState, str]:
    rc = ctx.get("reality_check")
    if rc is None:
        return GateState.FAIL, "no reality-check / data-snooping result"
    alpha = ctx.get("reality_check_alpha", 0.05)
    p = rc.get("bootstrap_pvalue")
    if p is None:
        return GateState.FAIL, "reality check produced no p-value"
    if p <= alpha:
        return GateState.PASS, f"reality check p={p:.4f} <= alpha={alpha}"
    return GateState.FAIL, f"reality check p={p:.4f} > alpha={alpha}"

def _gate_8_robust(ctx: dict) -> tuple[GateState, str]:
    if not _has(ctx, "robustness"):
        return GateState.FAIL, "no robustness/subperiod/regime evidence"
    rob = ctx["robustness"]
    if not isinstance(rob, dict):
        return GateState.FAIL, "robustness must be a dict"
    failures = [k for k, v in rob.items() if v is False]
    if failures:
        return GateState.FAIL, f"robustness failed: {failures}"
    return GateState.PASS, "robust across subperiods, regimes, and costs"

def _gate_9_graded(ctx: dict) -> tuple[GateState, str]:
    grade = ctx.get("evidence_grade")
    if grade is None:
        return GateState.FAIL, "no evidence grade"
    if str(grade) not in {"A", "B", "C", "D", "X"}:
        return GateState.FAIL, f"invalid evidence grade {grade}"
    return GateState.PASS, f"evidence grade {grade}"

def _gate_10_influence_assigned(ctx: dict) -> tuple[GateState, str]:
    influence = ctx.get("influence_class")
    if influence is None:
        return GateState.FAIL, "no influence class assigned"
    valid = {c.value for c in InfluenceClass}
    if str(influence) not in valid:
        return GateState.FAIL, f"invalid influence class {influence}"
    if ctx.get("claims_trade_authority") is True:
        return GateState.FAIL, "research may not claim broker/order/stop authority"
    return GateState.PASS, "influence class assigned; authority boundary respected"

def _gate_11_promotion_ready(ctx: dict) -> tuple[GateState, str]:
    return GateState.PASS, "eligible for READ_ONLY_ADVISORY promotion (deferred to R4)"


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
    ("RG-9", "graded", _gate_9_graded),
    ("RG-10", "influence_assigned", _gate_10_influence_assigned),
    ("RG-11", "promotion_ready", _gate_11_promotion_ready),
]


# RG-11 is the terminal "promotion_ready" confirmation: it is DERIVED from the
# prerequisite gates rather than evaluated independently, so it can never pass
# when an earlier gate failed.
_PREREQUISITE_GATES = [g for g in GATE_IDS if g != "RG-11"]


def run_promotion_gate(ctx: dict, *, halt_on_first_fail: bool = False) -> dict:
    """Run RG-0..RG-11 and return a full report.

    A fact may only be promoted if every gate passes. If halt_on_first_fail is
    set, later gates are marked NOT_IN_SCOPE rather than evaluated (they would be
    meaningless without their prerequisites).
    """
    report: dict[str, Any] = {"gate_results": {}, "passed": 0, "failed": 0,
                              "blocked": 0, "overall": GateState.PASS.value,
                              "promotion_state": None}
    blocked = False
    for gid, name, fn in _GATES:
        if gid == "RG-11":
            continue  # handled after the loop
        if blocked and halt_on_first_fail:
            report["gate_results"][gid] = {
                "name": name, "state": GateState.NOT_IN_SCOPE.value,
                "reason": "halted at earlier failure",
            }
            continue
        state, reason = fn(ctx)
        report["gate_results"][gid] = {"name": name, "state": state.value,
                                       "reason": reason}
        if state == GateState.PASS:
            report["passed"] += 1
        elif state == GateState.FAIL:
            report["failed"] += 1
            blocked = True
        else:
            report["blocked"] += 1

    # RG-11 promotion_ready: passes only when every prerequisite gate passed.
    prereq_ok = all(
        report["gate_results"][g]["state"] == GateState.PASS.value
        for g in _PREREQUISITE_GATES
    )
    r11 = (GateState.PASS, "eligible for READ_ONLY_ADVISORY promotion") if prereq_ok \
        else (GateState.FAIL, "prerequisite gates not all passed")
    report["gate_results"]["RG-11"] = {"name": "promotion_ready",
                                       "state": r11[0].value, "reason": r11[1]}
    if r11[0] == GateState.PASS:
        report["passed"] += 1
    else:
        report["failed"] += 1

    if report["failed"] > 0:
        report["overall"] = GateState.FAIL.value
    elif report["blocked"] > 0:
        report["overall"] = GateState.BLOCKED.value

    report["promotion_state"] = _promotion_state_for(report)
    return report


# Milestone ladder by the highest CONTIGUOUS gate passed (RG-0 -> RG-11).
_STATE_BY_LAST_PASSED: dict[str, str] = {
    "RG-0": "SOURCE_ONLY",
    "RG-1": "SOURCE_ONLY",
    "RG-2": "EXPLORATORY_ONLY",
    "RG-3": "ELIGIBLE_FOR_REPRODUCTION",
    "RG-4": "REPRODUCED_IN_SAMPLE",
    "RG-5": "OOS_SUPPORTED",
    "RG-6": "OOS_SUPPORTED",
    "RG-7": "OOS_SUPPORTED",
    "RG-8": "ELIGIBLE_FOR_SHADOW_CONTEXT",
    "RG-9": "ELIGIBLE_FOR_SHADOW_CONTEXT",
    "RG-10": "ELIGIBLE_FOR_CIO_CONTEXT",
    "RG-11": "ELIGIBLE_FOR_CIO_CONTEXT",
}


def _promotion_state_for(report: dict) -> str:
    last_passed: Optional[str] = None
    for gid in GATE_IDS:
        st = report["gate_results"].get(gid, {}).get("state")
        if st == GateState.PASS.value:
            last_passed = gid
        else:
            break
    if last_passed is None:
        return "SOURCE_ONLY"
    return _STATE_BY_LAST_PASSED[last_passed]
