"""Wave 2 slice 11: thesis_count / held_n exposed clearly on coverage.

Does not silently change held_n semantics (SCHG dust may remain in
held_equity_symbols). Card shows thesis_count/held_n.
"""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_command_center import build_office_coverage, build_office_home

HUB = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "command-center-v3"
    / "src"
    / "pages"
    / "CioHub.tsx"
)


def test_coverage_exposes_thesis_count_and_held_n_aliases():
    cov = build_office_coverage(
        holdings_thesis_coverage={
            "held_n": 19,
            "current_n": 19,
            "unavailable_n": 0,
            "items": [{"symbol": "SCHD"}, {"symbol": "SCHG"}],  # SCHG dust still listed
        },
    )
    assert cov["held_n"] == 19
    assert cov["held"] == 19
    assert cov["thesis_count"] == 19
    assert cov["with_thesis"] == 19
    # Aliases stay aligned — no silent held_n rewrite
    assert cov["held_n"] == cov["held"]
    assert cov["thesis_count"] == cov["with_thesis"]


def test_home_coverage_thesis_ratio_keys():
    home = build_office_home(
        operator_product={
            "holdings_thesis_coverage": {
                "held_n": 19,
                "current_n": 18,
                "unavailable_n": 1,
                "items": [{"symbol": f"S{i}"} for i in range(19)],
            },
        },
    )
    c = home["coverage"]
    assert c["thesis_count"] == 18
    assert c["held_n"] == 19


def test_ciohub_card_shows_thesis_over_held():
    src = HUB.read_text(encoding="utf-8")
    assert "Thesis / held" in src
    assert "thesisCount" in src and "heldN" in src
    assert "thesis_count / held_n" in src or "thesis_count" in src
    assert "SCHG dust" in src  # honesty note in help text
