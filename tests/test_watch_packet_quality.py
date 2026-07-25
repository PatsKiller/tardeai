from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import watch_packet_quality as quality


def validation(state="PASS", quality_state="ADMITTED", allowed=True):
    return {
        "state": state,
        "ticket_hash": f"{state}-{quality_state}",
        "hard_failures": ["blocked"] if state == "FAIL" else [],
        "warnings": ["review"] if state == "REVIEW_REQUIRED" else [],
        "quality_admission": {
            "state": quality_state,
            "new_entry_allowed": allowed,
            "reasons": [quality_state.lower()],
        },
    }


def test_current_actionable_plan_is_governing_when_present():
    packet = {
        "current_actionable_plan": {
            "family": "SWING",
            "ticket_validation": validation("PASS", "ADMITTED", True),
        },
        "plan_families": {
            "long_term": {
                "structures": [{
                    "ticket_validation": validation("FAIL", "QUARANTINED", False),
                }],
            },
        },
    }
    selected = quality.select_governing_validation(packet)
    assert selected["source"] == "current_actionable_plan"
    assert selected["deterministic"] == "PASS"
    assert selected["quality"] == "ADMITTED"


def test_stripped_current_plan_preserves_failed_family_gate():
    packet = {
        "current_actionable_plan": None,
        "plan_families": {
            "swing": {
                "structures": [{
                    "structure": "PULLBACK_SWING",
                    "ticket_validation": validation("FAIL", "QUARANTINED", False),
                }],
            },
        },
    }
    selected = quality.select_governing_validation(packet)
    gate = quality.packet_gate(packet)
    assert selected["source"] == "plan_families.swing.structures[0]"
    assert selected["deterministic"] == "FAIL"
    assert gate["quality"] == "QUARANTINED"
    assert gate["new_entry_allowed"] is False
    assert gate["hard_failures"] == ["blocked"]


def test_most_severe_retained_result_governs_without_current_plan():
    packet = {
        "plan_families": {
            "long_term": {
                "structures": [{
                    "ticket_validation": validation("PASS", "ADMITTED", True),
                }],
            },
            "swing": {
                "structures": [{
                    "ticket_validation": validation("REVIEW_REQUIRED", "RESEARCH_ONLY", False),
                }],
            },
            "options": {
                "structures": [{
                    "ticket_validation": validation("FAIL", "QUARANTINED", False),
                }],
            },
        },
    }
    selected = quality.select_governing_validation(packet)
    assert selected["source"] == "plan_families.options.structures[0]"
    assert selected["deterministic"] == "FAIL"
    assert selected["quality"] == "QUARANTINED"


def test_packet_gate_preserves_held_management_context():
    packet = {
        "ownership": {"held": True, "shares": 100},
        "plan_families": {
            "swing": {
                "structures": [{
                    "ticket_validation": validation("FAIL", "QUARANTINED", False),
                }],
            },
        },
    }
    gate = quality.packet_gate(packet)
    assert gate["held"] is True
    assert gate["quality"] == "QUARANTINED"


def test_missing_validation_is_unassessed_not_pass():
    selected = quality.select_governing_validation({"plan_families": {}})
    assert selected["deterministic"] == "NOT_RUN"
    assert selected["quality"] == "UNASSESSED"


def test_packet_level_quality_survives_when_no_ticket_exists():
    packet = {
        "quality_admission": {
            "state": "RESEARCH_ONLY",
            "new_entry_allowed": False,
            "reasons": ["current mechanics unavailable"],
        },
        "plan_families": {},
    }
    selected = quality.select_governing_validation(packet)
    gate = quality.packet_gate(packet)
    assert selected["source"] == "quality_admission"
    assert selected["deterministic"] == "NOT_RUN"
    assert selected["quality"] == "RESEARCH_ONLY"
    assert gate["new_entry_allowed"] is False
    assert gate["quality_reasons"] == ["current mechanics unavailable"]


def test_legacy_wait_header_with_non_primary_ready_is_reported_as_conflict():
    packet = {
        "operator_presentation": {"header_state": "WAIT"},
        "plan_families": {
            "long_term": {"action_state": "READY"},
            "swing": {"action_state": "WAIT"},
        },
    }
    conflicts = quality.presentation_conflicts(packet)
    assert len(conflicts) == 1
    assert "header WAIT" in conflicts[0]
    assert "long_term" in conflicts[0]


def test_apply_operator_presentation_scopes_secondary_ready_as_eligibility():
    packet = {
        "decision_state": "WAIT",
        "current_actionable_plan": {"family": "SWING"},
        "plan_families": {
            "long_term": {"action_state": "READY"},
            "swing": {"action_state": "WAIT"},
        },
    }
    out = quality.apply_operator_presentation(packet)
    presentation = out["operator_presentation"]
    assert presentation["contract"] == "watch-quality-governance-v1"
    assert presentation["header_state"] == "WAIT"
    assert presentation["primary_family"] == "SWING"
    assert presentation["family_display_states"]["LONG_TERM"] == "OWNERSHIP ELIGIBLE"
    assert presentation["family_display_states"]["SWING"] == "WAIT"
    assert quality.presentation_conflicts(out) == []
    assert out["plan_families"]["long_term"]["action_state"] == "READY"


def test_primary_ready_remains_ready_only_when_header_is_ready():
    packet = {
        "decision_state": "READY",
        "current_actionable_plan": {"family": "SWING"},
        "plan_families": {
            "long_term": {"action_state": "READY"},
            "swing": {"action_state": "READY"},
        },
    }
    quality.apply_operator_presentation(packet)
    states = packet["operator_presentation"]["family_display_states"]
    assert states["SWING"] == "READY"
    assert states["LONG_TERM"] == "OWNERSHIP ELIGIBLE"
    assert quality.presentation_conflicts(packet) == []
