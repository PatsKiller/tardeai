"""Wave 2 slice 10: home opportunities reentry keys non-zero when Surface A has names.

Dual pipes: queue chips vs Surface A book — labeled, not merged.
"""
from __future__ import annotations

from scripts.lib.cio_command_center import (
    build_office_home,
    build_opportunities,
    overlay_surface_a_reentry_on_opportunities,
)


def test_overlay_nonzero_when_surface_a_names_nonempty():
    base = build_opportunities(queue={"items": []})
    assert base["reentry_total"] == 0
    out = overlay_surface_a_reentry_on_opportunities(
        base,
        {
            "count": 67,
            "counts": {"NEAR": 5, "REENTER": 2, "WAIT": 40, "AVOID": 20},
            "names": [{"symbol": "ADBE", "status": "NEAR"}] * 67,
        },
    )
    assert out["surface_a_reentry_count"] == 67
    assert out["surface_a_reentry_near"] == 5
    assert out["surface_a_reentry_reenter"] == 2
    assert out["reentry_total"] == 7  # NEAR+REENTER overlay
    assert out["queue_reentry_total"] == 0
    assert out["reentry_pipes"]["merged"] is False
    assert out["reentry"] == []  # books not merged into chips


def test_overlay_falls_back_to_book_count_when_no_near_reenter():
    out = overlay_surface_a_reentry_on_opportunities(
        {"reentry": [], "reentry_total": 0},
        {"count": 67, "counts": {"WAIT": 50, "AVOID": 17}, "names": [{"symbol": "X"}] * 67},
    )
    assert out["reentry_total"] == 67
    assert out["surface_a_reentry_near"] == 0


def test_overlay_from_operator_reentry_without_names_list():
    """Operator product stamps count/counts but not names — still non-zero."""
    out = overlay_surface_a_reentry_on_opportunities(
        {"reentry": [], "reentry_total": 0},
        {"count": 67, "counts": {"NEAR": 3, "REENTER": 1}},
    )
    assert out["reentry_total"] == 4
    assert out["surface_a_reentry_count"] == 67


def test_home_opportunities_overlay_from_operator_product():
    home = build_office_home(
        opportunity_queue={"items": []},
        operator_product={
            "reentry": {
                "count": 67,
                "counts": {"NEAR": 4, "REENTER": 0, "WAIT": 63},
                "surface": "A",
            },
            "holdings_thesis_coverage": {},
            "watch_block_summary": {},
            "case_summaries": {"count": 0, "items": []},
        },
    )
    opp = home["opportunities"]
    assert opp["reentry_total"] > 0
    assert opp["surface_a_reentry_count"] == 67
    assert opp["surface_a_reentry_near"] == 4
    assert opp["reentry_pipes"]["merged"] is False
    assert opp["reentry"] == []


def test_queue_pipe_preserved_when_both_present():
    home = build_office_home(
        opportunity_queue={
            "items": [
                {
                    "symbol": "ADBE",
                    "source": "reentry",
                    "directive_label": "Re-entry NEAR ENTRY — ADBE",
                }
            ]
        },
        operator_product={
            "reentry": {"count": 67, "counts": {"NEAR": 5, "REENTER": 2}},
        },
    )
    opp = home["opportunities"]
    assert [r["symbol"] for r in opp["reentry"]] == ["ADBE"]
    assert opp["queue_reentry_total"] == 1
    assert opp["surface_a_reentry_count"] == 67
    assert opp["reentry_total"] == 7
