"""Gate-D Advisory Contract Tests — frozen advisory schema validation.

Provider-call-free. Uses mock specialist advisory JSON fixtures to prove:
  - Schema validation (reject fact-dump-only, missing fields)
  - Disagreement resolution (Alex must reconcile, not blind vote)
  - Prohibited authority enforcement (specialists never create final CIO actions)
  - Evidence-quality-to-confidence tracking (PARTIAL evidence → lower confidence)

Gate-D component. Zero provider calls.
"""
from __future__ import annotations

import json
import pytest
from dataclasses import asdict

from scripts.lib.cio_advisory_schema import (
    SpecialistAdvisoryPosition,
    SpecialistAdvisory,
    AlexCIOAdvisory,
    EvidenceSource,
    RiskFlag,
    ConditionToChangeView,
    validate_specialist_advisory,
    validate_alex_advisory,
    validate_cioe_executive_advisory,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

PARENT_RUN_ID = "run-gate-d-test-001"


def _make_evidence_sources(domains: list[str], quality: str = "AVAILABLE") -> list[EvidenceSource]:
    return [
        EvidenceSource(
            source_id=f"ds-{d}",
            domain=d,
            quality_state=quality,
            as_of="2026-08-10T20:00:00Z",
            source_ref=f"canonical://{d}",
        )
        for d in domains
    ]


def _maria_support_advisory() -> SpecialistAdvisory:
    return SpecialistAdvisory(
        specialist_id="maria",
        parent_run_id=PARENT_RUN_ID,
        run_purpose="PORTFOLIO_ALLOCATION_REVIEW",
        position=SpecialistAdvisoryPosition.SUPPORT,
        recommendation="Increase equity allocation to 75%, overweight Technology and Healthcare sectors. The fundamental thesis for current holdings is attractive — strong earnings growth, favorable catalysts, and positive analyst revisions.",
        rationale="Current portfolio shows 72% equity allocation vs 75% target. Technology sector fundamentals support overweight positioning. Positive earnings momentum and analyst upgrades across key holdings suggest thesis is intact and strengthening.",
        evidence_sources=_make_evidence_sources(["portfolio", "holdings_detail", "analyst_actions", "catalysts"]),
        evidence_summary="Portfolio at 72% equity (3% under target). Technology sector fundamentals strong. 4 positive analyst actions, 2 upcoming catalysts.",
        confidence=0.85,
        confidence_basis="FULL_EVIDENCE",
        material_risks=[
            RiskFlag(risk_id="r1", description="Technology sector concentration above 35%", severity="MEDIUM", evidence_refs=["ds-holdings_detail"]),
        ],
        alternatives_considered=[
            "Maintain current allocation",
            "Overweight Financials instead of Technology",
        ],
        conditions_to_change_view=[
            ConditionToChangeView(
                condition="Technology sector earnings guidance turns negative",
                new_position_if_met="NEUTRAL",
                rationale="Core thesis depends on tech earnings momentum",
            ),
            ConditionToChangeView(
                condition="Portfolio-wide stop-loss triggered on more than 2 positions",
                new_position_if_met="OPPOSE",
                rationale="Risk envelope breached — must prioritize capital preservation",
            ),
        ],
        evidence_gaps=["defense_stops_protection is DATA_UNAVAILABLE"],
        deficiencies_acknowledged=["Stop-loss coverage cannot be verified without defense_stops_protection"],
    )


def _steph_oppose_advisory() -> SpecialistAdvisory:
    return SpecialistAdvisory(
        specialist_id="steph",
        parent_run_id=PARENT_RUN_ID,
        run_purpose="PORTFOLIO_ALLOCATION_REVIEW",
        position=SpecialistAdvisoryPosition.OPPOSE,
        recommendation="Do NOT increase equity allocation. Technology sector already at 38% — concentration risk is too high. Rebalance toward target model portfolio before adding new positions.",
        rationale="Current Technology sector weight is 38% vs model target of 28%. Adding more Tech exposure violates IPS single-sector concentration limit of 35%. Total equity at 72% is within drift band — no urgency to add.",
        evidence_sources=_make_evidence_sources(["portfolio", "sectors", "investment_policy", "model_portfolio"]),
        evidence_summary="Tech sector at 38% (10% above target). IPS limits single sector to 35%. Equity drift at 3% — within threshold. Model portfolio target: 28% Tech.",
        confidence=0.90,
        confidence_basis="FULL_EVIDENCE",
        material_risks=[
            RiskFlag(risk_id="r2", description="Technology sector concentration violates IPS limit", severity="HIGH", evidence_refs=["ds-sectors", "ds-investment_policy"]),
            RiskFlag(risk_id="r3", description="Model portfolio drift in multiple sectors", severity="MEDIUM", evidence_refs=["ds-model_portfolio"]),
        ],
        alternatives_considered=[
            "Partial rebalance — trim Tech 5%, add to underrepresented sectors",
            "No action — wait for natural drift correction",
        ],
        conditions_to_change_view=[
            ConditionToChangeView(
                condition="Technology sector weight drops below 30% through natural market movement",
                new_position_if_met="SUPPORT",
                rationale="Concentration risk resolved — room to add on favorable thesis",
            ),
        ],
        evidence_gaps=["Account constraints not verified — cannot assess tax impact of rebalance"],
        deficiencies_acknowledged=["Tax impact of rebalance unknown without account_constraints"],
    )


def _guardian_oppose_advisory() -> SpecialistAdvisory:
    return SpecialistAdvisory(
        specialist_id="guardian",
        parent_run_id=PARENT_RUN_ID,
        run_purpose="PORTFOLIO_ALLOCATION_REVIEW",
        position=SpecialistAdvisoryPosition.OPPOSE,
        recommendation="Risk envelope is unacceptable for increasing equity exposure. Portfolio heat is at 82% of risk budget, and stop coverage is unverifiable. Adding positions without verified stop coverage violates risk governance.",
        rationale="Portfolio heat at 82% of total risk budget leaves only 18% headroom. Increasing equity allocation consumes remaining headroom without verified stop-loss protection. defense_stops_protection is DATA_UNAVAILABLE — cannot verify that new positions have adequate stops.",
        evidence_sources=_make_evidence_sources(["portfolio", "risk"]),
        evidence_summary="Portfolio heat at 82% of risk budget. Stop coverage unverified (defense_stops_protection DATA_UNAVAILABLE). Risk envelope too tight for new positions.",
        confidence=0.80,
        confidence_basis="PARTIAL_EVIDENCE",
        material_risks=[
            RiskFlag(risk_id="r4", description="Portfolio heat at 82% — insufficient headroom for new positions", severity="HIGH", evidence_refs=["ds-risk"]),
            RiskFlag(risk_id="r5", description="Stop-loss coverage unverifiable without defense_stops_protection", severity="HIGH", evidence_refs=[]),
        ],
        alternatives_considered=[
            "Allow only if existing position's stops are trimmed to free headroom",
            "Require operator to manually verify stop coverage before approving",
        ],
        conditions_to_change_view=[
            ConditionToChangeView(
                condition="Portfolio heat drops below 60% AND defense_stops_protection becomes AVAILABLE",
                new_position_if_met="SUPPORT",
                rationale="Sufficient risk headroom with verified stop coverage — risk governance satisfied",
            ),
        ],
        evidence_gaps=["defense_stops_protection is DATA_UNAVAILABLE — cannot verify stop coverage"],
        deficiencies_acknowledged=["Risk assessment incomplete without verified stop-loss data"],
    )


def _ledger_defer_advisory() -> SpecialistAdvisory:
    return SpecialistAdvisory(
        specialist_id="ledger",
        parent_run_id=PARENT_RUN_ID,
        run_purpose="PORTFOLIO_ALLOCATION_REVIEW",
        position=SpecialistAdvisoryPosition.DEFER,
        recommendation="Cannot assess tax implications of proposed allocation change. Tax lot data and account constraints are unavailable. Defer recommendation until tax evidence is complete.",
        rationale="tax_lots.json is unavailable — cannot determine holding periods, wash-sale proximity, or cost basis impact. account_constraints is UNSUPPORTED — cannot verify account-type eligibility for proposed positions. Tax review requires both domains.",
        evidence_sources=_make_evidence_sources(["cost_basis", "portfolio"]),
        evidence_summary="Tax lots DATA_UNAVAILABLE. Account constraints DATA_UNAVAILABLE. Cost basis available but incomplete without lot-level detail.",
        confidence=0.30,
        confidence_basis="INSUFFICIENT_EVIDENCE",
        material_risks=[
            RiskFlag(risk_id="r6", description="Potential wash-sale violation — cannot verify without lot data", severity="HIGH", evidence_refs=[]),
            RiskFlag(risk_id="r7", description="Unknown tax impact — could change recommendation from SUPPORT to OPPOSE", severity="MEDIUM", evidence_refs=[]),
        ],
        alternatives_considered=[
            "Proceed without tax review (REJECTED — violates Gate-C evidence rules)",
            "Limit review to non-taxable accounts only",
        ],
        conditions_to_change_view=[
            ConditionToChangeView(
                condition="tax_lots.json becomes available AND account_constraints becomes available",
                new_position_if_met="SUPPORT or OPPOSE based on tax impact analysis",
                rationale="Full tax evidence enables definitive position",
            ),
        ],
        evidence_gaps=[
            "tax_lots.json unavailable",
            "account_constraints UNSUPPORTED in registry",
        ],
        deficiencies_acknowledged=["Tax review impossible without lot-level data and account-type classification"],
    )


def _morgan_conditional_advisory() -> SpecialistAdvisory:
    return SpecialistAdvisory(
        specialist_id="morgan",
        parent_run_id=PARENT_RUN_ID,
        run_purpose="PORTFOLIO_ALLOCATION_REVIEW",
        position=SpecialistAdvisoryPosition.SUPPORT,
        recommendation="Support increasing equity allocation IF liquidity and retirement projections remain above thresholds. Current cash reserves of 8% provide adequate buffer. Proposed allocation aligns with long-term wealth goals.",
        rationale="Cash reserves at 8% meet liquidity threshold. Retirement roadmap projects on-track. Income projections support additional equity exposure. Conditional support: verify liquidity stays above 5% and retirement projections remain on-track post-adjustment.",
        evidence_sources=_make_evidence_sources(["portfolio", "income", "retirement", "liquidity", "model_portfolio"]),
        evidence_summary="Cash reserves 8% (>5% threshold). Income yield at 2.3%. Retirement on-track. Liquidity adequate. Model portfolio targets achievable.",
        confidence=0.75,
        confidence_basis="PARTIAL_EVIDENCE",
        material_risks=[
            RiskFlag(risk_id="r8", description="Liquidity below 5% post-adjustment would trigger reconsideration", severity="LOW", evidence_refs=["ds-liquidity"]),
        ],
        alternatives_considered=[
            "Maintain current allocation until retirement projections verified",
            "Reduce equity increase to 2% to preserve liquidity buffer",
        ],
        conditions_to_change_view=[
            ConditionToChangeView(
                condition="Liquidity drops below 5% of portfolio value",
                new_position_if_met="OPPOSE",
                rationale="Liquidity below threshold compromises near-term flexibility",
            ),
            ConditionToChangeView(
                condition="Retirement projections fall below 90% probability",
                new_position_if_met="OPPOSE",
                rationale="Retirement adequacy must take priority over equity growth",
            ),
        ],
        evidence_gaps=["Retirement projections not independently verified"],
        deficiencies_acknowledged=["Retirement projections are policy projections, not independently validated"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TestSpecialistAdvisoryContract — schema validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecialistAdvisoryContract:

    def test_valid_specialist_advisory_passes_validation(self):
        adv = _maria_support_advisory()
        errors = validate_specialist_advisory(adv)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_fact_dump_only_advisory_rejected(self):
        adv = SpecialistAdvisory(
            specialist_id="maria",
            parent_run_id=PARENT_RUN_ID,
            run_purpose="PORTFOLIO_ALLOCATION_REVIEW",
            position=SpecialistAdvisoryPosition.NEUTRAL,
            recommendation="Here is the data: portfolio value is $500K, equity at 72%, Technology at 38%. End of summary.",
            rationale="",
            evidence_sources=_make_evidence_sources(["portfolio"]),
            evidence_summary="Data dump",
            confidence=0.5,
            confidence_basis="UNKNOWN",
            material_risks=[],
            alternatives_considered=[],
            conditions_to_change_view=[],
            evidence_gaps=[],
            deficiencies_acknowledged=[],
        )
        errors = validate_specialist_advisory(adv)
        assert len(errors) > 0, "Fact dump advisory should produce validation errors"
        assert any("fact-dump" in e.lower() or "rationale" in e.lower() for e in errors), \
            f"Expected fact-dump or rationale error, got: {errors}"

    def test_missing_required_fields_rejected(self):
        adv = SpecialistAdvisory(
            specialist_id="",
            parent_run_id="",
            run_purpose="",
            position=SpecialistAdvisoryPosition.NEUTRAL,
            recommendation="",
            rationale="",
            evidence_sources=[],
            evidence_summary="",
            confidence=0.5,
            confidence_basis="",
            material_risks=[],
            alternatives_considered=[],
            conditions_to_change_view=[],
            evidence_gaps=[],
            deficiencies_acknowledged=[],
        )
        errors = validate_specialist_advisory(adv)
        assert len(errors) > 0, f"Missing fields should produce errors, got none"

    def test_confidence_out_of_range_rejected(self):
        adv = _maria_support_advisory()
        adv.confidence = 1.5
        errors = validate_specialist_advisory(adv)
        assert any("confidence" in e.lower() for e in errors), \
            f"Expected confidence range error, got: {errors}"

    def test_no_conditions_to_change_view_rejected(self):
        adv = _maria_support_advisory()
        adv.conditions_to_change_view = []
        errors = validate_specialist_advisory(adv)
        assert any("conditions_to_change_view" in e.lower() for e in errors), \
            f"Expected missing conditions error, got: {errors}"

    def test_all_positions_are_valid_enum_values(self):
        for pos in SpecialistAdvisoryPosition:
            adv = _maria_support_advisory()
            adv.position = pos
            errors = validate_specialist_advisory(adv)
            assert len(errors) == 0, f"Position {pos.value} should be valid, but got: {errors}"

    def test_position_contains_explicit_recommendation(self):
        adv = _guardian_oppose_advisory()
        assert adv.recommendation, "OPPOSE advisory must include recommendation"
        assert adv.has_explicit_judgment, "Advisory must have explicit judgment"

    def test_insufficient_evidence_position_requires_gap_documentation(self):
        adv = _ledger_defer_advisory()
        assert adv.position == SpecialistAdvisoryPosition.DEFER
        assert adv.evidence_gaps, "DEFER advisory must document evidence gaps"
        assert adv.deficiencies_acknowledged, "DEFER advisory must acknowledge deficiencies"


# ═══════════════════════════════════════════════════════════════════════════════
# TestAdvisoryDisagreementFixture — the disagreement scenario
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvisoryDisagreementFixture:

    def test_disagreement_scenario_all_positions_documented(self):
        maria = _maria_support_advisory()
        steph = _steph_oppose_advisory()
        guardian = _guardian_oppose_advisory()
        ledger = _ledger_defer_advisory()
        morgan = _morgan_conditional_advisory()

        positions = {
            "maria": maria.position,
            "steph": steph.position,
            "guardian": guardian.position,
            "ledger": ledger.position,
            "morgan": morgan.position,
        }

        assert positions["maria"] == SpecialistAdvisoryPosition.SUPPORT
        assert positions["steph"] == SpecialistAdvisoryPosition.OPPOSE
        assert positions["guardian"] == SpecialistAdvisoryPosition.OPPOSE
        assert positions["ledger"] == SpecialistAdvisoryPosition.DEFER
        assert positions["morgan"] == SpecialistAdvisoryPosition.SUPPORT

    def test_majority_count_is_not_blind_vote(self):
        positions = {
            "maria": SpecialistAdvisoryPosition.SUPPORT,
            "steph": SpecialistAdvisoryPosition.OPPOSE,
            "guardian": SpecialistAdvisoryPosition.OPPOSE,
            "ledger": SpecialistAdvisoryPosition.DEFER,
            "morgan": SpecialistAdvisoryPosition.SUPPORT,
        }

        support_count = sum(1 for p in positions.values() if p == SpecialistAdvisoryPosition.SUPPORT)
        oppose_count = sum(1 for p in positions.values() if p == SpecialistAdvisoryPosition.OPPOSE)
        defer_count = sum(1 for p in positions.values() if p == SpecialistAdvisoryPosition.DEFER)

        assert support_count == 2
        assert oppose_count == 2
        assert defer_count == 1
        # This is a 2-2-1 split — NOT resolvable by simple majority
        assert support_count != 3, "Not a clear majority — Alex must reconcile, not blind-vote"


# ═══════════════════════════════════════════════════════════════════════════════
# TestAlexDisagreementResolution — Alex must reconcile, not blind vote
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlexDisagreementResolution:

    def test_alex_resolves_specialist_disagreement(self):
        # Maria: SUPPORT (thesis attractive)
        # Steph: OPPOSE (concentration too high)
        # Guardian: OPPOSE (risk envelope unacceptable)
        # Ledger: DEFER (tax evidence insufficient)
        # Morgan: SUPPORT_WITH_CONDITIONS (ok if liquidity above threshold)
        # Alex must: identify all 5 positions, note disagreement, resolve explicitly
        # NOT blind majority (3 support vs 2 oppose != just go with support)

        alex = AlexCIOAdvisory(
            parent_run_id=PARENT_RUN_ID,
            final_advisory_position="DEFER",
            recommendation=(
                "Defer action on equity increase until: (1) Technology sector concentration "
                "is reduced below 35% IPS limit, (2) defense_stops_protection evidence becomes "
                "available for Guardian's risk audit, and (3) tax lot data is available for "
                "Ledger's tax review. Maria's thesis is sound but cannot proceed against "
                "Steph's concentration warning and Guardian's risk blockage."
            ),
            specialist_positions={
                "maria": "SUPPORT",
                "steph": "OPPOSE",
                "guardian": "OPPOSE",
                "ledger": "DEFER",
                "morgan": "SUPPORT_WITH_CONDITIONS",
            },
            material_disagreements=[
                "Maria (SUPPORT) vs Steph (OPPOSE): Whether Technology sector concentration justifies overweighting",
                "Maria (SUPPORT) vs Guardian (OPPOSE): Whether risk headroom and unverified stop coverage permit new positions",
                "Morgan (conditional SUPPORT) vs Guardian (OPPOSE): Whether liquidity buffer offsets risk concerns",
            ],
            how_disagreements_were_resolved=(
                "Steph's concentration data is irrefutable — 38% Tech violates the 35% IPS limit. "
                "This is a hard constraint, not a judgment call. Guardian's risk concern is also "
                "deterministic: 82% heat with unverified stops leaves insufficient headroom. "
                "Maria's fundamental thesis and Morgan's liquidity assessment are both valid but "
                "cannot override hard IPS limits and risk governance. Defer until constraints are met."
            ),
            actionability="NEEDS_MORE_EVIDENCE",
            evidence_quality_summary=(
                "Portfolio and sector evidence full. Risk partially available (stops unverified). "
                "Tax evidence insufficient. Investment policy and model portfolio available."
            ),
            confidence=0.65,
            confidence_basis="PARTIAL_EVIDENCE",
            material_risks=[
                RiskFlag(risk_id="alex-r1", description="Proceeding against IPS concentration limit creates governance violation", severity="HIGH"),
                RiskFlag(risk_id="alex-r2", description="Unverified stop-loss coverage exposes portfolio to unprotected drawdown", severity="HIGH"),
                RiskFlag(risk_id="alex-r3", description="Unknown tax consequences could trigger wash-sale penalties", severity="MEDIUM"),
            ],
            rationale_linked_to_evidence=(
                "Decision driven by Steph's sector concentration evidence (38% Tech vs 35% IPS limit — "
                "a hard constraint) and Guardian's risk heat evidence (82% utilization with unverified stops). "
                "Maria's thesis quality and Morgan's liquidity assessment are noted but cannot override "
                "deterministic IPS limits and risk governance requirements."
            ),
            alternatives_considered=[
                "Proceed with equity increase despite concentration (REJECTED — violates IPS)",
                "Partial increase to 74% equity with Tech cap at 35% (CONSIDERED — still blocked by risk)",
                "Defer until all constraints met (SELECTED)",
            ],
            conditions_to_change_view=[
                ConditionToChangeView(
                    condition="Tech sector drops below 30% AND defense_stops_protection becomes AVAILABLE AND tax lots available",
                    new_position_if_met="BUY — equity increase to 75%",
                    rationale="All three blocking constraints resolved",
                ),
            ],
            evidence_gaps=[
                "defense_stops_protection DATA_UNAVAILABLE",
                "tax_lots DATA_UNAVAILABLE",
                "account_constraints UNSUPPORTED",
            ],
        )

        errors = validate_alex_advisory(alex)
        assert len(errors) == 0, f"Alex advisory validation failed: {errors}"

        assert len(alex.specialist_positions) == 5, "Must document all 5 specialist positions"
        assert len(alex.material_disagreements) == 3, "Must identify all 3 disagreements"
        assert alex.has_resolved_disagreements, "Alex must resolve disagreements"
        assert not alex.is_blind_vote, "Alex is not blind-voting"

    def test_alex_without_disagreement_resolution_is_fail(self):
        alex = AlexCIOAdvisory(
            parent_run_id=PARENT_RUN_ID,
            final_advisory_position="BUY",
            recommendation="Increase equity to 75%.",
            specialist_positions={
                "maria": "SUPPORT",
                "steph": "OPPOSE",
            },
            material_disagreements=["Maria vs Steph on concentration"],
            how_disagreements_were_resolved="",  # EMPTY — blind vote
            actionability="READY_FOR_OPERATOR",
            evidence_quality_summary="Mixed",
            confidence=0.70,
            confidence_basis="PARTIAL_EVIDENCE",
            material_risks=[],
            rationale_linked_to_evidence="Majority supports increase.",
            alternatives_considered=[],
            conditions_to_change_view=[],
            evidence_gaps=[],
        )

        errors = validate_alex_advisory(alex)
        assert len(errors) > 0, "Alex advisory with unresolved disagreements must fail"
        assert any("disagreement" in e.lower() for e in errors), \
            f"Expected disagreement resolution error, got: {errors}"


# ═══════════════════════════════════════════════════════════════════════════════
# TestSpecialistNeverCreatesFinalCIOAction — prohibited authority enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecialistNeverCreatesFinalCIOAction:

    def test_specialist_advisory_has_no_action_fields(self):
        adv = _maria_support_advisory()
        d = adv.to_dict()

        prohibited_fields = [
            "final_advisory_position",
            "cio_action",
            "action_type",
            "order_type",
            "execution_instruction",
            "quantity",
            "limit_price",
        ]
        for field in prohibited_fields:
            assert field not in d, \
                f"Specialist advisory must not contain '{field}' — only Alex creates final CIO actions"

    def test_specialist_recommendation_is_advisory_not_executive(self):
        recommendations = [
            _maria_support_advisory(),
            _steph_oppose_advisory(),
            _guardian_oppose_advisory(),
            _ledger_defer_advisory(),
            _morgan_conditional_advisory(),
        ]
        executive_verbs = ("execute", "submit", "place order", "transmit", "do it", "go ahead")
        for adv in recommendations:
            rec_lower = adv.recommendation.lower()
            for verb in executive_verbs:
                assert verb not in rec_lower, \
                    f"Specialist '{adv.specialist_id}' must not use executive language '{verb}'"

    def test_all_specialists_have_prohibited_authorities_clear(self):
        advisories = [
            _maria_support_advisory(),
            _steph_oppose_advisory(),
            _guardian_oppose_advisory(),
            _ledger_defer_advisory(),
            _morgan_conditional_advisory(),
        ]
        for adv in advisories:
            assert adv.specialist_id != "alex", \
                f"Specialist ID must not be 'alex': got {adv.specialist_id}"
            assert adv.position != "FINAL_CIO_DECISION", \
                f"Specialist must not claim CIO decision authority"

    def test_alex_advisory_is_the_only_executive_artifact(self):
        alex = AlexCIOAdvisory(
            parent_run_id=PARENT_RUN_ID,
            final_advisory_position="DEFER",
            recommendation="Defer until constraints met.",
            specialist_positions={"maria": "SUPPORT"},
            material_disagreements=[],
            how_disagreements_were_resolved="",
            actionability="NEEDS_MORE_EVIDENCE",
            evidence_quality_summary="Partial",
            confidence=0.6,
            confidence_basis="PARTIAL_EVIDENCE",
            material_risks=[],
            rationale_linked_to_evidence="Based on partial evidence.",
            alternatives_considered=[],
            conditions_to_change_view=[],
            evidence_gaps=[],
        )
        assert alex.final_advisory_position == "DEFER", "Alex must produce a final position"
        assert alex.actionability is not None, "Alex must declare actionability"


# ═══════════════════════════════════════════════════════════════════════════════
# TestEvidenceQualityTracksConfidence — PARTIAL evidence → lower confidence
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvidenceQualityTracksConfidence:

    def test_full_evidence_yields_higher_confidence(self):
        maria = _maria_support_advisory()
        steph = _steph_oppose_advisory()

        assert maria.confidence_basis == "FULL_EVIDENCE"
        assert steph.confidence_basis == "FULL_EVIDENCE"
        assert maria.confidence >= 0.80
        assert steph.confidence >= 0.80

    def test_partial_evidence_lowers_confidence(self):
        ledger = _ledger_defer_advisory()
        assert ledger.confidence_basis == "INSUFFICIENT_EVIDENCE"
        assert ledger.confidence < 0.60, \
            f"DEFER with insufficient evidence should have confidence < 0.60, got {ledger.confidence}"

    def test_guardian_partial_evidence_lower_confidence(self):
        guardian = _guardian_oppose_advisory()
        assert guardian.confidence_basis == "PARTIAL_EVIDENCE"
        assert guardian.confidence < 0.90, \
            f"PARTIAL evidence should bound confidence below 0.90, got {guardian.confidence}"

    def test_morgan_partial_evidence_lower_confidence(self):
        morgan = _morgan_conditional_advisory()
        assert morgan.confidence_basis == "PARTIAL_EVIDENCE"
        assert morgan.confidence < 0.85, \
            f"PARTIAL evidence should bound confidence, got {morgan.confidence}"

    def test_confidence_never_exceeds_95_with_any_evidence_gap(self):
        advisories = [
            _maria_support_advisory(),
            _steph_oppose_advisory(),
            _guardian_oppose_advisory(),
            _ledger_defer_advisory(),
            _morgan_conditional_advisory(),
        ]
        for adv in advisories:
            if adv.evidence_gaps:
                assert adv.confidence <= 0.90, \
                    f"{adv.specialist_id}: confidence {adv.confidence} too high with {len(adv.evidence_gaps)} gaps"

    def test_alex_confidence_reflects_partial_evidence(self):
        alex = AlexCIOAdvisory(
            parent_run_id=PARENT_RUN_ID,
            final_advisory_position="DEFER",
            recommendation="Defer — evidence incomplete.",
            specialist_positions={
                "maria": "SUPPORT",
                "steph": "OPPOSE",
                "guardian": "OPPOSE",
                "ledger": "DEFER",
                "morgan": "SUPPORT_WITH_CONDITIONS",
            },
            material_disagreements=["Maria vs Steph"],
            how_disagreements_were_resolved="Hard IPS constraints override thesis quality.",
            actionability="NEEDS_MORE_EVIDENCE",
            evidence_quality_summary="Two of five specialists operating with PARTIAL or INSUFFICIENT evidence.",
            confidence=0.65,
            confidence_basis="PARTIAL_EVIDENCE",
            material_risks=[],
            rationale_linked_to_evidence="Driven by deterministic constraints, not judgment.",
            alternatives_considered=[],
            conditions_to_change_view=[],
            evidence_gaps=["defense_stops_protection", "tax_lots", "account_constraints"],
        )

        assert alex.confidence_basis == "PARTIAL_EVIDENCE"
        assert alex.confidence < 0.75, \
            f"Alex confidence {alex.confidence} should reflect partial evidence"


# ═══════════════════════════════════════════════════════════════════════════════
# Test dict-level validation (cio_executive_advisory contract)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDictLevelValidation:

    def test_valid_dict_passes(self):
        adv = _maria_support_advisory()
        errors = validate_cioe_executive_advisory(adv.to_dict())
        assert len(errors) == 0, f"Expected no errors for valid dict, got: {errors}"

    def test_missing_fields_in_dict_rejected(self):
        errors = validate_cioe_executive_advisory({"specialist_id": "maria"})
        assert len(errors) > 0, "Missing fields should produce errors"

    def test_fact_dump_recommendation_in_dict_rejected(self):
        d = {
            "specialist_id": "maria",
            "parent_run_id": "test",
            "run_purpose": "TEST",
            "position": "NEUTRAL",
            "recommendation": "Here is the data: portfolio at $500K with 23 positions. That's the summary.",
            "rationale": "",
            "evidence_sources": [{"source_id": "s1", "domain": "portfolio"}],
            "conditions_to_change_view": [{"condition": "test", "new_position_if_met": "SUPPORT", "rationale": "test"}],
        }
        errors = validate_cioe_executive_advisory(d)
        assert any("fact dump" in e.lower() for e in errors), \
            f"Expected fact dump error, got: {errors}"

    def test_invalid_position_in_dict_rejected(self):
        d = _maria_support_advisory().to_dict()
        d["position"] = "EXECUTE_NOW"
        errors = validate_cioe_executive_advisory(d)
        assert any("invalid position" in e.lower() for e in errors), \
            f"Expected invalid position error, got: {errors}"


# ═══════════════════════════════════════════════════════════════════════════════
# Promotion condition evaluation — offline-testable conditions
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromotionConditionEvaluation:
    """Verify that offline-testable promotion conditions are correctly scored."""

    def test_schema_validated_is_not_proven_not_fail(self):
        """Condition 5 moves from FAIL to NOT_PROVEN (schema code is validated)."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        result = evaluate_promotion_condition("maria", 5, schema_validated=True)
        assert result == "NOT_PROVEN", f"Condition 5 should be NOT_PROVEN after schema validation, got {result}"

    def test_prohibited_authorities_is_not_proven(self):
        """Condition 13: schema enforces prohibited authorities, but runtime not proven."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        result = evaluate_promotion_condition("maria", 13)
        assert result == "NOT_PROVEN", f"Condition 13 should be NOT_PROVEN, got {result}"

    def test_governed_path_exists_is_not_proven(self):
        """Condition 4: registry exists but not runtime-proven."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        result = evaluate_promotion_condition("maria", 4, governed_path_exists=True)
        assert result == "NOT_PROVEN", f"Condition 4 should be NOT_PROVEN with path, got {result}"

    def test_no_governed_path_is_fail(self):
        """Condition 4 without registry entry is FAIL."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        result = evaluate_promotion_condition("unknown", 4, governed_path_exists=False)
        assert result == "FAIL"

    def test_live_canary_conditions_remain_fail(self):
        """Conditions 1-3, 11, 17 require live canary → still FAIL."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        for cond in [1, 2, 3, 11, 17]:
            result = evaluate_promotion_condition("maria", cond)
            assert result == "FAIL", f"Condition {cond} should be FAIL, got {result}"

    def test_handoff_conditions_not_applicable(self):
        """Conditions 15-16 are N/A for specialists."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        for cond in [15, 16]:
            result = evaluate_promotion_condition("maria", cond)
            assert result == "NOT_APPLICABLE", f"Condition {cond} should be N/A, got {result}"

    def test_all_specialists_same_baseline(self):
        """All 5 specialists share the same promotion baseline."""
        from scripts.lib.cio_advisory_readiness import evaluate_all_conditions

        baseline = evaluate_all_conditions("maria")
        for sid in ["steph", "guardian", "ledger", "morgan"]:
            assert evaluate_all_conditions(sid) == baseline, \
                f"{sid} promotion baseline differs from maria"

    def test_conditions_6_10_content_fields_not_proven(self):
        """Advisory content fields need specialist output proof."""
        from scripts.lib.cio_advisory_readiness import evaluate_promotion_condition
        for cond in [6, 7, 8, 9, 10]:
            result = evaluate_promotion_condition("maria", cond)
            assert result == "NOT_PROVEN", f"Condition {cond} should be NOT_PROVEN, got {result}"

    def test_no_specialist_has_pass_yet(self):
        """No specialist has any PASS condition before live canary."""
        from scripts.lib.cio_advisory_readiness import evaluate_all_conditions
        for sid in ["maria", "steph", "guardian", "ledger", "morgan"]:
            results = evaluate_all_conditions(sid)
            passes = sum(1 for v in results.values() if v == "PASS")
            assert passes == 0, f"{sid} has {passes} PASS conditions before live canary"

    def test_schema_tier_distinction(self):
        """SCHEMA_DEFINED, SCHEMA_VALIDATED, and LIVE_OUTPUT_VALIDATED are distinct."""
        # SCHEMA_DEFINED: the dataclass exists (importable)
        from scripts.lib.cio_advisory_schema import (
            SpecialistAdvisory, AlexCIOAdvisory,
            validate_specialist_advisory, validate_alex_advisory,
        )
        assert SpecialistAdvisory is not None
        assert AlexCIOAdvisory is not None

        # SCHEMA_VALIDATED: validation functions work (offline tests prove)
        assert callable(validate_specialist_advisory)
        assert callable(validate_alex_advisory)

        # LIVE_OUTPUT_VALIDATED: requires live canary (NOT_PROVEN here)


# ═══════════════════════════════════════════════════════════════════════════════
# CIOSpecialistAdvisoryReadiness class-based tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCIOSpecialistAdvisoryReadiness:
    """Tests for the CIOSpecialistAdvisoryReadiness class API."""

    def test_condition_4_governed_path_detectable_for_all_six(self):
        from scripts.lib.cio_advisory_readiness import (
            CIOSpecialistAdvisoryReadiness, NOT_PROVEN,
        )
        expected = {"maria", "steph", "guardian", "ledger", "morgan", "alex"}
        for sid in expected:
            result = CIOSpecialistAdvisoryReadiness.evaluate_condition(sid, 4)
            assert result == NOT_PROVEN, (
                f"Condition 4 for '{sid}' should be NOT_PROVEN, got {result}"
            )

    def test_condition_5_schema_validated_proven_offline(self):
        from scripts.lib.cio_advisory_readiness import (
            CIOSpecialistAdvisoryReadiness, NOT_PROVEN, FAIL,
            SCHEMA_VALIDATED, LIVE_OUTPUT_VALIDATED,
        )
        assert CIOSpecialistAdvisoryReadiness.is_schema_defined()
        assert CIOSpecialistAdvisoryReadiness.is_schema_validated_offline()
        tier = CIOSpecialistAdvisoryReadiness.advisory_schema_tier()
        assert tier == SCHEMA_VALIDATED
        assert tier != LIVE_OUTPUT_VALIDATED

        for sid in ("maria", "steph", "guardian", "ledger", "morgan"):
            result = CIOSpecialistAdvisoryReadiness.evaluate_condition(sid, 5)
            assert result == NOT_PROVEN
            assert result != FAIL

    def test_condition_6_explicit_recommendation_required(self):
        from scripts.lib.cio_advisory_readiness import (
            CIOSpecialistAdvisoryReadiness, NOT_PROVEN,
        )
        # Schema enforces recommendation — empty recommendation rejected
        adv = SpecialistAdvisory(
            specialist_id="test", parent_run_id="test-run", run_purpose="TEST",
            position=SpecialistAdvisoryPosition.NEUTRAL,
            recommendation="", rationale="Valid rationale.",
            evidence_sources=_make_evidence_sources(["portfolio"]),
            evidence_summary="OK", confidence=0.5, confidence_basis="PARTIAL_EVIDENCE",
            material_risks=[], alternatives_considered=[],
            conditions_to_change_view=[], evidence_gaps=[], deficiencies_acknowledged=[],
        )
        errors = validate_specialist_advisory(adv)
        assert len(errors) > 0

        for sid in ("maria", "steph", "guardian", "ledger", "morgan"):
            result = CIOSpecialistAdvisoryReadiness.evaluate_condition(sid, 6)
            assert result == NOT_PROVEN

    def test_condition_10_conditions_to_change_view_required(self):
        from scripts.lib.cio_advisory_readiness import (
            CIOSpecialistAdvisoryReadiness, NOT_PROVEN,
        )
        adv = _maria_support_advisory()
        adv.conditions_to_change_view = []
        errors = validate_specialist_advisory(adv)
        assert len(errors) > 0

        for sid in ("maria", "steph", "guardian", "ledger", "morgan"):
            result = CIOSpecialistAdvisoryReadiness.evaluate_condition(sid, 10)
            assert result == NOT_PROVEN

    def test_condition_12_confidence_bounded_by_evidence(self):
        from scripts.lib.cio_advisory_readiness import (
            CIOSpecialistAdvisoryReadiness, NOT_PROVEN,
        )
        adv = _maria_support_advisory()
        adv.confidence = 1.5
        errors = validate_specialist_advisory(adv)
        assert any("confidence" in e.lower() for e in errors)

        for sid in ("maria", "steph", "guardian", "ledger", "morgan"):
            result = CIOSpecialistAdvisoryReadiness.evaluate_condition(sid, 12)
            assert result == NOT_PROVEN

    def test_condition_13_prohibited_authorities_enforced_by_schema(self):
        from scripts.lib.cio_advisory_readiness import (
            CIOSpecialistAdvisoryReadiness, EXECUTIVE_ACTION_FIELDS,
            NOT_PROVEN, FAIL,
        )
        from dataclasses import fields as dc_fields

        adv_fields = {f.name for f in dc_fields(SpecialistAdvisory)}
        overlap = adv_fields & EXECUTIVE_ACTION_FIELDS
        assert not overlap

        advisories = [
            _maria_support_advisory(), _steph_oppose_advisory(),
            _guardian_oppose_advisory(), _ledger_defer_advisory(),
            _morgan_conditional_advisory(),
        ]
        for adv in advisories:
            d = adv.to_dict()
            for field in EXECUTIVE_ACTION_FIELDS:
                assert field not in d

        for sid in ("maria", "steph", "guardian", "ledger", "morgan"):
            result = CIOSpecialistAdvisoryReadiness.evaluate_condition(sid, 13)
            assert result == NOT_PROVEN
            assert result != FAIL


