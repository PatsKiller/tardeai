#!/usr/bin/env python3
"""Momentum-scalp CONFIRMATION OVERLAYS (Layer B) — evidence that supports/weakens a named setup,
computed INDEPENDENTLY of setup identity. Deterministic, pure, SHADOW.

Canonical labels: ONE_MIN_CONFLUENCE, CATALYST_CONFIRMED, VOLUME_CONFIRMED, L2_CONFIRMED, MARKET_ALIGNED,
VWAP_ALIGNED, EMA_ALIGNED, MOMENTUM_ALIGNED, SUPPORT_RESISTANCE_REACTION.

Rules (arch-owner): indicator periods are CONFIGURABLE (sources did not specify them); the indicator
COUNT alone must never override a failed setup; ONE_MIN_CONFLUENCE can NEVER become a fire by itself in
v1 — confirmations are additive evidence, not a trigger. Exposes labels, score, pass/fail counts, evidence.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scalp_t0_metrics as t0            # noqa: E402
import scalp_trigger_engine as tfsm      # noqa: E402

ONE_MIN_CONFLUENCE = "ONE_MIN_CONFLUENCE"
# directional overlays (agree with the inferred 1-minute direction)
_DIRECTIONAL = ("VWAP_ALIGNED", "EMA_ALIGNED", "MOMENTUM_ALIGNED", "MARKET_ALIGNED",
                "L2_CONFIRMED", "SUPPORT_RESISTANCE_REACTION")
# directionless overlays
_NONDIR = ("CATALYST_CONFIRMED", "VOLUME_CONFIRMED")


def _direction(bars: Sequence[Mapping]) -> str | None:
    if len(bars) < 3:
        return None
    vw = tfsm._vwap_series(bars)
    vwap = vw[-1] if vw else None
    closes = [t0._c(b) for b in bars[-3:] if t0._c(b) is not None]
    if vwap is None or len(closes) < 2:
        return None
    slope = closes[-1] - closes[0]
    if closes[-1] > vwap and slope >= 0:
        return "up"
    if closes[-1] < vwap and slope <= 0:
        return "down"
    return None


def compute_confirmations(ctx: Mapping, cfg: Mapping, ov: Mapping | None = None) -> dict:
    """Return {labels, confirmation_score, confirmation_pass_count, confirmation_fail_count,
    confirmation_evidence, direction}. `ov` is the overlays config block (config/scalp_confirmations.yaml)."""
    ov = ov or {}
    bars = ctx.get("bars") or []
    direction = ctx.get("direction") or _direction(bars)
    ev: dict = {"direction": direction}
    results: dict[str, bool | None] = {}

    vw = tfsm._vwap_series(bars)
    vwap = vw[-1] if vw else None
    close = t0._c(bars[-1]) if bars else None

    # VWAP_ALIGNED
    if vwap is not None and close is not None and direction:
        results["VWAP_ALIGNED"] = (direction == "up" and close >= vwap) or (direction == "down" and close <= vwap)
        ev["vwap"] = vwap
    else:
        results["VWAP_ALIGNED"] = None

    # EMA_ALIGNED (fast EMA; ENGINE_ADAPTATION period)
    closes = [t0._c(b) for b in bars if t0._c(b) is not None]
    ema_p = int(ov.get("ema_period_fast", 9))
    if len(closes) >= ema_p and close is not None and direction:
        ema = tfsm._ema(closes, ema_p)[-1]
        results["EMA_ALIGNED"] = (direction == "up" and close >= ema) or (direction == "down" and close <= ema)
        ev["ema_fast"] = round(ema, 4)
    else:
        results["EMA_ALIGNED"] = None

    # MOMENTUM_ALIGNED (short 1-minute price slope agrees with direction). NOTE: 5m-MACD needs ~175
    # one-minute bars (slow+signal periods of 5m closes) so it is only available late session — it is
    # kept in evidence when computable (logged, never gating); MOMENTUM_ALIGNED uses a short slope.
    mlook = int(ov.get("momentum_lookback", 3))
    if len(closes) > mlook and direction:
        slope = closes[-1] - closes[-1 - mlook]
        results["MOMENTUM_ALIGNED"] = (direction == "up" and slope >= 0) or (direction == "down" and slope <= 0)
        ev["momentum_slope"] = round(slope, 4)
    else:
        results["MOMENTUM_ALIGNED"] = None
    mh = ctx.get("macd_hist_5m")
    if mh is None:
        try:
            mh = tfsm.macd_hist_5m(bars, cfg)
        except Exception:
            mh = None
    if mh is not None:
        ev["macd_hist_5m"] = mh

    # MARKET_ALIGNED (broader market)
    ma = ctx.get("market_aligned")
    results["MARKET_ALIGNED"] = (ma is True) if ma is not None else None

    # L2_CONFIRMED (directional book stacking — only from an actual book, never inferred)
    book = ctx.get("book")
    if book:
        stack = book.get("stacking")
        results["L2_CONFIRMED"] = (direction == "up" and stack == "bid") or (direction == "down" and stack == "offer")
    else:
        results["L2_CONFIRMED"] = None

    # SUPPORT_RESISTANCE_REACTION (reaction at the recent range extreme in the direction)
    if len(bars) >= 5 and direction:
        rng_hi = max((t0._h(b) for b in bars[-10:] if t0._h(b) is not None), default=None)
        rng_lo = min((t0._l(b) for b in bars[-10:] if t0._l(b) is not None), default=None)
        frac = float(ov.get("sr_reaction_frac", 0.15))
        cur_l, cur_h = t0._l(bars[-1]), t0._h(bars[-1])
        span = (rng_hi - rng_lo) if (rng_hi is not None and rng_lo is not None and rng_hi > rng_lo) else None
        if span and direction == "up" and cur_l is not None:
            results["SUPPORT_RESISTANCE_REACTION"] = (cur_l - rng_lo) <= frac * span
        elif span and direction == "down" and cur_h is not None:
            results["SUPPORT_RESISTANCE_REACTION"] = (rng_hi - cur_h) <= frac * span
        else:
            results["SUPPORT_RESISTANCE_REACTION"] = None
    else:
        results["SUPPORT_RESISTANCE_REACTION"] = None

    # CATALYST_CONFIRMED (directionless)
    cw = ctx.get("catalyst_weight")
    results["CATALYST_CONFIRMED"] = (cw is not None and cw >= float(ov.get("catalyst_min_weight", 0.40))) \
        if cw is not None else None

    # VOLUME_CONFIRMED (directionless)
    look = int(ov.get("volume_lookback", 10))
    mult = float(ov.get("volume_confirm_mult", 1.5))
    vols = [t0._v(b) or 0.0 for b in bars[-(look + 1):-1]]
    curv = t0._v(bars[-1]) if bars else None
    if vols and curv is not None:
        results["VOLUME_CONFIRMED"] = curv >= mult * statistics.mean(vols)
    else:
        results["VOLUME_CONFIRMED"] = None

    labels = [k for k, v in results.items() if v is True]
    pass_count = len(labels)
    fail_count = sum(1 for v in results.values() if v is False)
    evaluable = sum(1 for v in results.values() if v is not None)

    # ONE_MIN_CONFLUENCE — enough DIRECTIONAL overlays aligned. Additive evidence only; never a fire.
    dir_aligned = sum(1 for k in _DIRECTIONAL if results.get(k) is True)
    if dir_aligned >= int(ov.get("min_confluence_labels", 3)):
        labels.append(ONE_MIN_CONFLUENCE)

    ev["results"] = results
    return {
        "labels": labels,
        "confirmation_score": round(pass_count / evaluable, 3) if evaluable else 0.0,
        "confirmation_pass_count": pass_count,
        "confirmation_fail_count": fail_count,
        "confirmation_evidence": ev,
        "direction": direction,
        "authorizes_fire": False,   # confirmations NEVER authorize a fire on their own (v1 invariant)
    }
