#!/usr/bin/env python3
"""Phase 206c — Path-based profit-protection rule pricer (long-only).

Replays a candidate stop/trail/lock/partial-take-profit rule against the ACTUAL ordered intrabar
OHLC path of a closed trade (from trade_intrabar_bars) and returns the path-measured captured
profit, the exit kind, and whether the rule exited PREMATURELY (stopped out for less than the
realized result). This is what the single-peak MFE approximation cannot do: it orders the stop
trigger against later profit using the real bar sequence.

EVIDENCE ONLY. Pure function over price data — no DB writes, no broker/order/strategy effects.

Fill model (conservative, long trades):
  * Stop fires when a bar's LOW <= the (ratcheting) stop level.
  * Fill = stop level, unless the bar OPENED below the stop (gap-down) -> fill = open.
  * Stops only ratchet up, never down.
"""

# Rule specs keyed by the backtest's rule_name. kind in {breakeven, lock, trail, partial}.
RULE_SPECS = {
    "breakeven_after_1R":            {"kind": "breakeven", "trigger_r": 1.0},
    "lock25_after_1_5R":             {"kind": "lock", "trigger_r": 1.5, "frac": 0.25},
    "lock50_after_2R":               {"kind": "lock", "trigger_r": 2.0, "frac": 0.50},
    "trail5_after_2R":               {"kind": "trail", "trigger_r": 2.0, "pct": 0.05},
    "trail8_after_3R":               {"kind": "trail", "trigger_r": 3.0, "pct": 0.08},
    "partial_tp_1_5R":               {"kind": "partial", "trigger_r": 1.5},
    "partial_tp_2R":                 {"kind": "partial", "trigger_r": 2.0},
    "scalp_fast_trail3_after_1_5R":  {"kind": "trail", "trigger_r": 1.5, "pct": 0.03},
    "scalp_partial_tp_1R":           {"kind": "partial", "trigger_r": 1.0},
    "swing_lock50_after_2R":         {"kind": "lock", "trigger_r": 2.0, "frac": 0.50},
    "income_wide_trail8_after_3R":   {"kind": "trail", "trigger_r": 3.0, "pct": 0.08},
    "position_lock50_after_3R":      {"kind": "lock", "trigger_r": 3.0, "frac": 0.50},
}


def price_rule(trade, bars, spec):
    """Price one rule on one trade's real path.

    trade: {entry_price, shares, planned_stop, realized_pnl}
    bars:  ordered list of {high, low, open, close} (long-only, ascending bar_time)
    spec:  one of RULE_SPECS values
    Returns dict or None (None = cannot path-price: missing R/path).
    """
    entry = trade.get("entry_price"); shares = trade.get("shares")
    pstop = trade.get("planned_stop"); realized = trade.get("realized_pnl") or 0.0
    if not entry or not shares or not pstop or entry <= pstop or not bars:
        return None
    r_per_share = entry - pstop
    trig_price = entry + spec["trigger_r"] * r_per_share
    kind = spec["kind"]

    # PARTIAL take-profit: half exits at the trigger price (only if the path actually reaches it),
    # remaining half rides to the realized exit. No extra stop on the runner.
    if kind == "partial":
        reached = any((b["high"] or 0) >= trig_price for b in bars)
        if not reached:
            return {"priced": True, "triggered": False, "simulated_capture": realized,
                    "exit_kind": "realized_exit", "premature": False}
        locked_half = 0.5 * (trig_price - entry) * shares
        sim = locked_half + 0.5 * realized
        return {"priced": True, "triggered": True, "simulated_capture": round(sim, 2),
                "exit_kind": "partial_tp", "premature": bool(sim < realized)}

    # STOP-based rules: walk the path, activate at trigger, ratchet the stop, exit on breach.
    activated = False
    stop_price = None
    peak_high = entry
    for b in bars:
        hi = b["high"] if b["high"] is not None else b.get("close")
        lo = b["low"] if b["low"] is not None else b.get("close")
        op = b["open"] if b.get("open") is not None else hi
        if hi is None or lo is None:
            continue
        peak_high = max(peak_high, hi)
        if not activated and hi >= trig_price:
            activated = True
        if activated:
            if kind == "breakeven":
                new_stop = entry
            elif kind == "lock":
                new_stop = entry + spec["frac"] * (peak_high - entry)
            else:  # trail
                new_stop = peak_high * (1 - spec["pct"])
            stop_price = new_stop if stop_price is None else max(stop_price, new_stop)
            if lo <= stop_price:
                fill = stop_price if op >= stop_price else op   # gap-down -> fill at open
                sim = (fill - entry) * shares
                return {"priced": True, "triggered": True, "simulated_capture": round(sim, 2),
                        "exit_kind": "rule_stop", "exit_price": round(fill, 4),
                        "premature": bool(sim < realized)}
    # never stopped out -> trade reaches its realized exit
    return {"priced": True, "triggered": activated, "simulated_capture": realized,
            "exit_kind": "realized_exit", "premature": False}


if __name__ == "__main__":
    # tiny self-test: a +3R peak then full round-trip back to breakeven
    entry, pstop, shares = 100.0, 95.0, 100  # R=5/share
    bars = [
        {"open": 100, "high": 100, "low": 100, "close": 100},
        {"open": 105, "high": 116, "low": 104, "close": 110},   # peak +3.2R
        {"open": 109, "high": 110, "low": 100, "close": 101},   # pullback
        {"open": 101, "high": 102, "low": 95,  "close": 96},    # deeper
    ]
    tr = {"entry_price": entry, "planned_stop": pstop, "shares": shares, "realized_pnl": -200.0}
    import json
    for name in ("trail5_after_2R", "lock50_after_2R", "breakeven_after_1R"):
        print(name, json.dumps(price_rule(tr, bars, RULE_SPECS[name])))
