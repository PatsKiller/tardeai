#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import broker_strategy_resolver as bsr


def test_resolve_ms_from_sleeve_maps_to_classification_or_core():
    r = bsr.resolve_executable_strategy("MS", "core_holding")
    assert r["strategy_id"] in ("core_growth_compounder", "swing_breakout", "momentum_scalp")
    assert r["watchlist_sleeve"] == "core_holding"


def test_apply_strategy_exit_plan_uses_target_rr():
    en, st, tg, rat = bsr.apply_strategy_exit_plan(100.0, None, None, "core_growth_compounder")
    assert st < en < tg
    assert rat.get("target_rr_policy") == 3.0
    assert rat.get("sources")


def test_is_watchlist_sleeve():
    assert bsr.is_watchlist_sleeve("income")
    assert not bsr.is_watchlist_sleeve("momentum_scalp")


def test_defense_thesis_sleeve_maps_to_executable_strategy():
    r = bsr.resolve_executable_strategy("LDOS", "defense_thesis")
    assert r["strategy_id"] == "swing_breakout"
    assert r["watchlist_sleeve"] == "defense_thesis"
    assert r["resolve_source"] == "sleeve_map"


def test_policy_floor_raises_target_when_resistance_too_close():
    en, st, tg, rat = bsr.apply_strategy_exit_plan(
        220.3, None, None, "core_growth_compounder",
        support=209.28, resistance=231.32,
    )
    rr = round((tg - en) / (en - st), 2)
    assert rr >= 3.0
    assert any("policy floor" in s for s in rat.get("sources") or [])
    assert any("support" in s for s in rat.get("sources") or [])