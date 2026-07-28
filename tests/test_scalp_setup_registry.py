#!/usr/bin/env python3
"""Scalp setup registry — the canonical taxonomy contract. A lane is NOT a setup; the 7 named setups
are versioned, deterministic, and start SHADOW; primary selection is deterministic; the hash is stable."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_setup_registry as reg  # noqa: E402


def test_loads_and_has_all_canonical_setups():
    r = reg.load_registry()
    ids = {s["setup_id"] for s in r["setups"]}
    assert set(reg.CANONICAL_SETUP_IDS) <= ids
    assert len(r["setups"]) == len(reg.CANONICAL_SETUP_IDS)


def test_all_setups_start_shadow_and_are_versioned_deterministic():
    for s in reg.list_setups():
        assert s["operating_state"] in reg.VALID_OPERATING_STATES
        assert s["operating_state"] == "SHADOW", f"{s['setup_id']} must start SHADOW"
        assert str(s["version"]) == "1"


def test_lane_is_not_a_setup():
    ids = set(reg.CANONICAL_SETUP_IDS)
    for lane in ("IGN_45", "IGN_60", "IGN_75", "IGN_ACCEL", "TRIGGER", "BELOW"):
        assert lane not in ids


def test_vwap_pullback_and_reversion_are_distinct():
    pb = reg.get_setup("SCALP_VWAP_PULLBACK_V1")
    rev = reg.get_setup("SCALP_VWAP_REVERSION_V1")
    assert pb["display_label"] == "VWAP PULLBACK" and rev["display_label"] == "VWAP REVERSION"
    assert pb["family"] != rev["family"]                 # continuation vs mean reversion
    assert "continuation" in pb["source_rule_notes"].lower() or "continuation" in pb["entry_rule"].lower()
    assert "reversion" in rev["entry_rule"].lower() or "mean reversion" in rev["source_rule_notes"].lower()


def test_l2_momentum_requires_book_tier():
    assert reg.get_setup("SCALP_L2_MOMENTUM_V1")["required_data_tier"] == "T2"


def test_orb_window_is_regular_0945_1030():
    assert reg.get_setup("SCALP_ORB_15_BREAKOUT_V1")["active_window_et"] == "09:45-10:30"


def test_premarket_is_engine_adaptation_ignition_is_existing_rule():
    assert reg.get_setup("SCALP_PREMARKET_MOMENTUM_V1")["rule_provenance"] == "ENGINE_ADAPTATION"
    assert reg.get_setup("SCALP_IGNITION_BREAKOUT_V1")["rule_provenance"] == "EXISTING_ENGINE_RULE"
    assert reg.get_setup("SCALP_L2_MOMENTUM_V1")["rule_provenance"] == "SOURCE_DERIVED"


def test_registry_hash_stable_and_content_sensitive():
    r = reg.load_registry()
    assert reg.registry_hash(r) == reg.registry_hash(r)          # stable
    mutated = {**r, "setups": r["setups"][:-1]}
    assert reg.registry_hash(mutated) != reg.registry_hash(r)    # content-sensitive


def test_primary_selection_tier_then_criteria_then_family_then_id():
    r = reg.load_registry()
    # T2 (L2 MOMENTUM) beats T0 even with fewer mandatory satisfied
    m = [{"setup_id": "SCALP_IGNITION_BREAKOUT_V1", "mandatory_satisfied": 9},
         {"setup_id": "SCALP_L2_MOMENTUM_V1", "mandatory_satisfied": 1}]
    assert reg.select_primary(m, r) == "SCALP_L2_MOMENTUM_V1"
    # same tier → more mandatory criteria wins
    m2 = [{"setup_id": "SCALP_VWAP_PULLBACK_V1", "mandatory_satisfied": 2},
          {"setup_id": "SCALP_MICRO_PULLBACK_V1", "mandatory_satisfied": 5}]
    assert reg.select_primary(m2, r) == "SCALP_MICRO_PULLBACK_V1"
    # same tier + same criteria → family specificity rank (ORB 60 > MICRO 45)
    m3 = [{"setup_id": "SCALP_ORB_15_BREAKOUT_V1", "mandatory_satisfied": 3},
          {"setup_id": "SCALP_MICRO_PULLBACK_V1", "mandatory_satisfied": 3}]
    assert reg.select_primary(m3, r) == "SCALP_ORB_15_BREAKOUT_V1"
    assert reg.select_primary([], r) is None


def test_primary_selection_is_deterministic_regardless_of_input_order():
    r = reg.load_registry()
    a = [{"setup_id": "SCALP_MICRO_PULLBACK_V1", "mandatory_satisfied": 3},
         {"setup_id": "SCALP_ORB_15_BREAKOUT_V1", "mandatory_satisfied": 3}]
    assert reg.select_primary(a, r) == reg.select_primary(list(reversed(a)), r)


def _write(tmp_path, data):
    import yaml
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_schema_validation_fail_closed(tmp_path):
    good = reg.load_registry()
    # missing required field on a setup
    bad1 = {**good, "setups": [{k: v for k, v in good["setups"][0].items() if k != "entry_rule"}, *good["setups"][1:]]}
    with pytest.raises(reg.SetupRegistryError):
        reg.load_registry(_write(tmp_path, bad1))
    # bad operating_state
    s = dict(good["setups"][0]); s["operating_state"] = "AUTO_PAPER"
    with pytest.raises(reg.SetupRegistryError):
        reg.load_registry(_write(tmp_path, {**good, "setups": [s, *good["setups"][1:]]}))
    # missing a canonical setup (drop one)
    with pytest.raises(reg.SetupRegistryError):
        reg.load_registry(_write(tmp_path, {**good, "setups": good["setups"][:-1]}))
    # duplicate setup_id
    with pytest.raises(reg.SetupRegistryError):
        reg.load_registry(_write(tmp_path, {**good, "setups": [good["setups"][0], *good["setups"]]}))


def test_no_auto_paper_operating_state_anywhere():
    assert "AUTO_PAPER" not in reg.VALID_OPERATING_STATES
    for s in reg.list_setups():
        assert "AUTO_PAPER" not in str(s.get("operating_state"))


def test_public_view_is_read_only_no_write_authority():
    v = reg.public_view()
    assert v["read_only"] is True and v["write_authority"] is False
    assert v["registry_hash"].startswith("sha256:")
    assert len(v["setups"]) == len(reg.CANONICAL_SETUP_IDS)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
