"""Unit tests for scripts/lib/material_residual_gate.py — pre-model gate."""

from __future__ import annotations

from scripts.lib.judgment_schema import (
    CAP_REFUSED,
    FREE_FIRST_PENDING,
    GATE_PROCEED,
    NO_MATERIAL_RESIDUAL,
    OFFPEAK_DEFERRED,
    UNGROUNDED_REFUSED,
    WRONG_SUBJECT_REFUSED,
)
from scripts.lib.material_residual_gate import evaluate_material_residual_gate
from tests.helpers.l3_fixtures import (
    DEFERRED_SUMMER_ET,
    FACT_A1,
    OFFICIAL_PEAK_UTC,
    OFFPEAK_SUMMER_ET,
    OFFPEAK_WINTER_ET,
    SUBJECT_A,
    SUBJECT_B,
    make_fact,
    make_grounded_input,
)


def test_no_grounding_zero_calls():
    gate = evaluate_material_residual_gate(
        make_grounded_input(grounded=False, facts=[]),
        now=OFFPEAK_SUMMER_ET,
    )
    assert gate.proceed is False
    assert gate.state == UNGROUNDED_REFUSED
    assert gate.provider_calls_allowed == 0


def test_wrong_subject_memory_refused():
    gate = evaluate_material_residual_gate(
        make_grounded_input(
            facts=[
                make_fact(
                    memory_fact_id=FACT_A1,
                    subject_guid=SUBJECT_B,
                    fact_text="belongs to other subject",
                )
            ],
            filtered_wrong_subject=1,
        ),
        now=OFFPEAK_SUMMER_ET,
    )
    assert gate.proceed is False
    assert gate.state == WRONG_SUBJECT_REFUSED
    assert gate.provider_calls_allowed == 0


def test_free_first_not_exhausted_zero_calls():
    gate = evaluate_material_residual_gate(
        make_grounded_input(free_first_exhausted=False),
        now=OFFPEAK_SUMMER_ET,
    )
    assert gate.proceed is False
    assert gate.state == FREE_FIRST_PENDING
    assert gate.provider_calls_allowed == 0


def test_no_material_residual_zero_calls():
    gate = evaluate_material_residual_gate(
        make_grounded_input(residual_present=False),
        now=OFFPEAK_SUMMER_ET,
    )
    assert gate.proceed is False
    assert gate.state == NO_MATERIAL_RESIDUAL
    assert gate.provider_calls_allowed == 0


def test_offpeak_deferred_outside_bulk():
    gate = evaluate_material_residual_gate(
        make_grounded_input(),
        now=DEFERRED_SUMMER_ET,
    )
    assert gate.proceed is False
    assert gate.state == OFFPEAK_DEFERRED
    assert gate.provider_calls_allowed == 0


def test_offpeak_eligible_summer_and_winter():
    for when in (OFFPEAK_SUMMER_ET, OFFPEAK_WINTER_ET):
        gate = evaluate_material_residual_gate(make_grounded_input(), now=when)
        assert gate.proceed is True, when
        assert gate.state == GATE_PROCEED
        assert gate.provider_calls_allowed == 2


def test_official_peak_utc_deferred():
    gate = evaluate_material_residual_gate(make_grounded_input(), now=OFFICIAL_PEAK_UTC)
    assert gate.proceed is False
    assert gate.state == OFFPEAK_DEFERRED
    assert "official_deepseek_peak_utc" in gate.reasons[0] or any("peak" in r for r in gate.reasons)


def test_urgent_requires_allowlisted_basis_not_prose():
    # Outside off-peak with prose-only urgency → still deferred.
    prose = make_grounded_input(
        trigger="urgent",
        materiality_basis="because_operator_said_so",
    )
    prose["material_residual_question"]["urgency_prose"] = "this is extremely urgent!!!"
    gate = evaluate_material_residual_gate(prose, now=DEFERRED_SUMMER_ET)
    assert gate.proceed is False
    assert gate.state == OFFPEAK_DEFERRED
    assert any("allowlist" in r or "materiality_basis" in r for r in gate.reasons)

    ok = make_grounded_input(
        trigger="urgent",
        materiality_basis="price_move_gt_threshold",
        resolution_confidence=0.9,
    )
    gate_ok = evaluate_material_residual_gate(ok, now=DEFERRED_SUMMER_ET)
    assert gate_ok.proceed is True
    assert gate_ok.state == GATE_PROCEED


def test_caps_refuse_zero_calls():
    for kwargs in (
        {"budget_remaining_usd": 0.0},
        {"lane_calls_remaining": 0},
        {"request_cap_remaining": 0},
    ):
        gate = evaluate_material_residual_gate(
            make_grounded_input(),
            now=OFFPEAK_SUMMER_ET,
            **kwargs,
        )
        assert gate.proceed is False
        assert gate.state == CAP_REFUSED
        assert gate.provider_calls_allowed == 0


def test_subject_guid_present():
    raw = make_grounded_input()
    assert raw["subject"]["subject_guid"] == SUBJECT_A
