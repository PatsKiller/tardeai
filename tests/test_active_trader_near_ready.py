#!/usr/bin/env python3
"""Active Trader Stage 1b — near-ready candidate read model.

Product rules under test:
  - Near-ready = below the classic Trade AI GO bar (~5x RVOL / actionable GO) but showing
    building volume/momentum / pullback-break characteristics. Explicitly NOT a GO.
  - A candidate at/above the GO RVOL bar (or already actionable-GO) is EXCLUDED here.
  - Pure/deterministic scoring; a red-day pullback with constructive RSI still qualifies.
  - Endpoint is GET-only, read-only, list (empty OK); venue join adds prompt_required only.
  - `near_ready_desk` feature flag defaults OFF and gates operational promotion, not the read.
  - No write/canary/order/session authority anywhere.

Pure + read-only: no network, no DB, no order, no send.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import near_ready as nr  # noqa: E402
from active_trader.flags import HARD_OFF, load_flags  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI, near_ready_candidates  # noqa: E402
from active_trader.read_http import ACTIVE_TRADER_PREFIX, dispatch  # noqa: E402

NEAR = ACTIVE_TRADER_PREFIX + "/near-ready"


# ---- pure scoring ---------------------------------------------------------

def test_multi_signal_candidate_is_near_ready():
    row = nr.score_candidate(
        {"symbol": "crnt", "rvol": 2.8, "change_pct": 3.5, "rsi": 58, "entry_setup": "pullback"}
    )
    assert row["symbol"] == "CRNT"
    assert row["tier"] == nr.NEAR_READY
    assert row["score"] == 4
    assert all(row["signals"].values())
    assert row["is_trade_ai_go"] is False


def test_red_day_pullback_still_qualifies():
    # down on the day but a pullback setup with constructive RSI + building volume
    row = nr.score_candidate(
        {"symbol": "OSS", "rvol": 1.9, "change_pct": -2.1, "rsi": 51, "entry_setup": "pullback"}
    )
    assert row["tier"] == nr.NEAR_READY
    assert row["signals"]["momentum"] is False          # not an up-move
    assert row["signals"]["pullback_break"] is True
    assert row["signals"]["building_volume"] is True
    assert row["signals"]["constructive_rsi"] is True


def test_single_signal_is_watch_not_near_ready():
    row = nr.score_candidate(
        {"symbol": "MNOP", "rvol": 3.0, "change_pct": 0.2, "rsi": 30, "entry_setup": ""}
    )
    assert row["tier"] == nr.WATCH
    assert row["score"] == 1


def test_zero_signal_is_excluded():
    row = nr.score_candidate(
        {"symbol": "WXYZ", "rvol": 1.2, "change_pct": 0.5, "rsi": 41, "entry_setup": ""}
    )
    assert row["tier"] == nr.EXCLUDED
    assert row["score"] == 0


def test_go_level_rvol_is_excluded_not_near_ready():
    row = nr.score_candidate(
        {"symbol": "DFNS", "rvol": 120.8, "change_pct": 135.0, "rsi": 79, "entry_setup": "breakout"}
    )
    assert row["is_trade_ai_go"] is True
    assert row["tier"] == nr.EXCLUDED_ALREADY_GO


def test_actionable_go_flag_excludes_even_below_rvol_bar():
    row = nr.score_candidate(
        {"symbol": "XYZ", "rvol": 2.0, "change_pct": 3.0, "rsi": 60,
         "entry_setup": "pullback", "decision_actionable": True, "verdict": "GO"}
    )
    assert row["is_trade_ai_go"] is True
    assert row["tier"] == nr.EXCLUDED_ALREADY_GO


def test_partial_record_never_raises():
    row = nr.score_candidate({"symbol": "PARTIAL"})
    assert row["tier"] == nr.EXCLUDED
    assert row["score"] == 0


def test_select_returns_only_near_ready_sorted():
    cands = [
        {"symbol": "CRNT", "rvol": 2.8, "change_pct": 3.5, "rsi": 58, "entry_setup": "pullback"},
        {"symbol": "OSS", "rvol": 1.9, "change_pct": -2.1, "rsi": 51, "entry_setup": "pullback"},
        {"symbol": "MNOP", "rvol": 3.0, "change_pct": 0.2, "rsi": 30, "entry_setup": ""},
        {"symbol": "DFNS", "rvol": 120.8, "change_pct": 135.0, "rsi": 79, "entry_setup": "breakout"},
    ]
    out = nr.select_near_ready(cands)
    syms = [r["symbol"] for r in out]
    assert syms == ["CRNT", "OSS"]                 # watch + go excluded; higher score first
    assert out[0]["score"] >= out[1]["score"]


def test_include_watch_adds_single_signal_rows():
    cands = [
        {"symbol": "CRNT", "rvol": 2.8, "change_pct": 3.5, "rsi": 58, "entry_setup": "pullback"},
        {"symbol": "MNOP", "rvol": 3.0, "change_pct": 0.2, "rsi": 30, "entry_setup": ""},
    ]
    out = nr.select_near_ready(cands, include_watch=True)
    assert {r["symbol"] for r in out} == {"CRNT", "MNOP"}


def test_empty_input_is_empty_list():
    assert nr.select_near_ready([]) == []
    assert nr.select_near_ready(None) == []


# ---- venue-eligibility join (prompt_required only) ------------------------

def test_candidate_build_joins_venue_prompt_flag_only():
    built = near_ready_candidates(join_venue=True)
    assert built["source"] in ("fixtures", "empty")
    for row in built["candidates"]:
        assert "venue_prompt_required" in row
        assert isinstance(row["venue_prompt_required"], bool)
        assert row["venue_auto_route"] is False       # never auto-route


# ---- endpoint contract ----------------------------------------------------

def test_endpoint_lists_candidates_read_only():
    status, body = dispatch(None, "GET", NEAR)
    assert status == 200
    assert body["stage"] == 1 and body["sub_stage"] == "1b"
    assert body["write"] is False and body["canary"] is False
    assert body["read_only"] is True and body["auto_route"] is False
    assert body["count"] == len(body["candidates"])
    assert isinstance(body["candidates"], list)
    assert all(v is False for v in body["authority"].values())


def test_endpoint_desk_disabled_by_default():
    status, body = dispatch(None, "GET", NEAR)
    assert status == 200
    assert body["desk_enabled"] is False              # near_ready_desk defaults OFF


def test_endpoint_is_get_only():
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        status, body = dispatch(None, method, NEAR)
        assert status == 405
        assert body["write"] is False


def test_endpoint_include_watch_query():
    status, body = dispatch(None, "GET", NEAR, {"include_watch": "true"})
    assert status == 200
    tiers = {r["tier"] for r in body["candidates"]}
    assert tiers <= {nr.NEAR_READY, nr.WATCH}


def test_health_advertises_near_ready_endpoint():
    status, body = dispatch(None, "GET", ACTIVE_TRADER_PREFIX)
    assert status == 200
    assert any("near-ready" in e for e in body["endpoints"])


# ---- feature flag posture -------------------------------------------------

def test_near_ready_desk_flag_defaults_off():
    flags = load_flags()
    assert flags.flags.get("near_ready_desk", False) is False


def test_near_ready_desk_not_a_hard_off_flag():
    # it's a read-desk gate, not a write/canary switch — but must NOT be in HARD_OFF
    assert "near_ready_desk" not in HARD_OFF


def test_desk_enabled_true_when_flag_on_but_still_no_authority():
    base = load_flags()
    on = dataclasses.replace(base, flags={**base.flags, "near_ready_desk": True})
    api = ReadOnlyActiveTraderAPI(on)
    body = api.near_ready()
    assert body["desk_enabled"] is True
    assert body["write"] is False and body["canary"] is False
    assert all(v is False for v in body["authority"].values())


def test_stage0_safe_still_passes_with_read_desk():
    load_flags().assert_stage0_safe()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
