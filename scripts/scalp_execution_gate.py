#!/usr/bin/env python3
"""Momentum-scalp UNIVERSAL EXECUTION-QUALITY GATE (Layer C) — deterministic, pure, SHADOW.

Applied to EVERY named setup; it can VETO any of them. Bullish Bears' liquidity/spread/slippage material
is INPUT here, never a setup. Checks: freshness, minimum tradable volume, minimum dollar-volume rate,
maximum spread (bps), maximum expected slippage (bps), participation limit, halt state, data entitlement,
limit-price feasibility. NEVER auto-uses a market order — it reports the intended price control and the
estimated spread/slippage for the manual paper ticket.

evaluate_gate(ctx, cfg) → {result: PASS|FAIL, passed: bool, labels:[...], reasons:[...], evidence, price_control}
Canonical labels: LIQUIDITY_SPREAD_PASS, LIQUIDITY_SPREAD_FAIL, SPREAD_TOO_WIDE, EXPECTED_SLIPPAGE_TOO_HIGH,
INSUFFICIENT_VOLUME, PARTICIPATION_TOO_HIGH, DATA_STALE, HALTED, PRICE_CONTROL_UNAVAILABLE.
"""
from __future__ import annotations

from typing import Mapping

PASS_LABEL = "LIQUIDITY_SPREAD_PASS"
FAIL_LABEL = "LIQUIDITY_SPREAD_FAIL"
SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
EXPECTED_SLIPPAGE_TOO_HIGH = "EXPECTED_SLIPPAGE_TOO_HIGH"
INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
PARTICIPATION_TOO_HIGH = "PARTICIPATION_TOO_HIGH"
DATA_STALE = "DATA_STALE"
HALTED = "HALTED"
PRICE_CONTROL_UNAVAILABLE = "PRICE_CONTROL_UNAVAILABLE"


def evaluate_gate(ctx: Mapping, cfg: Mapping, gcfg: Mapping | None = None) -> dict:
    g = gcfg or {}
    tiers = cfg.get("data_tiers", {})
    fails: list[str] = []
    ev: dict = {}

    # ── freshness ──
    stale_max = tiers.get("stale_max_sec")
    age = ctx.get("data_age_sec")
    ev["data_age_sec"] = age
    if stale_max is not None and age is not None and age > stale_max:
        fails.append(DATA_STALE)

    # ── halt ──
    if ctx.get("halted") is True:
        fails.append(HALTED)

    # ── data entitlement / price-control feasibility (never auto-market) ──
    tier = ctx.get("data_tier") or tiers.get("active_tier")
    price = ctx.get("price")
    ev["data_tier"] = tier
    if price is None or tier is None:
        fails.append(PRICE_CONTROL_UNAVAILABLE)

    # ── spread ──
    spread_bps = ctx.get("spread_bps")
    ev["spread_bps"] = spread_bps
    max_spread = g.get("max_spread_bps")
    if spread_bps is not None and max_spread is not None and spread_bps > max_spread:
        fails.append(SPREAD_TOO_WIDE)

    # ── expected slippage (from the tier's assumed slippage) ──
    slip = None
    try:
        slip = tiers.get("assumed_slippage_bps", {}).get(tier)
    except AttributeError:
        slip = None
    ev["expected_slippage_bps"] = slip
    max_slip = g.get("max_expected_slippage_bps")
    if slip is not None and max_slip is not None and slip > max_slip:
        fails.append(EXPECTED_SLIPPAGE_TOO_HIGH)

    # ── volume + dollar-volume rate ──
    vol = ctx.get("bar_volume")
    ev["bar_volume"] = vol
    min_vol = g.get("min_bar_volume")
    if vol is not None and min_vol is not None and vol < min_vol:
        fails.append(INSUFFICIENT_VOLUME)
    if vol is not None and price is not None:
        dvr = vol * price
        ev["dollar_vol_rate"] = round(dvr, 2)
        min_dvr = g.get("min_dollar_vol_rate")
        if min_dvr is not None and dvr < min_dvr and INSUFFICIENT_VOLUME not in fails:
            fails.append(INSUFFICIENT_VOLUME)

    # ── participation (hypothetical size vs bar volume) ──
    shares = ctx.get("hypothetical_shares")
    max_part = g.get("max_participation_pct")
    if shares is not None and vol and max_part is not None:
        part = shares / vol
        ev["participation_pct"] = round(part, 4)
        if part > max_part:
            fails.append(PARTICIPATION_TOO_HIGH)

    passed = not fails
    labels = [PASS_LABEL] if passed else [FAIL_LABEL, *dict.fromkeys(fails)]
    price_control = {
        "method": "LIMIT",                       # NEVER market — price-controlled orders only
        "estimated_spread_bps": spread_bps,
        "estimated_slippage_bps": slip,
        "available": price is not None,
    }
    return {"result": "PASS" if passed else "FAIL", "passed": passed,
            "labels": labels, "reasons": list(dict.fromkeys(fails)),
            "evidence": ev, "price_control": price_control}
