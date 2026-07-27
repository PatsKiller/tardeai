#!/usr/bin/env python3
"""M3-S6 unit tests — T1 microstructure metrics (hand-computed) + the entitlement gate.

The gate tests are load-bearing: they prove T1 metrics CANNOT be computed on IEX-only / delayed /
unentitled data (only real-time consolidated SIP), and are OFF by config until a feed is procured."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "market_observations"))

import scalp_t1_metrics as t1                                    # noqa: E402
import scalp_t1_gate as gate                                     # noqa: E402
from scalp_t1_gate import T1NotEntitled, compute_t1_snapshot, require_consolidated_realtime, t1_ready  # noqa: E402
from observation import EntitlementState as ES                   # noqa: E402


def trade(price, size, ts): return {"price": price, "size": size, "ts": ts}
def quote(bid, ask, ts): return {"bid": bid, "ask": ask, "ts": ts}


# ── Lee-Ready / TFI ─────────────────────────────────────────────────
def test_lee_ready_above_below_mid():
    assert t1.lee_ready_sign(100.1, 100.0) == 1
    assert t1.lee_ready_sign(99.9, 100.0) == -1

def test_lee_ready_at_mid_tick_test():
    assert t1.lee_ready_sign(100.0, 100.0, last_diff_price=99.5) == 1   # uptick from last
    assert t1.lee_ready_sign(100.0, 100.0, last_diff_price=100.5) == -1  # downtick
    assert t1.lee_ready_sign(100.0, 100.0, last_diff_price=None) == 0

def test_sign_trades_and_tfi_hand_computed():
    quotes = [quote(99.9, 100.1, ts=0)]          # mid 100
    trades = [trade(100.1, 300, 1), trade(99.9, 100, 2)]   # buy 300, sell 100
    signed = t1.sign_trades(trades, quotes)
    assert [s["side"] for s in signed] == [1, -1]
    assert t1.trade_flow_imbalance(signed) == pytest.approx((300 - 100) / 400)  # 0.5

def test_tfi_balanced_is_zero():
    quotes = [quote(99.9, 100.1, 0)]
    signed = t1.sign_trades([trade(100.1, 100, 1), trade(99.9, 100, 2)], quotes)
    assert t1.trade_flow_imbalance(signed) == pytest.approx(0.0)

def test_tfi_none_when_no_signed_volume():
    quotes = [quote(99.9, 100.1, 0)]
    signed = t1.sign_trades([trade(100.0, 100, 1)], quotes)   # at mid, no tick ref → side 0
    assert t1.trade_flow_imbalance(signed) is None


# ── effective spread ────────────────────────────────────────────────
def test_effective_spread_bps_hand_computed():
    quotes = [quote(99.9, 100.1, 0)]             # mid 100
    trades = [trade(100.1, 100, 1)]              # |100.1-100|/100 = 0.001 → 1e4*2*0.001 = 20 bps
    assert t1.effective_spread_bps(trades, quotes) == pytest.approx(20.0)

def test_effective_spread_volume_weighted():
    quotes = [quote(99.9, 100.1, 0)]
    trades = [trade(100.1, 300, 1), trade(100.05, 100, 2)]  # 20bps@300, 10bps@100 → (20*300+10*100)/400
    assert t1.effective_spread_bps(trades, quotes) == pytest.approx((20 * 300 + 10 * 100) / 400)


# ── Kyle lambda ─────────────────────────────────────────────────────
def test_kyle_lambda_perfect_line():
    bars = [{"close": 100.0, "signed_dollar_vol": None},
            {"close": 101.0, "signed_dollar_vol": 1000.0},
            {"close": 103.0, "signed_dollar_vol": 2000.0}]   # ΔP 1@1000, 2@2000 → slope 0.001
    assert t1.kyle_lambda(bars) == pytest.approx(0.001, abs=1e-9)

def test_kyle_lambda_none_too_few():
    assert t1.kyle_lambda([{"close": 100, "signed_dollar_vol": 10}]) is None


# ── VPIN ────────────────────────────────────────────────────────────
def test_vpin_hand_computed():
    quotes = [quote(99.9, 100.1, 0)]
    signed = t1.sign_trades([trade(100.1, 50, 1), trade(99.9, 50, 2), trade(100.1, 100, 3)], quotes)
    # bucket 100: b1={buy50,sell50}→|0|/100=0 ; b2={buy100}→100/100=1 ; VPIN=(0+1)/2=0.5
    assert t1.vpin(signed, bucket_volume=100) == pytest.approx(0.5)

def test_vpin_none_on_bad_bucket():
    assert t1.vpin([], bucket_volume=0) is None


# ── ENTITLEMENT GATE (load-bearing) ─────────────────────────────────
def test_require_consolidated_realtime_only_sip():
    require_consolidated_realtime(ES.SIP_REALTIME)               # ok
    for bad in (ES.IEX_ONLY, ES.SIP_DELAYED, ES.AVAILABLE_DELAYED, ES.AVAILABLE_HISTORICAL,
                ES.SCAFFOLD_ONLY, ES.UNAVAILABLE, ES.UNRESOLVED, ES.AVAILABLE_REALTIME):
        with pytest.raises(T1NotEntitled):
            require_consolidated_realtime(bad)

def test_t1_ready_needs_flag_and_entitlement():
    assert t1_ready({"t1": {"enabled": False}}, ES.SIP_REALTIME) == (False, "t1.enabled=false")
    ok, why = t1_ready({"t1": {"enabled": True}}, ES.IEX_ONLY)
    assert ok is False and "IEX_ONLY" in why
    assert t1_ready({"t1": {"enabled": True}}, ES.SIP_REALTIME)[0] is True

def _cfg(enabled=True): return {"t1": {"enabled": enabled, "vpin_bucket_volume": 100, "vpin_buckets": 50}}
_Q = [quote(99.9, 100.1, 0)]
_T = [trade(100.1, 100, 1), trade(99.9, 100, 2)]
_B = [{"close": 100, "signed_dollar_vol": None}, {"close": 101, "signed_dollar_vol": 1000}]

def test_gate_refuses_when_flag_off():
    with pytest.raises(T1NotEntitled):
        compute_t1_snapshot(trades=_T, quotes=_Q, bars=_B, entitlement=ES.SIP_REALTIME, cfg=_cfg(False))

def test_gate_refuses_iex_only_even_with_flag_on():
    # THE load-bearing case: cannot compute T1 on IEX-only data
    with pytest.raises(T1NotEntitled):
        compute_t1_snapshot(trades=_T, quotes=_Q, bars=_B, entitlement=ES.IEX_ONLY, cfg=_cfg(True))

def test_gate_allows_only_sip_realtime():
    snap = compute_t1_snapshot(trades=_T, quotes=_Q, bars=_B, entitlement=ES.SIP_REALTIME, cfg=_cfg(True))
    assert snap["data_tier"] == "T1" and snap["entitlement"] == "SIP_REALTIME"
    assert snap["tfi"] == pytest.approx(0.0) and snap["effective_spread_bps"] is not None

def test_capability_resolution_keeps_gate_closed_today():
    # every candidate consolidated source is currently NOT SIP_REALTIME → gate stays shut
    assert gate.resolve_t1_entitlement_from_capability("polygon") != ES.SIP_REALTIME
    assert gate.resolve_t1_entitlement_from_capability("alpaca") == ES.IEX_ONLY


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
