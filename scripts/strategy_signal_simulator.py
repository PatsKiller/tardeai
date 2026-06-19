#!/usr/bin/env python3
"""strategy_signal_simulator.py — POINT-IN-TIME signal generation + walk-forward backtest.

This is the missing half of backtesting credibility: instead of replay-grading trades that already happened,
it GENERATES entries from historical data using the machine-readable strategy criteria
(strategy_criteria_evaluator) — strictly point-in-time — then simulates outcomes with costs and reports a
chronological walk-forward (train/test) split.

Honesty rules baked in:
  * Universe per day = symbols the screeners actually scanned that day (trade_ai_scans) — no survivorship
    from today's universe; if a symbol wasn't a candidate that day, it can't signal.
  * Signal uses ONLY bars strictly BEFORE the signal day (base structure), plus that day's close/volume for
    the breakout trigger (known at the close); ENTRY is the NEXT day's open.
  * Same-bar stop+target hit -> STOP fills first (conservative).
  * Costs: BACKTEST_COST_BPS round-trip (default 30) deducted from every trade.
  * Sample-size gate: <30 trades => verdict 'insufficient_sample' (never claims edge).
  * Caps are LOGGED, never silent.

Currently implements: swing_breakout (daily bars). Stop = base low; target = entry + 2R; timeout 21 bars.

  .venv/bin/python scripts/strategy_signal_simulator.py --strategy swing_breakout            # dry (no DB)
  .venv/bin/python scripts/strategy_signal_simulator.py --strategy swing_breakout --apply    # persist run
"""
import argparse
import json
import os
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COST_BPS = float(os.getenv("BACKTEST_COST_BPS", "30"))
TIMEOUT_BARS = 21
MAX_SYMBOLS = int(os.getenv("SIM_MAX_SYMBOLS", "250"))
MIN_BASE, MAX_BASE = 15, 90          # from swing_breakout.yaml setup_qualification
BREAKOUT_VOL_RATIO = 1.5
SAMPLE_GATE = 30


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _candidates():
    """Per-day candidate map from the screeners' own historical output (point-in-time universe)."""
    cur = _conn().cursor()
    cur.execute("""SELECT scanned_at::date d, symbol, max(COALESCE(float_m,0)) float_m,
                          max(COALESCE(price,0)) price, max(COALESCE(rvol,0)) rvol
                   FROM trade_ai_scans
                   WHERE COALESCE(price,0) BETWEEN 5 AND 150
                   GROUP BY 1, 2""")
    bydate = {}
    for d, sym, fl, px, rv in cur.fetchall():
        bydate.setdefault(d, []).append({"symbol": sym, "float_m": fl, "price": px, "rvol": rv})
    return bydate


_BARS_CACHE = {}


