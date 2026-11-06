#!/usr/bin/env python3
"""Fidelity GTC stop sync — manual_broker_stops pipeline tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "fidelity_stop_sync",
        ROOT / "scripts" / "lib" / "fidelity_stop_sync.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    # Parse/default behaviour is tested against a fixed copy of the July registry,
    # not the live config the operator edits (it was emptied 2026-10-03).
    mod.FIDELITY_STOPS_CONFIG = ROOT / "tests" / "fixtures" / "fidelity_rollover_stops_20260713.json"
    return mod


def test_normalize_zqbu_trailing_stop_row():
    mod = _load()
    row = mod.normalize_stop_row({
        "symbol": "ZQBU", "order_type": "TRAILING_STOP",
        "stop_price": 142.84, "trail_pct": 5, "trail_link": "LAST", "qty": 150,
    })
    assert row["symbol"] == "ZQBU"
    assert row["order_type"] == "TRAILING_STOP"
    assert row["stop_price"] == 142.84
    assert row["trail_pct"] == 5
    assert row["trail_link"] == "LAST"
    assert row["qty"] == 150
    assert row["account"] == "fidelity_rollover_ira"


def test_load_fidelity_stops_config_json():
    mod = _load()
    rows = mod.load_fidelity_stops_config()
    assert len(rows) == 7
    assert {r["symbol"] for r in rows} == {
        "ZQAE", "ZQBX", "ZQAV", "ZQAQ", "ZQBU", "ZQCD", "ZQAM",
    }


def test_default_stops_include_rollover_open_gtc():
    mod = _load()
    syms = {r["symbol"] for r in mod.default_fidelity_rollover_stops()}
    assert {"ZQAE", "ZQBX", "ZQAV", "ZQAQ", "ZQBU", "ZQCD", "ZQAM"} == syms


def test_snaptrade_open_orders_empty_is_documented_gap():
    """SnapTrade returns executed fills only — not Fidelity GTC pending stops."""
    mod = _load()
    row = mod.normalize_stop_row({
        "symbol": "ZQBU", "stop_price": 142.84, "trail_pct": 5, "qty": 150,
        "note": "Fidelity GTC — SnapTrade state=open returns 0 orders",
    })
    assert "Fidelity" in row["note"] or "GTC" in row["note"]


def test_zqbu_default_is_trailing_five_pct():
    mod = _load()
    defaults = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}
    zqbu = defaults["ZQBU"]
    assert zqbu["order_type"] == "TRAILING_STOP"
    assert zqbu["stop_price"] == 142.84
    assert zqbu["trail_pct"] == 5
    assert zqbu["qty"] == 150


def test_zqae_default_is_trailing_four_pct():
    mod = _load()
    zqae = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["ZQAE"]
    assert zqae["order_type"] == "TRAILING_STOP"
    assert zqae["stop_price"] == 146.6
    assert zqae["trail_pct"] == 4
    assert zqae["qty"] == 60


def test_zqav_default_is_trailing_six_pct():
    mod = _load()
    zqav = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["ZQAV"]
    assert zqav["order_type"] == "TRAILING_STOP"
    assert zqav["stop_price"] == 27.06
    assert zqav["trail_pct"] == 6
    assert zqav["qty"] == 4000


def test_zqbx_default_stop():
    mod = _load()
    zqbx = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["ZQBX"]
    assert zqbx["order_type"] == "STOP"
    assert zqbx["stop_price"] == 95.0
    assert zqbx["qty"] == 120


@pytest.mark.parametrize("sym,price,qty", [
    ("ZQAQ", 25.78, 800),
    ("ZQAM", 35.0, 800),
])
def test_fidelity_pending_stop_prices(sym, price, qty):
    mod = _load()
    defaults = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}
    assert defaults[sym]["stop_price"] == price
    assert defaults[sym]["qty"] == qty


def test_zqcd_default_is_trailing_six_pct():
    mod = _load()
    zqcd = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["ZQCD"]
    assert zqcd["order_type"] == "TRAILING_STOP"
    assert zqcd["stop_price"] == 59.62
    assert zqcd["trail_pct"] == 6
    assert zqcd["qty"] == 250