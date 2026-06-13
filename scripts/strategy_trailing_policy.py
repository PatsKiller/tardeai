#!/usr/bin/env python3
"""STOP-V2.4 — Strategy-aware trailing stop policy + optional structural overlay.

Maps strategy families to trailing tier configurations (R-multiple, V2.3) and — when explicitly
enabled in config/stop_trailing_hybrid.yaml (DEFAULT OFF) — augments them with structure-aware
stops: MA-trend filter, chandelier exit, and an ADX/MA-proximity dynamic multiplier (V2.4).

Does NOT move stops directly — returns recommendations only. The structural overlay can only RAISE
the recommended stop (tighten / lock more), never lower it, and never above current price; with the
config disabled, behavior is byte-for-byte identical to V2.3. Advisory; no broker write path here.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("strategy_trailing_policy")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HYBRID_CFG_PATH = _PROJECT_ROOT / "config" / "stop_trailing_hybrid.yaml"
_HYBRID_CFG_CACHE: Optional[dict] = None

# Strategy family classification
STRATEGY_FAMILIES = {
    # Momentum / Scalp — tight trailing, same-day exit
    "momentum_scalp": "momentum",
    "gap_and_go": "momentum",
    "earnings_catalyst": "momentum",
    "screener": "momentum",

    # Swing / Breakout — medium trailing, multi-day hold
    "swing_trade": "swing",
    "swing_breakout": "swing",
    "fib_retracement_bounce": "swing",
    "speculative_growth": "swing",
    "earnings_post_momentum": "swing",
    "earnings_pre_buildup": "swing",

    # Income / Dividend — wide trailing, long hold
    "dividend_growth_compounder": "income",
    "reit_income": "income",
    "bond_income": "income",
    "high_yield_income_bdc": "income",
    "income_add": "income",
    "international_dividend": "income",
    "covered_call_income": "income",
    "tax_loss_harvest": "income",

    # Position / Compounder — widest trailing, very long hold
    "core_growth_compounder": "position",
    "core_index": "position",
    "defense_thesis": "position",
    "sector_rotation": "position",

    # Recovery — patient trailing
    "recovery_watch": "income",  # treat like income for trailing
}

# Trailing tier definitions per family
# Each tier: (r_threshold, lock_r, description)
# lock_r=0.0 means breakeven
TRAILING_TIERS = {
    "momentum": {
        "tiers": [
            (1.0, 0.0, "breakeven"),
            (1.5, 0.5, "lock 0.5R"),
            (2.0, 1.0, "lock 1.0R"),
            (3.0, 2.0, "lock 2.0R"),
        ],
        "time_stop": {"type": "intraday", "close_at": "15:45"},
        "max_hold_days": None,  # intraday only
        "after_hours_trail": False,
    },
    "swing": {
        "tiers": [
            (1.0, 0.0, "breakeven"),
            (1.5, 0.5, "lock 0.5R"),
            (2.0, 1.0, "lock 1.0R"),
            (3.0, 2.0, "lock 2.0R"),
        ],
        "time_stop": {"type": "calendar", "max_hold_days": 21},
        "after_hours_trail": False,
    },
    "income": {
        "tiers": [
            (1.5, 0.0, "breakeven"),
            (2.5, 0.5, "lock 0.5R"),
            (3.5, 1.0, "lock 1.0R"),
            (5.0, 2.0, "lock 2.0R"),
        ],
        "time_stop": {"type": "review", "review_at_days": 90},
        "after_hours_trail": False,
    },
    "position": {
        "tiers": [
            (2.0, 0.0, "breakeven"),
            (3.0, 0.5, "lock 0.5R"),
            (4.0, 1.5, "lock 1.5R"),
            (6.0, 3.0, "lock 3.0R"),
        ],
        "time_stop": {"type": "review", "review_at_days": 180},
        "after_hours_trail": False,
    },
}

# Default for unknown strategies — conservative, requires review
DEFAULT_POLICY = {
    "tiers": [],  # no auto-trailing for unknown strategies
    "time_stop": {"type": "review", "review_at_days": 30},
    "after_hours_trail": False,
    "requires_review": True,
}


def get_strategy_family(strategy_id: str) -> str:
    """Return the family name for a strategy_id."""
    return STRATEGY_FAMILIES.get(strategy_id, "unknown")


def get_trailing_policy(strategy_id: str) -> dict:
    """Return the trailing policy for a strategy."""
    family = get_strategy_family(strategy_id)
    policy = TRAILING_TIERS.get(family, DEFAULT_POLICY).copy()
    policy["family"] = family
    policy["strategy_id"] = strategy_id
    policy["requires_review"] = family == "unknown"
    return policy


# ── STOP-V2.4 structural overlay (config-gated, default OFF) ─────────────────────────────────────

def _load_hybrid_config() -> dict:
    """Load config/stop_trailing_hybrid.yaml once. Absent/unparseable/disabled ⇒ {'enabled': False}
    so the overlay is a strict no-op (fail-safe to pure V2.3 R-multiple)."""
    global _HYBRID_CFG_CACHE
    if _HYBRID_CFG_CACHE is not None:
        return _HYBRID_CFG_CACHE
    cfg = {"enabled": False}
    try:
        if _HYBRID_CFG_PATH.exists():
            import yaml
            loaded = yaml.safe_load(_HYBRID_CFG_PATH.read_text()) or {}
            if isinstance(loaded, dict):
                cfg = loaded
    except Exception as e:
        log.warning(f"hybrid stop config unreadable ({e}) — overlay disabled (fail-safe)")
        cfg = {"enabled": False}
    _HYBRID_CFG_CACHE = cfg
    return cfg


def _structural_levels(symbol: str, cfg: dict) -> Optional[dict]:
    """ATR14 / EMA20 / SMA50 / ADX14 / highest_high(N) / last close from daily bars.
    Reuses indicator_engine._fetch_ohlcv (single data path). None on any failure ⇒ overlay skipped."""
    try:
        import indicator_engine as ie
        df = ie._fetch_ohlcv(symbol, days=max(90, int(cfg.get("chandelier_lookback", 22)) + 60))
        if df is None or len(df) < 50:
            return None
        import pandas_ta as ta
        atr_p = int(cfg.get("atr_period", 14))
        n = int(cfg.get("chandelier_lookback", 22))
        atr = float(ta.atr(df["high"], df["low"], df["close"], length=atr_p).dropna().iloc[-1])
        ema20 = float(ta.ema(df["close"], length=20).dropna().iloc[-1])
        sma50 = float(ta.sma(df["close"], length=50).dropna().iloc[-1])
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
        adx = float(adx_df[f"ADX_14"].dropna().iloc[-1]) if adx_df is not None else None
        hh = float(df["high"].tail(n).max())
        close = float(df["close"].iloc[-1])
        if atr <= 0:
            return None
        return {"atr": atr, "ema20": ema20, "sma50": sma50, "adx": adx,
                "highest_high": hh, "close": close}
    except Exception as e:
        log.warning(f"structural levels for {symbol} failed ({e}) — overlay skipped")
        return None


def _dynamic_multiplier(base_mult: float, lv: dict, cfg: dict) -> float:
    """Widen the ATR multiplier in strong trends (ADX high) / near a key MA (correction cushion);
    tighten in ranging tape (ADX low). Bounded to [base*0.7, base*1.6]."""
    m = base_mult
    adx = lv.get("adx")
    if adx is not None:
        if adx >= float(cfg.get("adx_trending_above", 25)):
            m *= 1.25                      # strong trend → give it room
        elif adx < float(cfg.get("adx_ranging_below", 20)):
            m *= 0.85                      # ranging → tighten
    # near a key MA within ma_proximity_atr → widen (don't get shaken in a normal pullback to support)
    atr = lv["atr"]; close = lv["close"]
    prox = float(cfg.get("ma_proximity_atr", 1.5))
    if min(abs(close - lv["ema20"]), abs(close - lv["sma50"])) <= prox * atr:
        m *= 1.15
    return max(base_mult * 0.7, min(m, base_mult * 1.6))


def _structural_overlay(strategy_id: str, symbol: Optional[str], current_price: float,
                        baseline_stop: float, current_stop: float) -> Optional[dict]:
    """Return {'stop': float, 'algos': [...], 'detail': {...}} raising the stop via the enabled
    structural algos, or None when disabled/inapplicable. Only ever TIGHTENS (>= baseline), and
    never >= current_price. MA-trend filter gates the overlay off in non-uptrends."""
    cfg = _load_hybrid_config()
    if not cfg.get("enabled") or not symbol:
        return None
    fam = get_strategy_family(strategy_id)
    fcfg = (cfg.get("families") or {}).get(fam)
    if not isinstance(fcfg, dict):
        return None
    if not any(fcfg.get(k) for k in ("ma_trend_filter", "chandelier", "dynamic_multiplier")):
        return None
    lv = _structural_levels(symbol, cfg)
    if not lv:
        return None

    # MA-TREND FILTER: only let the overlay tighten while price is in a confirmed uptrend. In chop
    # (below both MAs) defer entirely to the R-multiple baseline so we aren't shaken out.
    uptrend = lv["close"] > lv["ema20"] or lv["close"] > lv["sma50"]
    if fcfg.get("ma_trend_filter") and not uptrend:
        return {"stop": baseline_stop, "algos": ["ma_trend_filter:deferred"],
                "detail": {"reason": "price below EMA20 & SMA50 — overlay deferred to R-multiple",
                           **{k: round(v, 2) for k, v in lv.items() if isinstance(v, (int, float))}}}

    base_mult = float(fcfg.get("base_atr_mult", 3.0))
    mult = _dynamic_multiplier(base_mult, lv, cfg) if fcfg.get("dynamic_multiplier") else base_mult
    candidates = [baseline_stop]
    algos = []
    if fcfg.get("chandelier"):
        chand = lv["highest_high"] - mult * lv["atr"]
        candidates.append(chand); algos.append("chandelier")
    if fcfg.get("ma_trend_filter") and uptrend:
        ma_trail = lv["ema20"] - mult * lv["atr"]      # trail behind EMA20 with an ATR buffer
        candidates.append(ma_trail); algos.append("ma_trail")
    if fcfg.get("dynamic_multiplier"):
        algos.append(f"dyn_mult={round(mult, 2)}")

    overlay_stop = max(candidates)
    # clamp: tighten only (>= baseline & >= current), never at/above price
    overlay_stop = max(overlay_stop, baseline_stop, current_stop or 0)
    if overlay_stop >= current_price:
        overlay_stop = baseline_stop                    # would be invalid — fall back, no-op
        algos.append("clamped:at_price")
    return {"stop": round(overlay_stop, 2), "algos": algos,
            "detail": {"multiplier": round(mult, 2), "uptrend": uptrend,
                       **{k: round(v, 2) for k, v in lv.items() if isinstance(v, (int, float))}}}


def recommend_stop(strategy_id: str, entry_price: float, planned_stop: float,
                   current_stop: float, current_price: float,
                   market_hours: bool = True, symbol: Optional[str] = None) -> dict:
    """Compute trailing stop recommendation for a position.

    Returns recommendation dict — does NOT execute any stop movement. When the hybrid overlay is
    enabled (config/stop_trailing_hybrid.yaml) AND `symbol` is provided, a structural stop may
    TIGHTEN the R-multiple recommendation further; otherwise behavior is identical to V2.3.
    """
    policy = get_trailing_policy(strategy_id)
    family = policy["family"]

    if not entry_price or not planned_stop or entry_price <= planned_stop:
        return {
            "action": "hold",
            "reason": "invalid entry/stop data",
            "family": family,
            "current_stop": current_stop,
            "recommended_stop": current_stop,
        }

    initial_risk = entry_price - planned_stop
    if initial_risk <= 0:
        return {
            "action": "hold",
            "reason": "zero or negative initial risk",
            "family": family,
            "current_stop": current_stop,
            "recommended_stop": current_stop,
        }

    r_multiple = (current_price - entry_price) / initial_risk
    tiers = policy.get("tiers", [])

    # Find highest qualifying tier
    best_tier = None
    for r_threshold, lock_r, desc in reversed(tiers):
        if r_multiple >= r_threshold:
            best_tier = (r_threshold, lock_r, desc)
            break

    if not best_tier:
        # R-multiple says hold — but the structural overlay (chandelier/MA-trail) may already justify a
        # tighten on its own (config-gated; only when market hours allow trailing for this family).
        if market_hours or policy.get("after_hours_trail"):
            overlay = _structural_overlay(strategy_id, symbol, current_price, current_stop or 0, current_stop)
            if overlay and overlay["stop"] > (current_stop or 0):
                return {
                    "action": "recommend_trail",
                    "reason": (f"R={r_multiple:.2f} below first tier, but structural overlay raises stop "
                               f"${current_stop} → ${overlay['stop']} via {', '.join(overlay['algos'])}"),
                    "family": family,
                    "r_multiple": round(r_multiple, 2),
                    "current_stop": current_stop,
                    "recommended_stop": overlay["stop"],
                    "tier": "structural",
                    "hybrid": overlay,
                    "policy_version": "v2.4",
                }
        return {
            "action": "hold",
            "reason": f"R={r_multiple:.2f} below first tier threshold",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": current_stop,
            "policy_version": "v2.3",
        }

    r_threshold, lock_r, desc = best_tier
    new_stop = round(entry_price + lock_r * initial_risk, 2)

    # Stop can only move UP (tighten), never down
    effective_stop = max(new_stop, current_stop) if current_stop else new_stop

    if effective_stop <= current_stop:
        return {
            "action": "hold",
            "reason": f"R={r_multiple:.2f} tier={desc} but stop already at/above ${current_stop}",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": current_stop,
            "tier": desc,
            "policy_version": "v2.3",
        }

    # Check after-hours block
    if not market_hours and not policy.get("after_hours_trail", False):
        return {
            "action": "recommend_deferred",
            "reason": f"After hours — would trail to ${effective_stop} ({desc}) but blocked until market open",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": effective_stop,
            "tier": desc,
            "blocked_by": "after_hours",
            "policy_version": "v2.3",
        }

    # Check unknown strategy
    if policy.get("requires_review"):
        return {
            "action": "recommend_review",
            "reason": f"Unknown strategy '{strategy_id}' — trailing requires operator review",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": effective_stop,
            "blocked_by": "unknown_strategy",
            "policy_version": "v2.3",
        }

    # STOP-V2.4 structural overlay — may tighten effective_stop further (config-gated, default no-op)
    overlay = _structural_overlay(strategy_id, symbol, current_price, effective_stop, current_stop)
    final_stop = effective_stop
    reason = f"R={r_multiple:.2f} >= {r_threshold}R — {desc} (${current_stop} → ${effective_stop})"
    result = {
        "action": "recommend_trail",
        "reason": reason,
        "family": family,
        "r_multiple": round(r_multiple, 2),
        "current_stop": current_stop,
        "recommended_stop": effective_stop,
        "tier": desc,
        "tier_r_threshold": r_threshold,
        "tier_lock_r": lock_r,
        "policy_version": "v2.4",
    }
    if overlay and overlay["stop"] > effective_stop:
        final_stop = overlay["stop"]
        result["recommended_stop"] = final_stop
        result["reason"] = (f"R={r_multiple:.2f} {desc}; structural overlay tightened "
                            f"${effective_stop} → ${final_stop} via {', '.join(overlay['algos'])}")
        result["hybrid"] = overlay
    elif overlay:
        result["hybrid"] = overlay   # ran but didn't tighten — recorded for the audit trail
    return result


if __name__ == "__main__":
    # Preview helper: A/B the structural overlay for one position WITHOUT touching config or live state.
    #   python3 scripts/strategy_trailing_policy.py SYMBOL STRATEGY ENTRY PLANNED_STOP CUR_STOP CUR_PRICE
    # Forces the overlay on (all algos) for the preview so you can see what it WOULD recommend.
    import sys, json
    if len(sys.argv) < 7:
        print(__doc__); sys.exit(0)
    # import self by real name so the forced config + functions share ONE module object (avoids the
    # __main__ double-import quirk where the cache lands on a different module copy than the callee).
    import strategy_trailing_policy as _self
    strat = sys.argv[2]
    entry, pstop, cstop, cprice = (float(x) for x in sys.argv[3:7])
    fam = _self.get_strategy_family(strat)
    _self._HYBRID_CFG_CACHE = {"enabled": True, "atr_period": 14, "chandelier_lookback": 22,
                               "adx_ranging_below": 20, "adx_trending_above": 25, "ma_proximity_atr": 1.5,
                               "families": {fam: {"ma_trend_filter": True, "chandelier": True,
                                                  "dynamic_multiplier": True, "base_atr_mult": 3.0}}}
    base = _self.recommend_stop(strat, entry, pstop, cstop, cprice, market_hours=True, symbol=sys.argv[1].upper())
    print(json.dumps(base, indent=2, default=str))
