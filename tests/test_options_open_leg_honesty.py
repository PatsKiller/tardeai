#!/usr/bin/env python3
"""Stage 1B — open-leg P&L honesty, action criteria, margin UNKNOWN (no invented dollars).

    .venv/bin/python -m pytest tests/test_options_open_leg_honesty.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import options_engine as oe  # noqa: E402


def _pos(**kw):
    base = {
        "underlying": "V",
        "strike": 380.0,
        "dte": 21,
        "option_type": "call",
        "side": "short",
        "qty": 1,
        "avg_entry": 4.50,
        "occ_symbol": "V  251017C00380000",
        "account_key": "schwab_roth",
    }
    base.update(kw)
    return base


def test_pnl_unknown_missing_entry(monkeypatch):
    monkeypatch.setattr(oe, "_schwab_chain", lambda *a, **k: {"underlying_price": 365.0})
    monkeypatch.setattr(
        oe,
        "_pick_chain_contract",
        lambda *a, **k: {"mid": 2.0, "iv": 0.2, "delta": -0.25},
    )
    out = oe._monitor_position(_pos(avg_entry=0), {"V": {"price": 365.0}})
    assert out["pnl_status"] == "PNL_UNKNOWN"
    assert "avg_entry" in (out.get("pnl_unknown_reason") or "")
    assert out["unrealized_pnl"] is None
    assert out["margin_status"] == "MARGIN_UNKNOWN"
    assert out["margin_usd"] is None


def test_pnl_unknown_no_chain_mark(monkeypatch):
    monkeypatch.setattr(oe, "_schwab_chain", lambda *a, **k: {"underlying_price": 365.0})
    monkeypatch.setattr(oe, "_pick_chain_contract", lambda *a, **k: None)
    out = oe._monitor_position(_pos(), {"V": {"price": 365.0}})
    assert out["pnl_status"] == "PNL_UNKNOWN"
    assert "chain mark" in (out.get("pnl_unknown_reason") or "")
    assert out["margin_status"] == "MARGIN_UNKNOWN"


def test_close_profit_criterion_string(monkeypatch):
    """Short OTM + high POP + positive unrealized → Close for Profit + criterion."""
    monkeypatch.setattr(oe, "_schwab_chain", lambda *a, **k: {"underlying_price": 350.0})
    monkeypatch.setattr(
        oe,
        "_pick_chain_contract",
        lambda *a, **k: {"mid": 1.00, "iv": 0.18, "delta": -0.15},
    )
    # entry 4.50 mark 1.00 → short unrealized = (4.50-1)*100 = 350
    out = oe._monitor_position(_pos(strike=380.0, dte=30), {"V": {"price": 350.0, "iv": 18}})
    assert out["recommended_action"] == "Close for Profit"
    assert out["action"] == "close_profit"
    assert "POP OTM" in (out.get("action_criterion") or "")
    assert out["pnl_status"] == "OK"
    assert out["unrealized_pnl"] is not None and out["unrealized_pnl"] > 0
    assert out["entry_credit_debit"] == 450.0  # short credit
    assert out["margin_status"] == "MARGIN_UNKNOWN"


def test_margin_ok_only_when_schwab_field_present(monkeypatch):
    monkeypatch.setattr(oe, "_schwab_chain", lambda *a, **k: {"underlying_price": 365.0})
    monkeypatch.setattr(
        oe,
        "_pick_chain_contract",
        lambda *a, **k: {"mid": 2.0, "iv": 0.2, "delta": -0.2},
    )
    out = oe._monitor_position(
        _pos(buying_power_effect=-1200.5),
        {"V": {"price": 365.0}},
    )
    assert out["margin_status"] == "OK"
    assert out["margin_usd"] == -1200.5
    assert out["margin_field"] == "buying_power_effect"


def test_schwab_margin_stamp_never_invents():
    stamp = oe._schwab_margin_stamp({"symbol": "V"})
    assert stamp["margin_status"] == "MARGIN_UNKNOWN"
    assert stamp["margin_usd"] is None
