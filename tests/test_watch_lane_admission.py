"""Unit tests — watch lane admission (MAIN / RESEARCH / COVERAGE)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from watch_lane_admission import (  # noqa: E402
    annotate_item,
    classify_lane,
    is_coverage_source,
    is_no_trade_setup,
    is_setup_shaped,
    now_status,
    quality_board_from_items,
)


def test_analyst_source_is_coverage_not_main():
    it = {
        "symbol": "FOO",
        "source": "analyst_coverage",
        "decision_actionable": True,
        "setup_context": {"type": "pullback entry"},
    }
    assert is_coverage_source("analyst_coverage")
    assert classify_lane(it) == "coverage"
    assert now_status(annotate_item(it)) == "COVERAGE"


def test_ai_discovered_no_trade_is_research():
    it = {
        "symbol": "BAR",
        "source": "ai_discovered",
        "setup_context": {"type": "no-trade (downtrend)"},
        "decision_actionable": False,
    }
    assert is_no_trade_setup(it)
    assert classify_lane(it) == "research"


def test_ai_discovered_actionable_stays_research_without_promote():
    """Quantity trap: 4.5k ai_discovered must not flood MAIN via actionable alone."""
    it = {
        "symbol": "FLOOD",
        "source": "ai_discovered",
        "setup_context": {"type": "pullback entry"},
        "decision_actionable": True,
        "decision_quality_status": "actionable",
    }
    assert classify_lane(it) == "research"


def test_pullback_actionable_is_main_go():
    it = {
        "symbol": "BAZ",
        "source": "pullback_macd",
        "setup_context": {"type": "pullback entry"},
        "decision_actionable": True,
        "decision_quality_status": "actionable",
    }
    ann = annotate_item(it)
    assert ann["lane"] == "main"
    assert ann["now_status"] == "GO"
    assert ann["primary_cta"] == "Propose"


def test_operator_star_grants_main_wait():
    it = {
        "symbol": "STAR",
        "source": "ai_discovered",
        "starred": True,
        "setup_context": {"type": "trend continuation"},
        "decision_actionable": False,
    }
    ann = annotate_item(it)
    assert ann["lane"] == "main"
    assert ann["now_status"] in ("WAIT", "GO")


def test_setup_shaped_helpers():
    assert is_setup_shaped({"setup_context": {"type": "trend continuation"}})
    assert is_setup_shaped({"entry_setup": "pullback"})
    assert not is_setup_shaped({"setup_context": {"type": "no-trade (downtrend)"}})


def test_quality_board_counts():
    items = [
        {"symbol": "A", "source": "pullback_macd", "setup_context": {"type": "pullback entry"}, "decision_actionable": True},
        {"symbol": "B", "source": "ai_discovered", "setup_context": {"type": "no-trade (downtrend)"}},
        {"symbol": "C", "source": "analyst_signal"},
    ]
    board = quality_board_from_items(items)
    assert board["sample_n"] == 3
    assert board["by_lane"].get("main", 0) >= 1
    assert board["by_lane"].get("research", 0) >= 1
    assert board["by_lane"].get("coverage", 0) >= 1
