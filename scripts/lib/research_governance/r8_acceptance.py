"""R8A-1 empirical factor / strategy family acceptance."""
from __future__ import annotations

from .empirical import (
    AUTHORITY,
    FAMILY_ID,
    HYPOTHESIS_ID,
    MAX_INFLUENCE_PCT,
    N_VARIANTS,
    PROTOCOL_HASH,
    as_research_evidence,
    attempt_winner_only,
    run_family,
    variant_returns,
)
from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass, ResearchStatus
from .trial_registry import TrialRegistry


def _pass(d: str) -> tuple[str, str]:
    return GateState.PASS.value, d


def _fail(d: str) -> tuple[str, str]:
    return GateState.FAIL.value, d


def check_empirical_family() -> tuple[str, str]:
    try:
        pack = run_family()
    except Exception as exc:  # noqa: BLE001 — fail-closed on runner errors
        return _fail(f"run_family raised: {exc}")

    if pack.get("authority") != AUTHORITY:
        return _fail("authority drifted")
    if pack.get("standalone_sell") or pack.get("creates_trim"):
        return _fail("empirical family must not sell or TRIM")
    if pack.get("winner_only") is not False:
        return _fail("winner_only must be False")
    if pack.get("whole_family") is not True:
        return _fail("whole_family must be True")
    if pack.get("selected_winner") is not None:
        return _fail("selected_winner must remain None")
    if pack.get("family_complete") is not True:
        return _fail("family_complete must be True")
    if pack.get("n_variants") != N_VARIANTS:
        return _fail(f"n_variants {pack.get('n_variants')} != {N_VARIANTS}")
    if pack.get("oos_claimed"):
        return _fail("R8 fixture family must not claim OOS")
    if pack.get("research_status") == ResearchStatus.OOS_SUPPORTED.value:
        return _fail("R8 must not claim OOS_SUPPORTED")
    if pack.get("influence_class") != InfluenceClass.CONTEXT_MODIFIER.value:
        return _fail("influence_class must be CONTEXT_MODIFIER")
    if float(pack.get("max_influence_pct") or 0) > MAX_INFLUENCE_PCT:
        return _fail("influence cap exceeded")

    trials = pack.get("trials") or []
    if len(trials) != N_VARIANTS:
        return _fail(f"expected {N_VARIANTS} recorded trials, got {len(trials)}")
    months = {int(t["month"]) for t in trials}
    if months != set(range(1, 13)):
        return _fail(f"planned months incomplete: {sorted(months)}")
    if any(t.get("mean") is None or t.get("n") in (None, 0) for t in trials):
        return _fail("a recorded trial is empty")
    losers = [t for t in trials if float(t["mean"]) <= 0.0]
    if not losers:
        return _fail("losers were not recorded (negative-mean variants missing)")

    lengths = [len(variant_returns(m)) for m in range(1, 13)]
    if len(set(lengths)) != 1 or lengths[0] < 2:
        return _fail(f"variant series not equal-length complete years: {lengths}")

    mt = pack.get("multiple_testing") or {}
    adjusted = mt.get("adjusted") or []
    raw = mt.get("raw_pvalues") or []
    if len(adjusted) != N_VARIANTS or len(raw) != N_VARIANTS:
        return _fail("multiple_testing did not cover the 12-variant family")
    if mt.get("method") not in {"holm", "bonferroni", "bh_fdr"}:
        return _fail(f"unknown multiple-testing method {mt.get('method')}")

    ch = pack.get("family_challenge") or {}
    if ch.get("status") not in {"OK", "UNAVAILABLE"}:
        return _fail(f"family challenge bad status {ch}")
    if ch.get("status") == "OK" and (ch.get("n_rules") or 0) < N_VARIANTS:
        return _fail("family challenge must evaluate all 12 rules")
    if ch.get("winner_only"):
        return _fail("family challenge must not be winner-only")
    if ch.get("whole_family") is not True:
        return _fail("family challenge must be whole-family")

    try:
        ev = as_research_evidence(pack)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"as_research_evidence raised: {exc}")
    if not ev:
        return _fail("as_research_evidence returned nothing")
    for item in ev:
        if item.evidence_type not in {
            EvidenceType.EMPIRICAL_STRATEGY,
            EvidenceType.EMPIRICAL_FACTOR,
        }:
            return _fail(f"unexpected evidence_type {item.evidence_type}")
        if item.evidence_grade not in {EvidenceGrade.C, EvidenceGrade.D}:
            return _fail(f"fixture grade ceiling violated: {item.evidence_grade}")
        if item.influence_class != InfluenceClass.CONTEXT_MODIFIER:
            return _fail("evidence influence escaped CONTEXT_MODIFIER")
        if item.research_status == ResearchStatus.OOS_SUPPORTED:
            return _fail("evidence claimed OOS_SUPPORTED")
        if item.role_in_decision not in (None, "risk_modifier_or_context"):
            return _fail("role escaped risk_modifier_or_context")
    if ev[0].evidence_type != EvidenceType.EMPIRICAL_STRATEGY:
        return _fail("family evidence must be EMPIRICAL_STRATEGY")

    incomplete = dict(pack, family_complete=False, trials=trials[:3], selected_winner="month_09")
    try:
        attempt_winner_only(incomplete)
        return _fail("attempt_winner_only must fail on an incomplete family")
    except ValueError:
        pass

    try:
        attempt_winner_only(pack)
        return _fail("attempt_winner_only must not anoint a winner")
    except ValueError:
        pass
    if pack.get("selected_winner") is not None:
        return _fail("pack selected_winner mutated")

    reg = TrialRegistry()
    try:
        reg.freeze_family(
            "r8-confirm-no-hash",
            HYPOTHESIS_ID,
            protocol_hash=PROTOCOL_HASH,
            planned_trials=[("month_01", "cfg")],
            confirmatory=True,
        )
        return _fail("confirmatory freeze without family_definition_hash must fail")
    except ValueError:
        pass

    reg = TrialRegistry()
    reg.freeze_family(
        FAMILY_ID,
        HYPOTHESIS_ID,
        protocol_hash=PROTOCOL_HASH,
        planned_trials=[("month_01", "cfg1"), ("month_02", "cfg2")],
    )
    try:
        reg.record_trial(FAMILY_ID, "unplanned", config_hash="x", result_payload={"month": 99})
        return _fail("unplanned trial must be rejected")
    except ValueError:
        pass

    return _pass(
        "R8 empirical family: 12 variants incl. losers, no winner, no TRIM/sell, "
        "no OOS claim, CONTEXT_MODIFIER"
    )


CHECKS = {"R8A-1": check_empirical_family}
