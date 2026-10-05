"""Minimum stop distance for momentum-scalp levels (operator 2026-10-05, PR #1439).

Pure, dependency-free so every consumer (the 5-min engine and the sub-minute alert loop) floors
stops the same way without importing the engine's data stack. Config: `min_stop:` in
config/scalp_signal_engine.yaml.
"""
from __future__ import annotations


def min_stop_distance(price, atr, spread_bps, cfg: dict):
    """Minimum stop distance in $ = max(atr_mult·ATR_1m, spread_mult·spread$, pct_of_price·price).
    A 1-cent stop on a $4 name (XNDU, 10-05: R $0.01-0.02) made every tick look like several R."""
    ms = cfg["min_stop"]
    if price is None or price <= 0:
        return None
    parts = [float(ms["pct_of_price"]) * price]
    if atr and atr > 0:
        parts.append(float(ms["atr_mult"]) * atr)
    if spread_bps is not None and spread_bps > 0:
        parts.append(float(ms["spread_mult"]) * spread_bps / 1e4 * price)
    return max(parts)


def apply_min_stop(entry, stop, atr, spread_bps, cfg: dict) -> dict:
    """Widen (never tighten) a stop to the minimum distance. Returns entry/stop/r_dollars/stop_pct
    plus stop_floor_applied and the original stop."""
    out = {"entry": entry, "stop": stop, "stop_floor_applied": False, "stop_raw": stop}
    if entry is not None and cfg.get("min_stop", {}).get("enabled") and stop is not None:
        d = min_stop_distance(entry, atr, spread_bps, cfg)
        if d is not None and (entry - stop) < d:
            out["stop"] = round(entry - d, 4)
            out["stop_floor_applied"] = True
    r = (entry - out["stop"]) if (entry is not None and out["stop"] is not None) else None
    out["r_dollars"] = round(r, 4) if r is not None else None
    out["stop_pct"] = round(r / entry, 4) if (r is not None and entry) else None
    return out
