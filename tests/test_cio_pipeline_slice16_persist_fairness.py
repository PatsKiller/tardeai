"""Slice 16: persist ≥1 S3 when candidates exist; skip duplicate open S1."""
from __future__ import annotations

from scripts.lib.cio_situation_detector import fairness_order_s3


PRIORITY = {
    "S5_CASH_DEPLOYMENT": 0,
    "S6_CONCENTRATION_OR_DISPOSITION": 1,
    "S1_POSITION_LIFECYCLE": 3,
    "S3_REENTRY_CANDIDATE": 5,
}


def test_s3_is_placed_before_mass_s1_when_present():
    cands = (
        [{"situation_type": "S5_CASH_DEPLOYMENT", "symbols": ["CASH"]}]
        + [{"situation_type": "S1_POSITION_LIFECYCLE", "symbols": [f"S{i}"]} for i in range(8)]
        + [{"situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["ATAI"]}]
    )
    ordered = fairness_order_s3(cands, PRIORITY)
    types = [c["situation_type"] for c in ordered[:3]]
    assert "S3_REENTRY_CANDIDATE" in types
    assert types[0] == "S5_CASH_DEPLOYMENT"


def test_no_s3_leaves_order():
    cands = [{"situation_type": "S1_POSITION_LIFECYCLE", "symbols": ["SCHD"]}]
    assert fairness_order_s3(cands, PRIORITY) == cands
