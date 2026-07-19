#!/usr/bin/env python3
"""inverse_hedge_backtest.py — pre-registered two-day-entry study (spec:
docs/_findings/INVERSE_HEDGE_TWODAY_PREREGISTRATION_2026-07-19.md @ f2988645).

Reproducible: data fetched from the Schwab daily-history API (split-adjusted),
cached to data/research/inverse_hedge_history.json; every rule and threshold
comes from the pre-registered grid. Walk-forward: select on SPY/SH 2006-2015,
FREEZE, evaluate 2016-2020 and 2021-2026 out-of-sample, all four pairs.

Usage:
  inverse_hedge_backtest.py --fetch          # refresh the data cache
  inverse_hedge_backtest.py --run            # train + OOS evaluation
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CACHE = ROOT / "data" / "research" / "inverse_hedge_history.json"
PAIRS = [("SPY", "SH"), ("QQQ", "PSQ"), ("DIA", "DOG"), ("IWM", "RWM")]
FRICTION_BP = 3          # per side, pre-registered
EXPENSE_ANNUAL = 0.009   # 0.90%/yr while held
HEDGE_WEIGHT = 0.04      # 4% of equity overlay for portfolio metrics
MIN_N = 30


def fetch():
    import schwab_transport as st
    out = {}
    for sym in {s for p in PAIRS for s in p}:
        bars = st.get_price_history(sym, "2006-01-01", "2026-07-18")
        out[sym] = [{"d": b["datetime"][:10], "o": b["open"], "h": b["high"],
                     "l": b["low"], "c": b["close"]} for b in bars]
        print(sym, len(out[sym]), "bars", out[sym][0]["d"], "→", out[sym][-1]["d"])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out))
    print("cached →", CACHE)


def _series(sym):
    data = json.loads(CACHE.read_text())[sym]
    return data


def _indicators(bars):
    n = len(bars)
    c = [b["c"] for b in bars]
    atr, ma20, ma50, slope50, ret = [None] * n, [None] * n, [None] * n, [None] * n, [None] * n
    trs = []
    for i in range(n):
        if i:
            tr = max(bars[i]["h"] - bars[i]["l"], abs(bars[i]["h"] - c[i - 1]),
                     abs(bars[i]["l"] - c[i - 1]))
            trs.append(tr)
            ret[i] = (c[i] / c[i - 1] - 1) * 100
            if len(trs) >= 14:
                atr[i] = sum(trs[-14:]) / 14
        if i >= 19:
            ma20[i] = sum(c[i - 19:i + 1]) / 20
        if i >= 49:
            ma50[i] = sum(c[i - 49:i + 1]) / 50
        if i >= 59 and ma50[i] and ma50[i - 10]:
            slope50[i] = ma50[i] - ma50[i - 10]
    return {"c": c, "ret": ret, "atr": atr, "ma20": ma20, "ma50": ma50, "slope50": slope50}


def _thesis(ind, i):
    """Pre-registered proxy: c<50DMA AND 50DMA slope<0 AND c<c[-20]."""
    if ind["ma50"][i] is None or ind["slope50"][i] is None or i < 20:
        return False
    return (ind["c"][i] < ind["ma50"][i] and ind["slope50"][i] < 0
            and ind["c"][i] < ind["c"][i - 20])


def _thesis_exit(ind, i):
    """Two consecutive closes above the 50DMA."""
    return (i >= 1 and ind["ma50"][i] and ind["ma50"][i - 1]
            and ind["c"][i] > ind["ma50"][i] and ind["c"][i - 1] > ind["ma50"][i - 1])


def simulate(bench_bars, inv_bars, arm: str, p: dict) -> list[dict]:
    """One arm over one pair. Returns completed trades with hedge-first stats.
    arm: 'baseline' | 'twoday' | 'untimed' (enter at thesis-GREEN immediately)."""
    dates_b = {b["d"]: i for i, b in enumerate(bench_bars)}
    inv_by_date = {b["d"]: b["c"] for b in inv_bars}
    ind = _indicators(bench_bars)
    trades = []
    pos = None
    green = False
    for i, b in enumerate(bench_bars):
        d = b["d"]
        if d not in inv_by_date:
            continue
        was_green = green
        green = _thesis(ind, i) if not green else not _thesis_exit(ind, i)
        # exits first
        if pos:
            inv_px = inv_by_date[d]
            gain = inv_px / pos["inv_entry"] - 1
            held = i - pos["i0"]
            exit_reason = None
            if not green:
                exit_reason = "thesis_exit"
            elif p.get("max_hold") and held >= p["max_hold"]:
                exit_reason = "max_hold"
            elif p.get("tp_mode") == "inverse_fixed":
                if not pos.get("tp1_done") and gain >= 0.08:
                    pos["tp1_done"] = True
                    pos["realized_half"] = gain
                if gain >= 0.15:
                    exit_reason = "tp2"
            elif p.get("tp_mode") == "underlying_atr":
                if ind["atr"][i] and (ind["c"][pos["i0"]] - ind["c"][i]) >= 1.5 * ind["atr"][pos["i0"]]:
                    exit_reason = "atr_objective"
                elif ind["c"][i] > ind["c"][pos["i0"]] + 1.5 * (ind["atr"][pos["i0"]] or 0):
                    exit_reason = "underlying_stop"
            if exit_reason:
                friction = 2 * FRICTION_BP / 1e4 + EXPENSE_ANNUAL * held / 252
                if pos.get("tp1_done"):
                    net = 0.5 * pos["realized_half"] + 0.5 * gain - friction
                else:
                    net = gain - friction
                # avoided adverse entry excursion: benchmark move 5 sessions after entry
                j5 = min(pos["i0"] + 5, len(bench_bars) - 1)
                aae = (ind["c"][j5] / ind["c"][pos["i0"]] - 1) * 100
                trades.append({"entry": pos["d0"], "exit": d, "held": held,
                               "inv_net_ret": net, "exit_reason": exit_reason,
                               "bench_5d_after_entry_pct": aae,
                               "whipsaw": exit_reason == "thesis_exit" and held <= 3 and net < 0})
                pos = None
        # entries
        if pos is None and green and ind["atr"][i]:
            r1, r0 = ind["ret"][i], ind["ret"][i - 1] if i else None
            enter = False
            if arm == "untimed" and not was_green:
                enter = True
            elif arm == "baseline" and r1 is not None and r1 >= 0.75:
                enter = True
            elif arm == "twoday" and r1 is not None and r0 is not None:
                two = (1 + r0 / 100) * (1 + r1 / 100) - 1
                atr_norm = (ind["c"][i] - ind["c"][i - 2]) / ind["atr"][i]
                enter = (r0 > p["min_daily"] and r1 > p["min_daily"]
                         and two * 100 >= p["min_cum"]
                         and atr_norm >= p["min_atr"]
                         and atr_norm <= p["chase_atr"]
                         and not (p.get("trend_veto") and ind["ma50"][i] and ind["c"][i] > ind["ma50"][i]))
            if enter:
                pos = {"d0": d, "i0": i, "inv_entry": inv_by_date[d]}
    return trades


def overlay_metrics(bench_bars, inv_bars, trades) -> dict:
    """Pre-registered primary metrics: portfolio MDD reduction, downside beta,
    downside capture — proxy book = 100% benchmark long, hedged at HEDGE_WEIGHT
    in the ACTUAL inverse ETF while a position is open."""
    if not trades:
        return {}
    dates_open = set()
    idx = {b["d"]: i for i, b in enumerate(bench_bars)}
    for t in trades:
        i0, i1 = idx.get(t["entry"]), idx.get(t["exit"])
        if i0 is None or i1 is None:
            continue
        for i in range(i0, i1 + 1):
            dates_open.add(bench_bars[i]["d"])
    inv_by = {b["d"]: b["c"] for b in inv_bars}
    base_eq = hedged_eq = 1.0
    base_curve, hedged_curve, br_list, hr_list = [], [], [], []
    prev_b = prev_i = None
    for b in bench_bars:
        d, c = b["d"], b["c"]
        iv = inv_by.get(d)
        if prev_b is not None:
            rb = c / prev_b - 1
            ri = (iv / prev_i - 1) if (iv and prev_i) else -rb
            rh = rb + (HEDGE_WEIGHT * ri if d in dates_open else 0.0)
            base_eq *= (1 + rb)
            hedged_eq *= (1 + rh)
            base_curve.append(base_eq)
            hedged_curve.append(hedged_eq)
            br_list.append(rb)
            hr_list.append(rh)
        prev_b, prev_i = c, iv if iv else prev_i

    def mdd(curve):
        peak, worst = -1e9, 0.0
        for v in curve:
            peak = max(peak, v)
            worst = min(worst, v / peak - 1)
        return worst
    downs = [(br_list[i], hr_list[i]) for i in range(len(br_list)) if br_list[i] < 0]
    if downs:
        mb = sum(x for x, _ in downs) / len(downs)
        mh = sum(y for _, y in downs) / len(downs)
        var_b = sum((x - mb) ** 2 for x, _ in downs) / len(downs)
        cov = sum((x - mb) * (y - mh) for x, y in downs) / len(downs)
        dbeta = cov / var_b if var_b else None
        dcapture = mh / mb if mb else None
    else:
        dbeta = dcapture = None
    return {"mdd_base_pct": round(100 * mdd(base_curve), 2),
            "mdd_hedged_pct": round(100 * mdd(hedged_curve), 2),
            "mdd_reduction_pp": round(100 * (mdd(base_curve) - mdd(hedged_curve)) * -1, 2),
            "downside_beta_hedged": round(dbeta, 3) if dbeta is not None else None,
            "downside_capture_hedged": round(dcapture, 3) if dcapture is not None else None}


def metrics(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "verdict": "INSUFFICIENT N"}
    rets = [t["inv_net_ret"] for t in trades]
    aae = [t["bench_5d_after_entry_pct"] for t in trades]
    m = {"n": n,
         "avg_inv_net_ret_pct": round(100 * sum(rets) / n, 2),
         "win_rate_pct": round(100 * sum(1 for r in rets if r > 0) / n, 1),
         "avg_held_sessions": round(sum(t["held"] for t in trades) / n, 1),
         "whipsaw_rate_pct": round(100 * sum(1 for t in trades if t["whipsaw"]) / n, 1),
         # AAE: mean benchmark move 5d after entry — MORE NEGATIVE = better timing
         "avg_bench_5d_after_entry_pct": round(sum(aae) / n, 2),
         "hedge_efficiency_per_day": round(100 * sum(rets) / max(1, sum(t["held"] for t in trades)), 3)}
    if n < MIN_N:
        m["verdict"] = "INSUFFICIENT N"
    return m


GRID = [dict(min_daily=md, min_cum=mc, min_atr=ma, chase_atr=ca, trend_veto=True,
             max_hold=mh, tp_mode=tp)
        for md in (0.0, 0.25, 0.50, 0.75)
        for mc in (0.75, 1.00, 1.50)
        for ma in (0.50, 0.75, 1.00)
        for ca in (1.5, 2.0)
        for mh in (5, 10, 15, 20)
        for tp in ("inverse_fixed", "underlying_atr")]


def run():
    bench = {s: _series(s) for s, _ in PAIRS}
    inv = {v: _series(v) for _, v in PAIRS}

    def window(bars, lo, hi):
        return [b for b in bars if lo <= b["d"] <= hi]

    # TRAIN: SPY/SH 2006-2015 — rank by pre-registered order (AAE improvement,
    # then whipsaw, then efficiency)
    tb, ti = window(bench["SPY"], "2006-01-01", "2015-12-31"), window(inv["SH"], "2006-01-01", "2015-12-31")
    base_train = metrics(simulate(tb, ti, "baseline", dict(max_hold=20, tp_mode="inverse_fixed")))
    scored = []
    for g in GRID:
        m = metrics(simulate(tb, ti, "twoday", g))
        if m["n"] == 0:
            continue
        scored.append((m.get("avg_bench_5d_after_entry_pct", 9), m.get("whipsaw_rate_pct", 99),
                       -m.get("hedge_efficiency_per_day", -9), g, m))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    best = scored[0]
    frozen = best[3]
    report = {"preregistration": "f2988645",
              "train_SPY_2006_2015": {"baseline": base_train, "best_twoday": best[4],
                                      "frozen_params": frozen},
              "oos": {}}
    # OOS: frozen params, all pairs, both windows + the untimed comparator
    for lo, hi, label in (("2016-01-01", "2020-12-31", "2016_2020"),
                          ("2021-01-01", "2026-07-18", "2021_2026")):
        for bsym, isym in PAIRS:
            key = f"{label}:{bsym}/{isym}"
            wb, wi = window(bench[bsym], lo, hi), window(inv[isym], lo, hi)
            tb_ = simulate(wb, wi, "baseline", dict(max_hold=20, tp_mode="inverse_fixed"))
            tt_ = simulate(wb, wi, "twoday", frozen)
            tu_ = simulate(wb, wi, "untimed", dict(max_hold=20, tp_mode="inverse_fixed"))
            report["oos"][key] = {
                "baseline": {**metrics(tb_), **overlay_metrics(wb, wi, tb_)},
                "twoday_frozen": {**metrics(tt_), **overlay_metrics(wb, wi, tt_)},
                "untimed": {**metrics(tu_), **overlay_metrics(wb, wi, tu_)},
            }
    out = ROOT / "data" / "research" / "inverse_hedge_results.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report["train_SPY_2006_2015"], indent=1))
    agg = {"baseline": [], "twoday_frozen": [], "untimed": []}
    for k, v in report["oos"].items():
        for arm in agg:
            if v[arm]["n"]:
                agg[arm].append(v[arm])
    print("\nOOS aggregate — SIGNAL-WEIGHTED (validator correction: cells weighted by n):")
    for arm, ms in agg.items():
        if ms:
            N = sum(m["n"] for m in ms)
            w = lambda k: sum(m[k] * m["n"] for m in ms if m.get(k) is not None) / N
            print(f"  {arm:14} n_total={N:3} avg_ret={w('avg_inv_net_ret_pct'):+.2f}% "
                  f"whipsaw={w('whipsaw_rate_pct'):.1f}% AAE={w('avg_bench_5d_after_entry_pct'):+.2f}% "
                  f"eff/day={w('hedge_efficiency_per_day'):+.3f}")
            mm = [m for m in ms if m.get("mdd_reduction_pp") is not None]
            if mm:
                print(f"  {'':14} MDD_reduction={sum(m['mdd_reduction_pp'] for m in mm)/len(mm):+.2f}pp "
                      f"downside_beta={sum(m['downside_beta_hedged'] for m in mm if m['downside_beta_hedged'] is not None)/max(1,len([m for m in mm if m['downside_beta_hedged'] is not None])):.3f}")
    print("→", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    if a.run:
        run()
