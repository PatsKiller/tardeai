#!/usr/bin/env python3
"""backtest_hybrid_stops.py — STOP-V2.4 vs V2.3 A/B backtest (read-only, advisory).

Proves (or disproves) that the structural overlay (MA-trend filter + chandelier + dynamic ATR
multiplier) beats the pure R-multiple trailing on expectancy/profit-factor/drawdown BEFORE the
operator flips config/stop_trailing_hybrid.yaml on. Prop-desk rule: promote by expectancy, not
hope.

METHOD (isolates the STOP logic — both policies see identical entries):
  • Entries: 20-day breakout, flat-only (close > max of prior 20 closes). Classic trend-following
    entry; the regime where trailing-stop quality actually matters.
  • Initial stop: entry − INIT_ATR_MULT × ATR14 at entry (defines initial risk R).
  • Walk forward bar-by-bar; each bar: check intrabar stop hit (low ≤ stop) FIRST, else ask the
    REAL strategy_trailing_policy.recommend_stop to (maybe) ratchet the stop up. Time-stop at
    MAX_HOLD bars. Exit at last close if never stopped.
  • V2.3 run: overlay disabled. V2.4 run: overlay enabled for the family, fed POINT-IN-TIME levels
    (no lookahead) computed from bars[:i+1]. Same production code path either way — the backtest
    cannot diverge from live behavior.

Metrics per policy: trades, win%, expectancy (mean R), profit factor, max drawdown (R), avg hold,
whipsaw count (stopped ≤0 then price > entry within WHIPSAW_LOOKAHEAD bars). Verdict = expectancy
delta, gated on profit factor + drawdown not worsening.

  python3 scripts/backtest_hybrid_stops.py [--symbols V,RTX,LMT] [--years 3] [--strategy swing_breakout]
  ADVISORY ONLY — no orders, no config writes, no broker contact.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

INIT_ATR_MULT = 2.0        # initial stop distance = 2×ATR (defines R)
MAX_HOLD = 60              # calendar-bar time stop
WHIPSAW_LOOKAHEAD = 10     # bars after a losing exit to check if price recovered above entry
BREAKOUT_LOOKBACK = 20

DEFAULT_SYMBOLS = ["V", "RTX", "LMT", "NOC", "GD", "PLTR"]


def _fetch(symbol: str, years: int):
    import yfinance as yf
    try:
        h = yf.Ticker(symbol).history(period=f"{years}y")
        if h is None or len(h) < 120:
            return None
        h = h.rename(columns=str.lower)[["high", "low", "close"]].reset_index(drop=True)
        return h
    except Exception:
        return None


def _indicators(df, cfg):
    """Causal indicator series (each value uses only data up to its own index — no lookahead)."""
    import pandas_ta as ta
    atr_p = int(cfg.get("atr_period", 14))
    n = int(cfg.get("chandelier_lookback", 22))
    out = {}
    out["atr"] = ta.atr(df["high"], df["low"], df["close"], length=atr_p)
    out["ema20"] = ta.ema(df["close"], length=20)
    out["sma50"] = ta.sma(df["close"], length=50)
    adx = ta.adx(df["high"], df["low"], df["close"], length=14)
    out["adx"] = adx[f"ADX_14"] if adx is not None else None
    out["hh"] = df["high"].rolling(n).max()
    out["bo"] = df["close"].rolling(BREAKOUT_LOOKBACK).max().shift(1)   # prior 20-close high (causal)
    return out


def _levels_at(ind, i):
    """Point-in-time structural levels dict for bar i, or None if any indicator is NaN yet."""
    try:
        atr = float(ind["atr"].iloc[i]); ema20 = float(ind["ema20"].iloc[i])
        sma50 = float(ind["sma50"].iloc[i]); hh = float(ind["hh"].iloc[i])
        adx = float(ind["adx"].iloc[i]) if ind["adx"] is not None else None
        close = float(ind["close"].iloc[i]) if "close" in ind else None
        import math
        if any(x is None or (isinstance(x, float) and math.isnan(x)) for x in (atr, ema20, sma50, hh)):
            return None
        if atr <= 0:
            return None
        return {"atr": atr, "ema20": ema20, "sma50": sma50, "adx": adx, "highest_high": hh, "close": close}
    except Exception:
        return None


def _simulate(df, ind, strategy, hybrid):
    """Run all breakout trades under one policy. hybrid=False → V2.3; True → V2.4 overlay (point-in-time).
    Returns list of trade dicts with realized_R, exit_reason, hold, whipsaw."""
    import strategy_trailing_policy as p
    closes = df["close"].values; highs = df["high"].values; lows = df["low"].values
    bo = ind["bo"].values; atr = ind["atr"].values
    trades = []
    i = 55                      # warm-up for sma50/adx
    n = len(df)
    while i < n - 1:
        # entry: breakout above prior 20-close high, ATR valid
        import math
        if math.isnan(bo[i]) or math.isnan(atr[i]) or closes[i] <= bo[i] or atr[i] <= 0:
            i += 1; continue
        entry = float(closes[i]); planned_stop = entry - INIT_ATR_MULT * float(atr[i])
        initial_risk = entry - planned_stop
        if initial_risk <= 0:
            i += 1; continue
        current_stop = planned_stop
        exit_reason = "time"; realized_R = None; entry_i = i
        j = i + 1
        while j < n:
            if lows[j] <= current_stop:                       # intrabar stop hit
                realized_R = (current_stop - entry) / initial_risk
                exit_reason = "stop"; break
            cur_price = float(closes[j])
            if hybrid:
                lv = _levels_at({**ind, "close": df["close"]}, j)
                p._BT_LEVELS = lv                              # inject point-in-time levels
            rec = p.recommend_stop(strategy, entry, planned_stop, current_stop, cur_price,
                                   market_hours=True, symbol="BT" if hybrid else None)
            ns = rec.get("recommended_stop")
            if ns and ns > current_stop and ns < cur_price:
                current_stop = float(ns)
            if j - entry_i >= MAX_HOLD:
                realized_R = (cur_price - entry) / initial_risk; exit_reason = "time"; break
            j += 1
        if realized_R is None:                                # ran off the end
            realized_R = (float(closes[-1]) - entry) / initial_risk; exit_reason = "eod"; j = n - 1
        # whipsaw: losing/scratch exit, then price recovers above entry within lookahead
        whip = False
        if realized_R <= 0:
            end = min(j + WHIPSAW_LOOKAHEAD, n)
            if any(highs[k] > entry for k in range(j, end)):
                whip = True
        trades.append({"entry_i": entry_i, "exit_i": j, "entry": round(entry, 2),
                       "realized_R": round(realized_R, 3), "exit_reason": exit_reason,
                       "hold": j - entry_i, "whipsaw": whip})
        i = j + 1                                             # flat-only: next entry after this exit
    return trades


def _metrics(trades):
    if not trades:
        return {"trades": 0}
    rs = [t["realized_R"] for t in trades]
    wins = [r for r in rs if r > 0]; losses = [r for r in rs if r < 0]
    gross_win = sum(wins); gross_loss = abs(sum(losses))
    # max drawdown on the cumulative-R equity curve
    eq = 0.0; peak = 0.0; mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {
        "trades": len(trades),
        "win_pct": round(100 * len(wins) / len(trades), 1),
        "expectancy_R": round(sum(rs) / len(rs), 3),
        "total_R": round(sum(rs), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_dd_R": round(mdd, 2),
        "avg_hold": round(sum(t["hold"] for t in trades) / len(trades), 1),
        "whipsaws": sum(1 for t in trades if t["whipsaw"]),
    }


def run(symbols, years, strategy, algos=("ma_trend_filter", "chandelier", "dynamic_multiplier"),
        base_atr_mult=3.0):
    import strategy_trailing_policy as p
    # configure the overlay for the strategy's family with the SELECTED algos, fed point-in-time levels
    fam = p.get_strategy_family(strategy)
    fcfg = {"ma_trend_filter": "ma_trend_filter" in algos, "chandelier": "chandelier" in algos,
            "dynamic_multiplier": "dynamic_multiplier" in algos, "base_atr_mult": base_atr_mult}
    cfg = {"enabled": True, "atr_period": 14, "chandelier_lookback": 22, "adx_ranging_below": 20,
           "adx_trending_above": 25, "ma_proximity_atr": 1.5, "families": {fam: fcfg}}
    # patch _structural_levels to hand back the injected point-in-time levels during the v24 run
    p._BT_LEVELS = None
    _orig_levels = p._structural_levels
    p._structural_levels = lambda sym, c: getattr(p, "_BT_LEVELS", None)

    agg = {"v23": [], "v24": []}
    rows = []
    for sym in symbols:
        df = _fetch(sym, years)
        if df is None:
            rows.append((sym, None, None)); continue
        ind = _indicators(df, cfg)
        # V2.3 (overlay off)
        p._HYBRID_CFG_CACHE = {"enabled": False}
        t23 = _simulate(df, ind, strategy, hybrid=False)
        # V2.4 (overlay on)
        p._HYBRID_CFG_CACHE = cfg
        t24 = _simulate(df, ind, strategy, hybrid=True)
        agg["v23"] += t23; agg["v24"] += t24
        rows.append((sym, _metrics(t23), _metrics(t24)))
    p._structural_levels = _orig_levels
    p._HYBRID_CFG_CACHE = {"enabled": False}
    return rows, {"v23": _metrics(agg["v23"]), "v24": _metrics(agg["v24"])}


# ── Phase 2 (2026-06-29): CONTEXT-AWARE LAYERED policy re-test ───────────────────────────────────────
# STOP-V2.4 tested the PLAIN chandelier overlay and HELD. The MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY adds
# things STOP-V2.4 never tested: L2 breakeven, DELAYED trail activation (+act_r, not immediate), and a
# REGIME-aware multiplier. This re-test isolates the trailing contribution: baseline (L1 stop + L2 breakeven,
# NO trail) vs ctx (L1 + L2 + L3 regime-aware Chandelier). Gate metric = Δexpectancy (ctx − baseline); the
# policy's 4.5 gate wants ≥ +0.25R. NOTE: daily bars on liquid names — this tests the LAYERING MECHANICS,
# not the intraday micro-cap scalp regime (that is the §6 paper-trade gate). Advisory; no orders/config.
CTX_DEFAULTS = {"init_mult": 1.5, "be_r": 1.0, "activate_r": 1.5,
                "mult_trend": 3.0, "mult_mid": 2.0, "mult_range": 1.5}


def _simulate_ctx(df, ind, params, trail_enabled):
    import math
    closes = df["close"].values; highs = df["high"].values; lows = df["low"].values
    bo = ind["bo"].values; atr = ind["atr"].values
    adx = ind["adx"].values if ind["adx"] is not None else None
    im = params["init_mult"]; be_r = params["be_r"]; act_r = params["activate_r"]
    trades = []; i = 55; n = len(df)
    while i < n - 1:
        if math.isnan(bo[i]) or math.isnan(atr[i]) or closes[i] <= bo[i] or atr[i] <= 0:
            i += 1; continue
        entry = float(closes[i]); risk = im * float(atr[i]); stop = entry - risk
        if risk <= 0:
            i += 1; continue
        be_done = trail_on = False; hh = entry; exit_reason = "time"; rR = None; ei = i; j = i + 1
        while j < n:
            if lows[j] <= stop:
                rR = (stop - entry) / risk; exit_reason = ("stop_be" if be_done else "stop"); break
            px = float(closes[j]); hh = max(hh, float(highs[j])); R = (px - entry) / risk
            if not be_done and R >= be_r:                         # L2 breakeven
                stop = max(stop, entry); be_done = True
            if trail_enabled and be_done and R >= act_r:          # L3 delayed activation
                trail_on = True
            if trail_on:
                a = float(atr[j]) if not math.isnan(atr[j]) else float(atr[i])
                adv = adx[j] if (adx is not None and not math.isnan(adx[j])) else None
                mult = (params["mult_trend"] if (adv is not None and adv > 25)
                        else params["mult_range"] if (adv is not None and adv < 20) else params["mult_mid"])
                ts = hh - mult * a
                if ts > stop and ts < px:
                    stop = ts
            if j - ei >= MAX_HOLD:
                rR = (px - entry) / risk; exit_reason = "time"; break
            j += 1
        if rR is None:
            rR = (float(closes[-1]) - entry) / risk; exit_reason = "eod"; j = n - 1
        whip = bool(rR <= 0 and any(highs[k] > entry for k in range(j, min(j + WHIPSAW_LOOKAHEAD, n))))
        trades.append({"realized_R": round(rR, 3), "exit_reason": exit_reason, "hold": j - ei,
                       "whipsaw": whip, "trail_on": trail_on})
        i = j + 1
    return trades


def run_ctx(symbols, years, strategy, params):
    agg = {"base": [], "ctx": []}; rows = []
    for sym in symbols:
        df = _fetch(sym, years)
        if df is None:
            rows.append((sym, None, None)); continue
        ind = _indicators(df, {"atr_period": 14, "chandelier_lookback": 22})
        tb = _simulate_ctx(df, ind, params, trail_enabled=False)   # L1+L2, no trail (the gate baseline)
        tc = _simulate_ctx(df, ind, params, trail_enabled=True)    # L1+L2+L3 regime-aware trail
        agg["base"] += tb; agg["ctx"] += tc
        rows.append((sym, _metrics(tb), _metrics(tc)))
    return rows, {"base": _metrics(agg["base"]), "ctx": _metrics(agg["ctx"])}


def _fmt(m):
    if not m or m.get("trades", 0) == 0:
        return "   (no trades)"
    return (f"n={m['trades']:>3}  win={m['win_pct']:>5}%  exp={m['expectancy_R']:+.3f}R  "
            f"PF={m['profit_factor']:>4}  maxDD={m['max_dd_R']:>6}R  hold={m['avg_hold']:>4}  whip={m['whipsaws']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--strategy", default="swing_breakout")
    ap.add_argument("--algos", default="ma_trend_filter,chandelier,dynamic_multiplier",
                    help="comma list of overlay algos to enable")
    ap.add_argument("--base-atr-mult", type=float, default=3.0)
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "ctx"],
                    help="hybrid = STOP-V2.4 overlay A/B; ctx = context-aware layered policy re-test (Phase 2)")
    ap.add_argument("--init-mult", type=float, default=CTX_DEFAULTS["init_mult"])
    ap.add_argument("--be-r", type=float, default=CTX_DEFAULTS["be_r"])
    ap.add_argument("--activate-r", type=float, default=CTX_DEFAULTS["activate_r"])
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]

    if a.mode == "ctx":
        params = {**CTX_DEFAULTS, "init_mult": a.init_mult, "be_r": a.be_r, "activate_r": a.activate_r}
        print(f"\nCONTEXT-AWARE LAYERED re-test — {a.strategy} · init={params['init_mult']}xATR · "
              f"BE@+{params['be_r']}R · trail@+{params['activate_r']}R · regime mult "
              f"{params['mult_range']}/{params['mult_mid']}/{params['mult_trend']} · {a.years}y\n"
              f"baseline = L1 stop + L2 breakeven (NO trail) · ctx = + L3 regime Chandelier\n")
        rows, totals = run_ctx(syms, a.years, a.strategy, params)
        for sym, mb, mc in rows:
            print(f"── {sym}")
            if mb is None:
                print("   (no data)"); continue
            print(f"   base: {_fmt(mb)}")
            print(f"   ctx : {_fmt(mc)}")
        print("\n══ AGGREGATE ═════════════════════════════════════════════════════════════════")
        b, c = totals["base"], totals["ctx"]
        print(f"   baseline (no trail): {_fmt(b)}")
        print(f"   ctx (regime trail) : {_fmt(c)}")
        if b.get("trades") and c.get("trades"):
            de = c["expectancy_R"] - b["expectancy_R"]
            dd_ok = c["max_dd_R"] >= b["max_dd_R"] - 0.01
            pf_ok = c["profit_factor"] >= b["profit_factor"] - 0.01
            gate = de >= 0.25 and dd_ok and pf_ok      # the policy §6 gate: ≥ +0.25R from trailing
            verdict = ("PASS GATE — layered trailing adds ≥ +0.25R; clears the §6 trailing gate (still "
                       "needs the intraday paper sample)" if gate else
                       f"FAIL GATE — trailing Δ={de:+.3f}R < +0.25R; keep Layer-3 OFF (confirms STOP-V2.4 prior)")
            print(f"\n   Δexpectancy (ctx − baseline) = {de:+.3f}R/trade · drawdown_ok={dd_ok} · pf_ok={pf_ok}")
            print(f"   §6 GATE (≥ +0.25R): {verdict}")
        print("\n   Daily bars on liquid names — tests the LAYERING mechanics, NOT the intraday micro-cap")
        print("   scalp regime. Real validation = the 150-trade paper gate (policy §6). Advisory only.\n")
        return

    algos = tuple(s.strip() for s in a.algos.split(",") if s.strip())
    print(f"\nSTOP-V2.4 (hybrid) vs V2.3 (R-multiple) — {a.strategy} · algos={algos} · "
          f"mult={a.base_atr_mult} · {a.years}y · 20d-breakout entries\n")
    rows, totals = run(syms, a.years, a.strategy, algos=algos, base_atr_mult=a.base_atr_mult)
    for sym, m23, m24 in rows:
        print(f"── {sym}")
        if m23 is None:
            print("   (no data)"); continue
        print(f"   V2.3: {_fmt(m23)}")
        print(f"   V2.4: {_fmt(m24)}")
    print("\n══ AGGREGATE ═════════════════════════════════════════════════════════════════")
    t23, t24 = totals["v23"], totals["v24"]
    print(f"   V2.3: {_fmt(t23)}")
    print(f"   V2.4: {_fmt(t24)}")
    if t23.get("trades") and t24.get("trades"):
        de = t24["expectancy_R"] - t23["expectancy_R"]
        dd_ok = t24["max_dd_R"] >= t23["max_dd_R"] - 0.01      # drawdown not materially worse
        pf_ok = t24["profit_factor"] >= t23["profit_factor"] - 0.01
        verdict = ("PROMOTE — hybrid improves expectancy without worse drawdown/PF"
                   if de > 0.02 and dd_ok and pf_ok else
                   "HOLD — hybrid does not clearly beat R-multiple; keep config OFF")
        print(f"\n   Δexpectancy = {de:+.3f}R/trade · drawdown_ok={dd_ok} · pf_ok={pf_ok}")
        print(f"   VERDICT: {verdict}")
    print("\n   Advisory backtest — no orders, no config changes. Flip config/stop_trailing_hybrid.yaml")
    print("   only on a PROMOTE, and only per-family where it wins.\n")


if __name__ == "__main__":
    main()
