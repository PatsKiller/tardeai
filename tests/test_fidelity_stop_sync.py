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
    return mod


def test_normalize_anet_trailing_stop_row():
    mod = _load()
    row = mod.normalize_stop_row({
        "symbol": "ANET", "order_type": "TRAILING_STOP",
        "stop_price": 178.03, "trail_pct": 6, "trail_link": "LAST", "qty": 200,
    })
    assert row["symbol"] == "ANET"
    assert row["order_type"] == "TRAILING_STOP"
    assert row["stop_price"] == 178.03
    assert row["trail_pct"] == 6
    assert row["trail_link"] == "LAST"
    assert row["qty"] == 200
    assert row["account"] == "fidelity_rollover_ira"


def test_load_fidelity_stops_config_json():
    mod = _load()
    rows = mod.load_fidelity_stops_config()
    assert len(rows) == 8
    assert {r["symbol"] for r in rows} == {
        "QCOM", "CSCO", "SCHG", "ARKX", "XAR", "ANET", "DXCM", "DIVI",
    }


def test_default_stops_include_rollover_open_gtc():
    mod = _load()
    syms = {r["symbol"] for r in mod.default_fidelity_rollover_stops()}
    assert {"QCOM", "CSCO", "SCHG", "ARKX", "XAR", "ANET", "DXCM", "DIVI"} == syms


def test_snaptrade_open_orders_empty_is_documented_gap():
    """SnapTrade returns executed fills only — not Fidelity GTC pending stops."""
    mod = _load()
    row = mod.normalize_stop_row({
        "symbol": "ANET", "stop_price": 178.03, "trail_pct": 6, "qty": 200,
        "note": "Fidelity GTC — SnapTrade state=open returns 0 orders",
    })
    assert "Fidelity" in row["note"] or "GTC" in row["note"]


def test_anet_default_is_trailing_six_pct():
    mod = _load()
    defaults = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}
    anet = defaults["ANET"]
    assert anet["order_type"] == "TRAILING_STOP"
    assert anet["stop_price"] == 178.03
    assert anet["trail_pct"] == 6
    assert anet["qty"] == 200


def test_qcom_default_is_trailing_seven_pct():
    mod = _load()
    qcom = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["QCOM"]
    assert qcom["order_type"] == "TRAILING_STOP"
    assert qcom["stop_price"] == 174.79
    assert qcom["trail_pct"] == 7
    assert qcom["qty"] == 55


def test_schg_default_is_trailing_six_pct():
    mod = _load()
    schg = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["SCHG"]
    assert schg["order_type"] == "TRAILING_STOP"
    assert schg["stop_price"] == 32.6
    assert schg["trail_pct"] == 6
    assert schg["qty"] == 5000


def test_csco_default_stop():
    mod = _load()
    csco = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["CSCO"]
    assert csco["order_type"] == "STOP"
    assert csco["stop_price"] == 115.0
    assert csco["qty"] == 100


@pytest.mark.parametrize("sym,price,qty", [
    ("ARKX", 31.06, 1000),
    ("XAR", 263.03, 100),
    ("DIVI", 40.58, 1000),
])
def test_fidelity_pending_stop_prices(sym, price, qty):
    mod = _load()
    defaults = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}
    assert defaults[sym]["stop_price"] == price
    assert defaults[sym]["qty"] == qty


def test_dxcm_default_is_trailing_six_pct():
    mod = _load()
    dxcm = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}["DXCM"]
    assert dxcm["order_type"] == "TRAILING_STOP"
    assert dxcm["stop_price"] == 71.06
    assert dxcm["trail_pct"] == 6
    assert dxcm["qty"] == 225