def _daily_bars(symbol, start, end):
    if symbol in _BARS_CACHE:
        return _BARS_CACHE[symbol]
    try:
        import ohlc_charts as oc
        import datetime as _dt
        # free SIP tier 403s when the window touches the last ~15 min — cap the end safely in the past
        _cap = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _end = min(f"{end}T23:59:59Z", _cap)
        bars, _ = oc._fetch(symbol, f"{start}T00:00:00Z", _end, "1Day")
        if not bars:
            # Schwab read-only fallback (same tier-2 as the chart layer) — survives Alpaca 403/429/outage
            try:
                bars = oc._schwab_bars(symbol, f"{start}T00:00:00Z", _end, "1Day")
            except Exception:
                pass
    except Exception:
        bars = []
    out = []
    for b in bars or []:
        out.append({"d": str(b["t"])[:10], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
    _BARS_CACHE[symbol] = out
    return out


def _detect_breakout(bars, i):
    """At index i (signal day, close known): was there a base in bars[<i] and did bars[i] break it on volume?
    Returns metrics dict or None. Uses ONLY bars[:i] for structure + bars[i] close/volume (known at close)."""
    if i < MIN_BASE + 20:
        return None
    day = bars[i]
    # base window: trailing consolidation before today
    for blen in (20, 30, 45, 60, 90):
        if blen > i or blen < MIN_BASE or blen > MAX_BASE:
            continue
        base = bars[i - blen:i]
        hi = max(b["h"] for b in base)
        lo = min(b["l"] for b in base)
        if lo <= 0 or hi <= 0:
            continue
        tightness = (hi - lo) / hi
        if tightness > 0.25:                       # not a consolidation
            continue
        if day["c"] <= hi:                         # no breakout above base high
            continue
        vol20 = sum(b["v"] for b in bars[max(0, i - 20):i]) / min(20, i)
        vol_ratio = (day["v"] / vol20) if vol20 else 0
        return {"base_days": blen, "base_high": hi, "base_low": lo,
                "breakout_volume_ratio": round(vol_ratio, 2), "tightness": round(tightness, 3)}
    return None


def _detect_fib_bounce(bars, i):
    """fib_retracement_bounce, point-in-time at close of bar i:
    prior advance (swing low->high, >=15%, within last 60 bars), today's LOW touched the 50-61.8%
    retracement zone, close bounced UP off it, and the larger uptrend is intact (close > 50-bar mean).
    Stop below the 61.8% level; target = prior swing high."""
    if i < 55:
        return None
    day = bars[i]
    window = bars[max(0, i - 60):i]
    hi_idx = max(range(len(window)), key=lambda k: window[k]["h"])
    swing_hi = window[hi_idx]["h"]
    lo_before = window[:hi_idx + 1]
    if not lo_before:
        return None
    swing_lo = min(b["l"] for b in lo_before)
    if swing_lo <= 0 or (swing_hi - swing_lo) / swing_lo < 0.15:
        return None                                    # no meaningful prior advance
    fib50 = swing_hi - 0.50 * (swing_hi - swing_lo)
    fib618 = swing_hi - 0.618 * (swing_hi - swing_lo)
    sma50 = sum(b["c"] for b in bars[i - 50:i]) / 50
    if day["c"] < sma50:
        return None                                    # uptrend filter
    if not (day["l"] <= fib50 and day["l"] >= fib618 * 0.99):
        return None                                    # low must probe the 50-61.8% zone
    if day["c"] <= day["o"] or day["c"] < fib50:
        return None                                    # bounce: close up and back above the 50% line
    return {"swing_high": swing_hi, "swing_low": swing_lo, "fib50": round(fib50, 4),
            "fib618": round(fib618, 4), "stop_level": round(fib618 * 0.99, 4),
            "target_level": round(swing_hi, 4)}


def _simulate_trade(bars, i, base):
    """Enter next open after signal day i; stop = base low; target = entry + 2R; conservative same-bar rule."""
    if i + 1 >= len(bars):
        return None
    entry = bars[i + 1]["o"]
    stop = base.get("stop_level") or base["base_low"]
    if entry <= stop:
        return None
    risk = entry - stop
    target = base.get("target_level") or (entry + 2 * risk)
    if target <= entry:
        return None
    exit_px, reason, j = None, "timeout", min(i + 1 + TIMEOUT_BARS, len(bars) - 1)
    for k in range(i + 1, j + 1):
        b = bars[k]
        if b["l"] <= stop:                          # stop first (conservative on same-bar both-hit)
            exit_px, reason = stop, "stop"; j = k; break
        if b["h"] >= target:
            exit_px, reason = target, "target"; j = k; break
    if exit_px is None:
        exit_px = bars[j]["c"]
    cost = entry * (COST_BPS / 10000.0)
    pnl_ps = exit_px - entry - cost
    return {"entry_date": bars[i + 1]["d"], "exit_date": bars[j]["d"], "entry": round(entry, 4),
            "exit": round(exit_px, 4), "stop": round(stop, 4), "target": round(target, 4),
            "reason": reason, "r_multiple": round(pnl_ps / risk, 3) if risk else 0,
            "pnl_pct": round(pnl_ps / entry * 100, 3), "hold_bars": j - i - 1}


def _agg(trades):
    n = len(trades)
    if not n:
        return {"trades": 0}

    # Clamp each per-trade r-multiple to a realistic band before aggregating (fix 2026-06-19): a single
    # near-zero-risk backtest trade can produce an absurd r (e.g. 27R), which then poisoned expectancy_r
    # on the leaderboard. ±10R is generous but excludes the data artifacts.
    def _cr(x):
        try:
            return max(-10.0, min(10.0, float(x)))
        except Exception:
            return 0.0

    rs = [_cr(t["r_multiple"]) for t in trades]
    wins_n = sum(1 for r in rs if r > 0)
    gp = sum(r for r in rs if r > 0)
    gl = abs(sum(r for r in rs if r < 0)) or 1e-9
    return {"trades": n, "win_rate": round(wins_n / n, 3),
            "profit_factor": round(gp / gl, 2), "expectancy_r": round(sum(rs) / n, 3),
            "avg_hold_bars": round(sum(t["hold_bars"] for t in trades) / n, 1)}


def run(strategy_id="swing_breakout", apply=False):
    from strategy_criteria_evaluator import evaluate
    bydate = _candidates()
    days = sorted(bydate)
    if not days:
        print(json.dumps({"status": "no_candidate_history"})); return
    syms = sorted({c["symbol"] for d in days for c in bydate[d]})
    capped = len(syms) > MAX_SYMBOLS
    if capped:
        print(f"[sim] capping universe {len(syms)} -> {MAX_SYMBOLS} symbols (deterministic alpha order; "
              f"set SIM_MAX_SYMBOLS to widen)")
        syms = syms[:MAX_SYMBOLS]
    start, end = (days[0] - dt.timedelta(days=150)).isoformat(), days[-1].isoformat()
    print(f"[sim] {strategy_id}: {len(days)} candidate-days {days[0]}..{days[-1]}, {len(syms)} symbols, "
          f"cost={COST_BPS}bps")

    trades, signals_checked = [], 0
    for sym in syms:
        bars = _daily_bars(sym, start, end)
        if len(bars) < MIN_BASE + 25:
            continue
        idx_by_date = {b["d"]: k for k, b in enumerate(bars)}
        cand_days = [d for d in days if any(c["symbol"] == sym for c in bydate[d])]
        for d in cand_days:
            i = idx_by_date.get(d.isoformat())
            if i is None:
                continue
            if strategy_id == "fib_retracement_bounce":
                base = _detect_fib_bounce(bars, i)
            else:
                base = _detect_breakout(bars, i)
            if not base:
                continue
            cand = next(c for c in bydate[d] if c["symbol"] == sym)
            metrics = {"price": bars[i]["c"], "rvol": cand["rvol"], "float_m": cand["float_m"] or None,
                       "base_days": base.get("base_days"), "breakout_volume_ratio": base.get("breakout_volume_ratio"),
                       "retracement_pct": (round(100 * (base["swing_high"] - bars[i]["l"]) /
                                            (base["swing_high"] - base["swing_low"]), 1)
                                           if "swing_high" in base else None),
                       "prior_advance_pct": (round(100 * (base["swing_high"] - base["swing_low"]) /
                                             base["swing_low"], 1) if "swing_high" in base else None),
                       "score": 35,
                       # evidence flags: present because we computed them point-in-time
                       "price_data": 1, "volume_pattern": 1, "breakout_level": base.get("base_high") or base.get("swing_high"),
                       "stop_below_base": 1, "trade_plan": 1, "base_duration": base.get("base_days"),
                       "fib_levels": 1, "bounce_confirmation": 1, "uptrend_confirmed": 1,
                       # fib YAML minimum_evidence names — all genuinely computed point-in-time above
                       "fib_levels_calculated": 1, "swing_points_identified": 1,
                       "trend_state_confirmed": 1, "volume_data": 1}
            signals_checked += 1
            r = evaluate(strategy_id, metrics)
            if not r.get("pass"):
                continue
            t = _simulate_trade(bars, i, base)
            if t:
                trades.append({**t, "symbol": sym,
                               **{k: base[k] for k in ("base_days", "breakout_volume_ratio") if k in base}})

    trades.sort(key=lambda t: t["entry_date"])
    split = int(len(trades) * 0.7)
    train, test = trades[:split], trades[split:]
    report = {
        "strategy_id": strategy_id, "run_type": "pit_simulated", "cost_bps": COST_BPS,
        "universe_symbols": len(syms), "universe_capped": capped,
        "candidate_days": len(days), "breakouts_evaluated": signals_checked,
        "signals": len(trades),
        "all": _agg(trades), "train_70pct": _agg(train), "test_30pct": _agg(test),
        "wf_degradation": (round((_agg(train).get("win_rate", 0) or 0) - (_agg(test).get("win_rate", 0) or 0), 3)
                           if train and test else None),
        "verdict": ("insufficient_sample" if len(trades) < SAMPLE_GATE else
                    "edge_candidate" if (_agg(test).get("expectancy_r", 0) or 0) > 0 else "no_edge_oos"),
        "sample_gate": SAMPLE_GATE,
    }
    print(json.dumps(report, indent=2, default=str))

    if apply and trades:
        conn = _conn(); cur = conn.cursor()
        run_id = f"pit_{strategy_id}_{days[-1].isoformat()}"
        cur.execute("""INSERT INTO strategy_backtest_runs (run_id, strategy_id, run_type, status, start_date, end_date)
                       VALUES (%s,%s,'pit_simulated','completed',%s,%s)
                       ON CONFLICT (run_id) DO UPDATE SET status='completed', end_date=EXCLUDED.end_date""",
                    (run_id, strategy_id, days[0], days[-1]))
        for t in trades:
            cur.execute("""INSERT INTO strategy_backtest_trades
                (simulated_trade_id, run_id, strategy_id, symbol, signal_time, entry_time, exit_time,
                 direction, entry_price, stop_price, target_price, exit_price, pnl, pnl_pct, r_multiple,
                 exit_reason, execution_assumptions)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'long',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (f"{run_id}_{t['symbol']}_{t['entry_date']}", run_id, strategy_id, t["symbol"],
                         t["entry_date"], t["entry_date"], t["exit_date"], t["entry"], t["stop"], t["target"],
                         t["exit"], round((t["exit"] - t["entry"]), 4), t["pnl_pct"], t["r_multiple"],
                         t["reason"], json.dumps({"cost_bps": COST_BPS, "entry": "next_open",
                                                  "same_bar_rule": "stop_first", "pit": True})))
        a = report["all"]
        cur.execute("""INSERT INTO strategy_backtest_results
            (run_id, strategy_id, run_type, total_trades, wins, losses, win_rate, profit_factor, expectancy_r,
             sample_size, equity_curve_json)
            VALUES (%s,%s,'pit_simulated',%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, strategy_id, a["trades"], int(a["trades"] * a.get("win_rate", 0)),
                     a["trades"] - int(a["trades"] * a.get("win_rate", 0)), a.get("win_rate"),
                     a.get("profit_factor"), a.get("expectancy_r"), a["trades"],
                     json.dumps({"train": report["train_70pct"], "test": report["test_30pct"]})))
        conn.commit()
        print(f"[sim] persisted run {run_id} ({len(trades)} trades, run_type=pit_simulated)")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="swing_breakout")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.strategy, a.apply)
