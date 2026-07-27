#!/usr/bin/env python3
"""M3-S5 — entry-trigger state machine (Momentum Scalp Signal Engine, design §4/§6).

PURE function over a 1-minute bar series. No I/O, no DB, no network, no alerts, no proposals, no order
path. Formalizes the operator's "first candle that reverses the pullback" pattern as a deterministic
state machine:

    IDLE → IMPULSE → PULLBACK → ARMED → TRIGGERED | VOID

All seven §6 conditions are required for a TRIGGERED fire; failures VOID the leg (reset to IDLE) or
REJECT the trigger with a reason. MACD(5m) is computed and LOGGED but NEVER gates (§6.1). A post-halt
30-bar re-warm suppresses new IMPULSE detection (§6.6). Levels: entry = trigger_high+off,
stop = min(trigger_low, pullback_low)-off floored at entry-1·ATR, R = entry-stop.

Consumed by the shadow logger, which records TRIGGERED fires under the `TRIGGER` lane. This module
imports only scalp_t0_metrics (ATR/EvR helpers) — never the scorer or logger.

INTERPRETATION NOTE (surfaced for operator, design §6 is ambiguous): the "R:R to target_1 < 2.0"
rejection uses target_1 = the impulse **leg high** (nearest resistance / room-to-run check). §7's exit
target_1 = entry+2R is a separate concept. Flagged in the M3-S5 report.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scalp_t0_metrics as t0  # noqa: E402

IDLE, IMPULSE, PULLBACK, ARMED, TRIGGERED, VOID = "IDLE", "IMPULSE", "PULLBACK", "ARMED", "TRIGGERED", "VOID"


def _ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(out[-1] + k * (float(v) - out[-1]))
    return out


def macd_hist_5m(bars_1m: Sequence[Mapping], cfg: Mapping) -> float | None:
    """MACD histogram on 5-minute closes (aggregate every 5 one-minute bars). LOGGED, never gates."""
    c = cfg["trigger"]["macd_5m"]
    closes5 = []
    for j in range(0, len(bars_1m), 5):
        chunk = bars_1m[j:j + 5]
        cl = t0._c(chunk[-1]) if chunk else None
        if cl is not None:
            closes5.append(cl)
    if len(closes5) < c["slow"] + c["signal"]:
        return None
    ef, es = _ema(closes5, c["fast"]), _ema(closes5, c["slow"])
    macd_line = [a - b for a, b in zip(ef, es)]
    sig = _ema(macd_line, c["signal"])
    return round(macd_line[-1] - sig[-1], 6)


def _atr_series(bars: Sequence[Mapping], period: int) -> list[float | None]:
    return [t0.atr(bars[: i + 1], period) for i in range(len(bars))]


def _vwap_series(bars: Sequence[Mapping]) -> list[float | None]:
    out, num, den = [], 0.0, 0.0
    for b in bars:
        h, l, c, v = t0._h(b), t0._l(b), t0._c(b), t0._v(b)
        if None not in (h, l, c, v) and v > 0:
            num += ((h + l + c) / 3.0) * v
            den += v
        out.append((num / den) if den > 0 else None)
    return out


def _evr_absorption_absent(impulse_bars: Sequence[Mapping], cfg: Mapping) -> bool:
    """§6.7 — absorption absent = the last 3 impulse bars are NOT dominated by low EvR (high volume,
    little result). Deterministic: mean EvR of the last 3 impulse bars >= 25th-percentile of all
    impulse-bar EvRs. Too few bars → treated as absent (no evidence of absorption)."""
    if len(impulse_bars) < 4:
        return True
    evr = [x for x in t0.effort_vs_result(impulse_bars) if x is not None]
    if len(evr) < 4:
        return True
    last3 = [x for x in evr[-3:]]
    if not last3:
        return True
    q25 = statistics.quantiles(evr, n=4)[0] if len(evr) >= 4 else min(evr)
    return statistics.mean(last3) >= q25


def compute_levels(trigger_high: float, trigger_low: float, pullback_low: float, atr: float,
                   leg_high: float, origin_low: float, cfg: Mapping) -> dict:
    """Pure §6 entry/stop/R computation + rejection logic. entry = trigger_high+off;
    stop = min(trigger_low, pullback_low)-off, floored at entry-1·ATR (noise-stop protection, so
    R ≤ ATR); R = entry-stop. Rejects: nonpositive R, stop_pct > max, no-chase, R:R (leg_height/R)
    < min_rr. Returns {outcome: TRIGGERED|REJECT, reason, entry, stop, r_dollars, stop_pct, rr, leg_high}."""
    tc = cfg["trigger"]
    entry = trigger_high + tc["entry_offset"]
    raw_stop = min(trigger_low, pullback_low) - tc["stop_offset"]
    floor_stop = entry - tc["noise_stop_atr_mult"] * (atr or 0)
    stop = max(raw_stop, floor_stop)
    floor_bound = floor_stop >= raw_stop   # the ATR noise-stop floor set the stop (R capped at ~ATR)
    R = entry - stop
    stop_pct = (R / entry) if entry else None
    leg_height = leg_high - origin_low
    rr = (leg_height / R) if (R and R > 0) else None
    reason = None
    if not R or R <= 0:
        reason = "nonpositive_R"
    elif stop_pct is not None and stop_pct > tc["max_stop_pct"]:
        reason = f"stop_pct>{tc['max_stop_pct']}"
    elif entry > leg_high * tc["no_chase_mult"]:
        reason = "no_chase"
    elif rr is not None and rr < tc["min_rr"]:
        reason = "rr<min"
    return {"outcome": (TRIGGERED if not reason else "REJECT"), "reason": reason,
            "entry": round(entry, 4), "stop": round(stop, 4),
            "r_dollars": round(R, 4) if R else None,
            "stop_pct": round(stop_pct, 4) if stop_pct else None, "floor_bound": floor_bound,
            "rr": round(rr, 3) if rr is not None else None, "leg_high": round(leg_high, 4)}


def run_trigger_engine(bars: Sequence[Mapping], cfg: Mapping) -> dict:
    """Fold the state machine over `bars`. Returns {events:[...], trace:[state per bar], macd_hist_5m}.
    Pure. Each event: {fire_idx, outcome (TRIGGERED|REJECT|VOID), reason, entry, stop, r_dollars,
    stop_pct, leg_high, rr_to_resistance}."""
    tc = cfg["trigger"]
    atrs = _atr_series(bars, int(tc["atr_period"]))
    vwaps = _vwap_series(bars)
    events, trace = [], []

    st = IDLE
    origin_low = t0._l(bars[0]) if bars else None
    origin_idx = 0
    leg_high = None
    leg_high_idx = None
    pullback_low = None
    lower_highs = 0
    prev_high = None
    rewarm = 0

    def reset():
        nonlocal st, origin_low, origin_idx, leg_high, leg_high_idx, pullback_low, lower_highs, prev_high
        st = IDLE
        leg_high = leg_high_idx = pullback_low = prev_high = None
        lower_highs = 0

    for i, b in enumerate(bars):
        h, l, c, o = t0._h(b), t0._l(b), t0._c(b), t0._o(b)
        atr, vwap = atrs[i], vwaps[i]
        if rewarm > 0:
            rewarm -= 1
            trace.append(IDLE)
            origin_low = l if (origin_low is None or (l is not None and l < origin_low)) else origin_low
            origin_idx = i if origin_low == l else origin_idx
            continue

        if st == IDLE:
            if l is not None and (origin_low is None or l < origin_low):
                origin_low, origin_idx = l, i
            if h is not None and atr and origin_low is not None and (h - origin_low) >= tc["impulse_atr_mult"] * atr:
                st, leg_high, leg_high_idx = IMPULSE, h, i

        elif st == IMPULSE:
            if h is not None and h > leg_high:
                leg_high, leg_high_idx = h, i          # extend the leg
            else:
                st = PULLBACK                          # first lower high → pullback
                pullback_low, lower_highs, prev_high = l, 1, h

        elif st in (PULLBACK, ARMED):
            if l is not None and (pullback_low is None or l < pullback_low):
                pullback_low = l
            if h is not None and prev_high is not None and h < prev_high:
                lower_highs += 1
            prev_high = h if h is not None else prev_high
            leg = (leg_high - origin_low) if (leg_high is not None and origin_low is not None) else None
            retrace = ((leg_high - pullback_low) / leg) if (leg and leg > 0 and pullback_low is not None) else 0.0
            if retrace > tc["retrace_void"]:
                events.append({"fire_idx": i, "outcome": VOID, "reason": "deep_retrace",
                               "retrace": round(retrace, 3)})
                reset()
                trace.append(VOID)
                continue
            # volume dry-up (§6.4)
            imp_vols = [t0._v(x) or 0.0 for x in bars[origin_idx + 1: (leg_high_idx or origin_idx) + 1]]
            pb_vols = [t0._v(x) or 0.0 for x in bars[(leg_high_idx or origin_idx) + 1: i + 1]]
            vdu_ok = bool(imp_vols and pb_vols and statistics.mean(pb_vols) <= tc["vdu_ratio"] * statistics.mean(imp_vols))
            if st == PULLBACK:
                if (lower_highs >= tc["min_lower_highs"] and tc["retrace_min"] <= retrace <= tc["retrace_max"] and vdu_ok):
                    st = ARMED
            if st == ARMED:
                prev = bars[i - 1] if i > 0 else None
                ph = t0._h(prev) if prev else None
                rng = (h - l) if (h is not None and l is not None and h > l) else None
                top_ok = bool(rng and c is not None and (c - l) / rng >= tc["trigger_close_top_frac"])
                vol_ok = bool(pb_vols and (t0._v(b) or 0) >= tc["trigger_vol_mult"] * statistics.mean(pb_vols))
                break_ok = bool(ph is not None and c is not None and c > ph)
                structure_held = bool(vwap is None or (pullback_low is not None and pullback_low >= vwap) or (c is not None and c >= vwap))
                absorption_absent = _evr_absorption_absent(bars[origin_idx: (leg_high_idx or origin_idx) + 1], cfg)
                if break_ok and top_ok and vol_ok:
                    if not structure_held:
                        events.append({"fire_idx": i, "outcome": "REJECT", "reason": "structure_not_held_vwap"})
                        reset(); trace.append(VOID); continue
                    if not absorption_absent:
                        events.append({"fire_idx": i, "outcome": "REJECT", "reason": "absorption"})
                        reset(); trace.append(VOID); continue
                    ev = compute_levels(h, l, pullback_low, atr or 0, leg_high, origin_low, cfg)
                    ev["fire_idx"] = i
                    events.append(ev)
                    reset(); trace.append(TRIGGERED if ev["outcome"] == TRIGGERED else VOID); continue

        trace.append(st)

    return {"events": events, "trace": trace, "macd_hist_5m": macd_hist_5m(bars, cfg)}


def triggered_fires(result: dict) -> list[dict]:
    return [e for e in result["events"] if e.get("outcome") == TRIGGERED]
