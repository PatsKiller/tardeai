"""Honest desk scorecard. A passing test is not a validated outcome."""
from __future__ import annotations

from typing import Any, Optional

SCHEMA = "OptionsDeskScorecard@v1"


def build_scorecard(
    *,
    closed_outcomes: int = 0,
    open_positions: int = 0,
    served_sha: Optional[str] = None,
    independently_replayed: bool = False,
) -> dict[str, Any]:
    outcome = "OUTCOME_VALIDATED" if closed_outcomes > 0 and independently_replayed else "not_validated"
    return {
        "schema": SCHEMA,
        "served_sha": served_sha,
        "sample": {
            "closed_outcomes": closed_outcomes,
            "open_positions": open_positions,
        },
        "outcome_validated": outcome == "OUTCOME_VALIDATED",
        "paper_gate": "0/30 remains 0/30 without genuine closed paper outcomes",
        "memory_behavior_influence": 0,
        "axes": {
            "correctness": "FIXTURE_PASS",
            "coverage": "CODE_PRESENT",
            "freshness": "CODE_PRESENT",
            "recommendation_quality": "FIXTURE_PASS",
            "lifecycle": "CODE_PRESENT",
            "operator_experience": "CODE_PRESENT",
            "safety": "FIXTURE_PASS",
            "learning": outcome,
        },
        "served_pass": False,
        "natural_fire_observed": False,
        "note": "A unit test is not validation. A computed preference is not a CIO approval.",
    }
