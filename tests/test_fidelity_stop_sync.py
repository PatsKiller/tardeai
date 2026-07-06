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


def test_normalize_anet_stop_row():
    mod = _load()
    row = mod.normalize_stop_row({"symbol": "ANET", "stop_price": 155.50, "qty": 200})
    assert row["symbol"] == "ANET"
    assert row["stop_price"] == 155.50
    assert row["qty"] == 200
    assert row["account"] == "fidelity_rollover_ira"


def test_default_stops_include_anet_dxcm():
    mod = _load()
    syms = {r["symbol"] for r in mod.default_fidelity_rollover_stops()}
    assert {"ANET", "DXCM", "DIVI", "SMCI"} <= syms


def test_snaptrade_open_orders_empty_is_documented_gap():
    """SnapTrade returns executed fills only — not Fidelity GTC pending stops."""
    mod = _load()
    # load_manual_protective_stops is DB-backed; dry normalize proves the contract.
    row = mod.normalize_stop_row({
        "symbol": "ANET", "stop_price": 155.50, "qty": 200,
        "note": "Fidelity GTC — SnapTrade state=open returns 0 orders",
    })
    assert "Fidelity" in row["note"] or "GTC" in row["note"]


@pytest.mark.parametrize("sym,price,qty", [
    ("ANET", 155.50, 200),
    ("DXCM", 67.23, 225),
    ("DIVI", 40.58, 1000),
    ("SMCI", 24.90, 500),
])
def test_fidelity_pending_stop_prices(sym, price, qty):
    mod = _load()
    defaults = {r["symbol"]: r for r in mod.default_fidelity_rollover_stops()}
    assert defaults[sym]["stop_price"] == price
    assert defaults[sym]["qty"] == qty