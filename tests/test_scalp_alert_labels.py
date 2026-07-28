#!/usr/bin/env python3
"""Scalp alerts carry the named setup + MANUAL PAPER ONLY, and remain non-proposal."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_alert_emitter as ae  # noqa: E402


def test_alert_names_primary_setup_and_manual_paper_only():
    row = {"symbol": "ABCD", "ign": 72, "lane": "IGN_ACCEL", "subscores": {"v_rvol": 0.8},
           "rvol_tod": 8.4, "_tax": {"primary_setup_label": "MICRO PULLBACK",
                                     "matched_setup_labels": ["MICRO PULLBACK", "IGNITION BREAKOUT"],
                                     "market_session": "REGULAR"}}
    title, body = ae.build_alert(row)
    assert "MICRO PULLBACK" in title and "MULTI-SETUP" in title
    assert "IGNITION BREAKOUT" in body and "session=REGULAR" in body
    assert "MANUAL PAPER ONLY — NOT AN ORDER" in body
    assert ae.NOT_A_PROPOSAL in body


def test_alert_without_taxonomy_still_builds():
    title, body = ae.build_alert({"symbol": "WXYZ", "ign": 61, "lane": "IGN_60", "subscores": {}})
    assert "WXYZ" in title and "NOT AN ORDER" in body


def test_lane_75_is_still_an_alert_not_a_proposal():
    assert ae.LANE_TIER["IGN_75"] == "ALERT"        # never a proposal


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
