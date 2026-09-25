#!/usr/bin/env python3
"""Stage 1E — entry_state BUY_READY / ENTRY_NEAR → Hub Ideas Directional (long_call).

No IV/intent widen. No auto-trade. Owned≥100 exempt only when source=entry_state.

    .venv/bin/python -m pytest tests/test_options_directional_hub_1e_20260924.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import options_engine as oe  # noqa: E402
from scripts.lib import cio_options_fluency as flu  # noqa: E402


def _entry_conviction(sym: str, *, state: str = "BUY_READY", atr: float = 4.0,
                      price: float = 100.0, stop: float = 90.0, target: float = 130.0,
                      entry_low: float = 95.0, entry_high: float = 102.0,
                      vol_elevated: bool | None = None) -> dict:
    if vol_elevated is None:
        vol_elevated, atr_vs, _ = flu.atr_volatility_elevated(
            price=price, stop=stop, atr=atr,
        )
    else:
        atr_vs = round(atr / (price - stop), 2) if price > stop else None
    return {
        "symbol": sym,
        "source": "entry_state",
        "confidence": 0.62,
        "bias": "bullish",
        "direction": "bullish",
        "entry_state": state,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "target": target,
        "atr": atr,
        "price": price,
        "volatility_elevated": bool(vol_elevated),
        "atr_vs_distance_to_stop": atr_vs,
        "summary": f"{state} entry zone",
    }


def _good_call_contract(und: float = 100.0) -> dict:
    return {
        "strike": round(und * 1.04 / 2.5) * 2.5,
        "dte": 35,
        "mid": 3.50,
        "iv": 0.28,
        "delta": 0.45,
        "exp": "2026-10-31",
    }


def _stub_resolve(monkeypatch, contract=None, missing: bool = False):
    def _resolve(sym, und, tech, side, target_strike, target_dte, strikes=10):
        if missing:
            return None, ""
        c = contract or _good_call_contract(und)
        return dict(c), "bs_estimate"

    monkeypatch.setattr(oe, "_resolve_option_contract", _resolve)
    monkeypatch.setattr(oe, "_iv_rank_proxy", lambda sym, tech, chain_iv=None: 35.0)
    monkeypatch.setattr(
        oe, "_auto_select_account",
        lambda *a, **k: "schwab_roth",
    )
    monkeypatch.setattr(oe, "_stamp_execution", lambda p, account="", holdings=None: p)
    monkeypatch.setattr(oe, "_execution_note", lambda extra="": "advisory · Path B 2FA")
    # Deterministic edge above MIN_EDGE_CONVICTION−3 so IV/ownership gates are the unit under test.
    monkeypatch.setattr(
        oe, "_edge_score_debit",
        lambda **kw: 70.0,
    )
    monkeypatch.setattr(oe, "_pop_otm_call", lambda *a, **k: 40.0)


def test_t1e1_buy_ready_not_owned_long_call_directional(monkeypatch):
    """T1E.1 — BUY_READY not owned · IV/edge pass → long_call · directional≥1 · entry_state."""
    _stub_resolve(monkeypatch)
    c = _entry_conviction("AXTI", state="BUY_READY", price=72.93, stop=58.50,
                          entry_low=62, entry_high=66, atr=6.0, target=96.50)
    drops: list = []
    props = oe.generate_defined_risk_proposals(
        [c], {"AXTI": {"price": 72.93, "iv": 35, "atr": 6.0}}, owned=set(),
        out_entry_drops=drops,
    )
    longs = [p for p in props if p.get("strategy") == "long_call"]
    assert longs, f"expected long_call, got {props!r} drops={drops}"
    assert longs[0]["conviction_source"] == "entry_state"
    assert longs[0]["entry_state"] == "BUY_READY"
    facets = oe.proposal_filter_facets(longs)
    assert facets["by_group"]["directional"] >= 1
    assert drops == []


def test_t1e2_buy_ready_owned_exempt_from_skip(monkeypatch):
    """T1E.2 — BUY_READY owned≥100 (V-shaped) → long_call not skipped solely for owned."""
    _stub_resolve(monkeypatch)
    c = _entry_conviction("V", state="BUY_READY", price=367.53, stop=357.50,
                          entry_low=364.5, entry_high=369, atr=4.0, target=410.0)
    owned = {"V"}
    # Non-entry conviction on owned must still be skipped:
    other = {
        "symbol": "V", "source": "layer4", "confidence": 0.70,
        "direction": "bullish", "summary": "layer4 bullish",
    }
    drops: list = []
    props_entry = oe.generate_defined_risk_proposals(
        [c], {"V": {"price": 367.53, "iv": 30, "atr": 4.0}}, owned=owned,
        out_entry_drops=drops,
    )
    props_other = oe.generate_defined_risk_proposals(
        [other], {"V": {"price": 367.53, "iv": 30}}, owned=owned,
    )
    assert any(p.get("strategy") == "long_call" for p in props_entry)
    assert props_entry[0].get("conviction_source") == "entry_state"
    assert not any(p.get("strategy") == "long_call" for p in props_other)
    # Owned entry must not open CSP on this path
    assert not any(p.get("strategy") == "cash_secured_put" for p in props_entry)


def test_t1e3_entry_near_elevated_atr_stamped(monkeypatch):
    """T1E.3 — ENTRY_NEAR + atr/(px−stop)≥0.40 → volatility_elevated + reasoning cites preference."""
    _stub_resolve(monkeypatch)
    # atr 8 / (72.93−58.50) ≈ 0.55 ≥ 0.40
    c = _entry_conviction(
        "AXTI", state="ENTRY_NEAR", price=72.93, stop=58.50,
        entry_low=62, entry_high=66, atr=8.0, target=96.50,
    )
    assert c["volatility_elevated"] is True
    props = oe.generate_defined_risk_proposals(
        [c], {"AXTI": {"price": 72.93, "iv": 35, "atr": 8.0}}, owned=set(),
    )
    assert props and props[0]["volatility_elevated"] is True
    reason = (props[0].get("reasoning") or "").lower()
    assert "elevated" in reason or "atr" in reason
    assert "options" in reason or "defined-risk" in reason or "defined risk" in reason


def test_t1e4_iv_below_named_drop(monkeypatch):
    """T1E.4 — Entry symbol IV below floor → no long_call · named IV_BELOW drop (not silent)."""
    _stub_resolve(monkeypatch)
    monkeypatch.setattr(oe, "_iv_rank_proxy", lambda sym, tech, chain_iv=None: 5.0)  # < MIN_IV_CONVICTION 12
    c = _entry_conviction("ZZZ", state="BUY_READY", price=50.0, stop=45.0, atr=1.0)
    drops: list = []
    props = oe.generate_defined_risk_proposals(
        [c], {"ZZZ": {"price": 50.0, "iv": 5}}, owned=set(), out_entry_drops=drops,
    )
    assert not any(p.get("strategy") == "long_call" for p in props)
    assert drops and drops[0]["reason"] == "IV_BELOW"
    assert drops[0]["symbol"] == "ZZZ"


def test_t1e5_packet_ok_when_long_call_on_cache():
    """T1E.5 — After cache has long_call, select_entry_options_alternative → OPTIONS_ALT_OK."""
    desk = {
        "by_symbol": {
            "V": [
                {"strategy": "covered_call", "strike": 385, "edge_score": 64,
                 "premium_total": 219, "iv_rank": 24.6},
                {"strategy": "long_call", "strike": 370, "edge_score": 70,
                 "premium_total": 850, "pop_pct": 55, "iv_rank": 30, "delta": 0.45,
                 "conviction_source": "entry_state", "entry_state": "BUY_READY"},
            ],
        },
    }
    alt = flu.select_entry_options_alternative(
        "V", entry_low=364.5, entry_high=369, stop=357.5, target=410, atr=4.0,
        desk=desk, goals=[],
    )
    assert alt["status"] == "OPTIONS_ALT_OK"
    assert alt["strategy"] == "long_call"
    assert alt["reason"] is None


def test_t1e6_regression_floors_and_advisory_only():
    """T1E.6 — IV floors / intent / Path B chrome / MBI advisory unchanged; no order language."""
    assert oe.MIN_IV_CONVICTION == 12
    assert oe.MIN_IV_RANK == 20
    assert oe.MIN_EDGE_SCORE == 62
    assert oe.MIN_EDGE_CC_INTENT == 52
    assert flu.ATR_VS_STOP_ELEVATED == 0.40
    # Shared ATR helper — structure and 1E must not fork
    elev, ratio, _ = flu.atr_volatility_elevated(price=72.93, stop=58.50, atr=8.0)
    assert elev is True and ratio is not None and ratio >= 0.40
    # Runner / fluency must stay advisory — no place_order / broker write in 1E surface
    src = Path(oe.__file__).read_text(encoding="utf-8", errors="replace")
    assert "place_order" not in src
    # Conviction bias honors explicit bias=bullish (entry_state rows)
    assert oe._conviction_bias({"bias": "bullish"}) == "bullish"
    # Slot allocator prefers entry_state long_calls inside the cap (final list may
    # still sort by edge — assert membership under contested slots).
    picked = oe._allocate_strategy_slots([
        {"strategy": "long_call", "symbol": "AAA", "strike": 10, "account": "a",
         "edge_score": 80, "conviction_source": "layer4"},
        {"strategy": "long_call", "symbol": "V", "strike": 370, "account": "a",
         "edge_score": 60, "conviction_source": "entry_state"},
        {"strategy": "long_call", "symbol": "BBB", "strike": 20, "account": "a",
         "edge_score": 75},  # would beat V on edge alone, but entry wins the reserved pick
    ])
    long_syms = [p["symbol"] for p in picked if p["strategy"] == "long_call"]
    assert "V" in long_syms  # entry_state kept despite lower edge
    assert "BBB" not in long_syms  # squeezed out by entry preference + slot cap 2
    assert "AAA" in long_syms
