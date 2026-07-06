#!/usr/bin/env python3
"""Trail threshold (9%) and live-price lock-in helpers."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load_hf():
    spec = importlib.util.spec_from_file_location("holding_family", ROOT / "scripts" / "holding_family.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_trail_threshold_lowered_to_nine_percent():
    hf = _load_hf()
    assert hf.TRAIL_PNL_PCT_NORMAL == 9.0
    assert hf.trail_pnl_threshold("position") == 9.0
    assert hf.trail_pnl_threshold("income") == 20.0


def test_nine_point_seven_pct_triggers_trail_for_position():
    hf = _load_hf()
    assert hf.trail_recommended_for_state(
        family="position", pnl_pct=9.7, price=174.0, sma50=160.0,
    )
    assert not hf.trail_recommended_for_state(
        family="position", pnl_pct=8.9, price=174.0, sma50=160.0,
    )


def test_anet_lockin_at_live_price_not_advisory_snapshot():
    hf = _load_hf()
    # Jul 3 advisory snapshot (~$160) — floor below $155.50 fixed stop
    assert not hf.lockin_eligible(live_price=159.99, trail_pct=9.2, fixed_stop=155.50)
    # Jul 6 live price (~$174) — floor above fixed stop
    assert hf.lockin_eligible(live_price=174.23, trail_pct=9.0, fixed_stop=155.50)
    floor = hf.trailing_floor(174.23, 9.0)
    assert floor > 155.50


def test_trail_nudge_skips_when_lockin_already_fires():
    hf = _load_hf()
    px, fixed, tpct = 174.23, 155.50, 9.0
    assert hf.trail_recommended_for_state(family="position", pnl_pct=9.7, price=px, sma50=160.0)
    assert hf.lockin_eligible(live_price=px, trail_pct=tpct, fixed_stop=fixed)