"""Wave 2 slice 08: coverage object on /v3/cio/home (Class D). Fail-soft zeros.

Slice 12b tightened ``with_plan`` to open S1/S3/S5/S6 plans only, so these
fixtures carry an explicit ``situation_type``. The assertions are unchanged.
"""
from __future__ import annotations

from scripts.lib.cio_command_center import build_office_coverage, build_office_home


def test_coverage_from_existing_keys():
    cov = build_office_coverage(
        holdings_thesis_coverage={
            "held_n": 19,
            "current_n": 19,
            "unavailable_n": 0,
            "items": [
                {"symbol": "SCHD", "thesis_status": "CURRENT"},
                {"symbol": "NOC", "thesis_status": "CURRENT"},
            ],
        },
        watch_block_summary={
            "count": 21,
            "ready_symbols": [],
            "near_symbols": [],
            "ready_count": 0,
            "fires_s7": False,
        },
        case_summaries={"count": 323, "items": [], "class": "A"},
        reentry={"count": 67, "counts": {"NEAR": 4, "WAIT": 50, "AVOID": 13}},
        plans=[
            {"status": "draft", "situation_type": "S1_POSITION_LIFECYCLE",
             "symbols": ["SCHD"], "hermes_result_id": "res_1"},
            {"status": "proposed", "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
             "symbols": ["NOC"]},
            {"status": "cancelled", "situation_type": "S1_POSITION_LIFECYCLE",
             "symbols": ["SCHD"], "hermes_result_id": "res_x"},
        ],
    )
    assert cov["class"] == "D"
    assert cov["held"] == 19
    assert cov["held_n"] == 19
    assert cov["with_thesis"] == 19
    assert cov["thesis_count"] == 19
    assert cov["with_plan"] == 2
    assert cov["with_research"] == 1
    assert cov["with_case_summary"] == 323
    assert cov["watch_ready"] == 0
    assert cov["watch_block"] == 21
    assert cov["reentry_near"] == 4
    assert cov["memory_behavior_influence"] == 0
    assert cov["authority"] == "READ_ONLY_ADVISORY"


def test_coverage_fail_soft_zeros():
    cov = build_office_coverage()
    for k in (
        "held", "with_plan", "with_thesis", "with_research",
        "with_case_summary", "watch_ready", "watch_block", "reentry_near",
    ):
        assert cov[k] == 0, k
    assert cov["class"] == "D"


def test_home_wires_coverage():
    home = build_office_home(
        operator_product={
            "holdings_thesis_coverage": {
                "held_n": 3,
                "current_n": 2,
                "unavailable_n": 1,
                "items": [
                    {"symbol": "AAA", "thesis_status": "CURRENT"},
                    {"symbol": "BBB", "thesis_status": "CURRENT"},
                    {"symbol": "CCC", "thesis_status": "UNAVAILABLE"},
                ],
            },
            "watch_block_summary": {
                "count": 5,
                "ready_symbols": ["XYZ"],
                "near_symbols": [],
            },
            "case_summaries": {"count": 10, "items": [], "class": "A"},
            "reentry": {"count": 8, "counts": {"NEAR": 2}},
        },
        plans=[{"status": "draft", "situation_type": "S1_POSITION_LIFECYCLE",
                "symbols": ["AAA"], "hermes_result_id": "r1"}],
    )
    assert "coverage" in home
    assert home["coverage"]["held"] == 3
    assert home["coverage"]["with_thesis"] == 2
    assert home["coverage"]["watch_ready"] == 1
    assert home["coverage"]["watch_block"] == 5
    assert home["coverage"]["reentry_near"] == 2
    assert home["coverage"]["with_plan"] == 1
    assert home["coverage"]["with_research"] == 1
    assert home["telegram_sent"] is False
