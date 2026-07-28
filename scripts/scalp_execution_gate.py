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

# ── stop-reference validator reason codes (Defect 2 — deterministic minimum-stop floor) ──
STOP_REFERENCE_MISSING = "STOP_REFERENCE_MISSING"
STOP_DIRECTION_INVALID = "STOP_DIRECTION_INVALID"
STOP_DISTANCE_BELOW_TICK_FLOOR = "STOP_DISTANCE_BELOW_TICK_FLOOR"
STOP_DISTANCE_BELOW_SPREAD_FLOOR = "STOP_DISTANCE_BELOW_SPREAD_FLOOR"
STOP_DISTANCE_BELOW_VOLATILITY_FLOOR = "STOP_DISTANCE_BELOW_VOLATILITY_FLOOR"
STOP_FLOOR_INPUT_UNAVAILABLE = "STOP_FLOOR_INPUT_UNAVAILABLE"
STOP_VALIDATION_PASS = "STOP_VALIDATION_PASS"

# CONFIGURABLE ENGINE ADAPTATION fallbacks — authoritative values live in config/scalp_confirmations.yaml
# (gate.stop_floor). These mirror that config ONLY as a defensive last resort when no cfg is supplied.
_STOP_FLOOR_DEFAULTS = {
    "min_stop_ticks": 2,
    "min_stop_spread_multiple": 1.5,
    "min_stop_atr_multiple": 0.25,
    "us_equity_fallback": {"ge_1": 0.01, "lt_1": 0.0001},
}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_stop_reference(*, entry_ref, stop_ref, atr_1m=None, spread_bps=None,
                            price_increment=None, price=None, data_tier=None,
                            cfg: Mapping | None = None) -> dict:
    """ONE pure minimum-stop-floor validator for the universal execution-quality gate.

    Rejects (never widens) a long-entry stop reference that sits inside deterministic market noise. The
    required distance is the MAX of a tick floor, a spread floor, and a short-horizon volatility floor;
    a stop tighter than that MAX is a VETO. Fails CLOSED when no defensible floor can be established.

    Returns: {stop_validation: PASS|VETO, actual_stop_distance, required_stop_distance, tick_floor,
              spread_floor, volatility_floor, stop_distance_bps, price_increment, reason_codes}.
    """
    fc = dict(_STOP_FLOOR_DEFAULTS)
    sf = (cfg or {}).get("stop_floor") if isinstance(cfg, Mapping) else None
    if isinstance(sf, Mapping):
        fc.update({k: sf.get(k, fc[k]) for k in fc})
    min_ticks = _num(fc.get("min_stop_ticks"))
    min_spread_mult = _num(fc.get("min_stop_spread_multiple"))
    min_atr_mult = _num(fc.get("min_stop_atr_multiple"))
    fb = fc.get("us_equity_fallback") if isinstance(fc.get("us_equity_fallback"), Mapping) else {}

    entry = _num(entry_ref)
    stop = _num(stop_ref)
    px = _num(price)
    ref_px = px if px is not None else entry

    def _out(result, actual, required, tick_f, spread_f, vol_f, codes):
        bps = (actual / entry * 1e4) if (actual is not None and entry) else None
        return {
            "stop_validation": result,
            "actual_stop_distance": round(actual, 6) if actual is not None else None,
            "required_stop_distance": round(required, 6) if required is not None else None,
            "tick_floor": round(tick_f, 6) if tick_f is not None else None,
            "spread_floor": round(spread_f, 6) if spread_f is not None else None,
            "volatility_floor": round(vol_f, 6) if vol_f is not None else None,
            "stop_distance_bps": round(bps, 3) if bps is not None else None,
            "price_increment": inc,
            "reason_codes": list(dict.fromkeys(codes)),
        }

    # resolve the price increment (prefer an explicit provider/broker increment; else documented fallback)
    inc = _num(price_increment)
    if inc is None and ref_px is not None:
        inc = _num(fb.get("ge_1", 0.01)) if ref_px >= 1.0 else _num(fb.get("lt_1", 0.0001))

    if entry is None or stop is None:
        return _out("VETO", None, None, None, None, None, [STOP_REFERENCE_MISSING])
    actual = entry - stop
    if actual <= 0:
        return _out("VETO", actual, None, None, None, None, [STOP_DIRECTION_INVALID])

    # component floors — only the ones whose inputs are available contribute to the required distance
    tick_floor = (min_ticks * inc) if (min_ticks is not None and inc is not None) else None
    spread_dollars = (_num(spread_bps) / 1e4 * ref_px) if (_num(spread_bps) is not None and ref_px is not None) else None
    spread_floor = (min_spread_mult * spread_dollars) if (min_spread_mult is not None and spread_dollars is not None) else None
    atr = _num(atr_1m)
    volatility_floor = (min_atr_mult * atr) if (min_atr_mult is not None and atr is not None and atr > 0) else None

    floors = [f for f in (tick_floor, spread_floor, volatility_floor) if f is not None]
    if not floors:
        # no defensible floor can be established → fail closed
        return _out("VETO", actual, None, tick_floor, spread_floor, volatility_floor,
                    [STOP_FLOOR_INPUT_UNAVAILABLE])
    required = max(floors)

    codes = []
    if tick_floor is not None and actual < tick_floor:
        codes.append(STOP_DISTANCE_BELOW_TICK_FLOOR)
    if spread_floor is not None and actual < spread_floor:
        codes.append(STOP_DISTANCE_BELOW_SPREAD_FLOOR)
    if volatility_floor is not None and actual < volatility_floor:
        codes.append(STOP_DISTANCE_BELOW_VOLATILITY_FLOOR)
    if codes:
        return _out("VETO", actual, required, tick_floor, spread_floor, volatility_floor, codes)
    return _out("PASS", actual, required, tick_floor, spread_floor, volatility_floor,
                [STOP_VALIDATION_PASS])


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

    # ── stop-reference validation (Defect 2) — computed ONLY when a stop reference is supplied. This is a
    # SEPARATE eligibility dimension: it never silently widens a stop and never flips the liquidity gate's
    # PASS/FAIL. A FIRED setup with stop_validation != PASS stays visible but is not execution-eligible. ──
    stop_validation = None
    if ctx.get("entry_ref") is not None and ctx.get("stop_ref") is not None:
        stop_validation = validate_stop_reference(
            entry_ref=ctx.get("entry_ref"), stop_ref=ctx.get("stop_ref"),
            atr_1m=ctx.get("atr_1m"), spread_bps=spread_bps,
            price_increment=ctx.get("price_increment"), price=price,
            data_tier=tier, cfg=g)
        ev["stop_validation"] = stop_validation

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
            "evidence": ev, "price_control": price_control,
            "stop_validation": stop_validation}
