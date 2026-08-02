"""Defense → MAIN promote policy unit checks (no DB)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.defense_main_promote import (
    extract_destination_symbols,
    is_soft_auto_symbol,
    load_promote_policy,
    soft_auto_candidates,
)
from lib.watch_lane_admission import classify_lane, now_status


def test_schd_is_soft_auto():
    p = load_promote_policy()
    assert "SCHD" in p["soft_auto_symbols"]
    assert is_soft_auto_symbol("SCHD", p)


def test_xlk_not_soft_when_lean_on():
    p = load_promote_policy()
    # Cyclical XLK should not be soft-auto while lean excludes Technology
    assert "XLK" not in p["soft_auto_symbols"] or "XLK" in p["click_only_symbols"]
    assert not is_soft_auto_symbol("XLK", p)


def test_soft_candidates_filter():
    cards = [
        {"group": "get_into", "etf": "SCHD"},
        {"group": "get_into", "etf": "XLK"},
        {"group": "protect", "etf": "XLU"},
    ]
    cands = soft_auto_candidates(cards)
    assert "SCHD" in cands
    assert "XLK" not in cands


def test_extract_destinations():
    syms = extract_destination_symbols([
        {"group": "get_into", "etf": "XLU"},
        {"group": "income", "symbol": "SCHD"},
    ])
    assert "XLU" in syms and "SCHD" in syms


def test_defense_promoted_lands_main_wait():
    item = {
        "symbol": "SCHD",
        "source": "operator",
        "origin_system": "defense_rotation",
        "notes": "[defense_main_promote soft]",
    }
    assert classify_lane(item) == "main"
    item["lane"] = "main"
    assert now_status(item) == "WAIT"
