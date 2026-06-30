#!/usr/bin/env python3
"""scalp_stop_validation_tracker.py — the 4.4->4.5 stop/trail validation gate (read-only, advisory).

Measures the MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY §6 metrics over CLOSED momentum_scalp paper trades
(the ACTIVE layers: L1 initial ATR/structure stop + L2 breakeven). The Layer-3 trailing metric is NOT
computed here — Phase 2 backtest + the 27-config sweep showed trailing is net-negative for momentum
(Δ -0.13..-0.87R), so it stays config-OFF; this tracker gates the layers we actually run.

Honest about sample size: the gate needs >=150 closed trades; reports INSUFFICIENT until then.

  python3 scripts/scalp_stop_validation_tracker.py [--strategy momentum_scalp] [--json|--markdown]
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# §6 gate (policy). trailing-R-improvement is excluded — measured by the backtest, currently negative.
GATE = {
    "closed_trades": (">=", 150), "win_pct": (">=", 58.0), "expectancy_R": (">=", 0.35),
    "profit_factor": (">=", 1.65), "max_dd_R_floor": (">=", -4.5 / 1.0),  # informational
}
MIN_SAMPLE = 30   # below this, every verdict is INSUFFICIENT regardless of value


def _r(entry, exit_, stop):
    try:
        e = float(entry); x = float(exit_); s = float(stop)
        risk = e - s
        if risk <= 0:
            return None
        return (x - e) / risk
    except Exception:
        return None


def run(strategy="momentum_scalp"):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT symbol, entry_price, exit_price, planned_stop, stop_loss_price, exit_reason,
                          market_regime, max_adverse_excursion, recommendation_to_entry_seconds,
                          breakeven_trigger_r, final_r_vs_planned_stop, pnl
                   FROM paper_trades
                   WHERE strategy_id=%s AND (lifecycle_state='closed' OR status='closed')
                     AND exit_price IS NOT NULL AND entry_price IS NOT NULL
                     AND exit_reason NOT IN ('duplicate_of_22','dedup_removed','cancelled')""", (strategy,))
    rows = cur.fetchall()
    trades, no_risk = [], 0
    for (sym, e, x, pstop, sloss, reason, regime, mae, rec_s, be_r, fvp, pnl) in rows:
        r = _r(e, x, pstop if pstop is not None else sloss)
        if r is None:
            no_risk += 1; continue
        trades.append({"symbol": sym, "R": r, "reason": reason, "regime": regime,
                       "mae": float(mae) if mae is not None else None,
                       "rec_s": int(rec_s) if rec_s is not None else None,
                       "be_r": float(be_r) if be_r is not None else None})
    n = len(trades)
    rs = [t["R"] for t in trades]
    wins = [r for r in rs if r > 0]; losses = [r for r in rs if r < 0]
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    m = {
        "closed_trades": n, "tagged_no_risk_denominator": no_risk,
        "win_pct": round(100 * len(wins) / n, 1) if n else None,
        "expectancy_R": round(sum(rs) / n, 3) if n else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else (float("inf") if wins else None),
        "max_dd_R": round(mdd, 2),
        "by_regime": {}, "freshness_tagged": sum(1 for t in trades if t["rec_s"] is not None),
        "breakeven_tagged": sum(1 for t in trades if t["be_r"] is not None),
        "mae_tagged": sum(1 for t in trades if t["mae"] is not None),
    }
    for reg in set(t["regime"] or "unknown" for t in trades):
        rr = [t["R"] for t in trades if (t["regime"] or "unknown") == reg]
        m["by_regime"][reg] = {"n": len(rr), "exp_R": round(sum(rr) / len(rr), 3) if rr else None}
    # gate verdicts (INSUFFICIENT below MIN_SAMPLE)
    verdicts = {}
    for key, (op, tgt) in (("closed_trades", GATE["closed_trades"]), ("win_pct", GATE["win_pct"]),
                           ("expectancy_R", GATE["expectancy_R"]), ("profit_factor", GATE["profit_factor"])):
        val = m.get(key)
        if key != "closed_trades" and n < MIN_SAMPLE:
            verdicts[key] = f"INSUFFICIENT ({n}/{MIN_SAMPLE} min sample)"
        elif val is None:
            verdicts[key] = "NO DATA"
        else:
            ok = (val >= tgt)
            verdicts[key] = f"{'PASS' if ok else 'FAIL'} ({val} vs {op}{tgt})"
    overall = ("INSUFFICIENT SAMPLE — gate needs >=150 closed trades" if n < 150
               else "PASS" if all("PASS" in v for v in verdicts.values()) else "FAIL")
    return {"strategy": strategy, "metrics": m, "gate_verdicts": verdicts, "overall": overall,
            "trailing_note": "Layer-3 trailing excluded — backtest+sweep show net-negative for momentum "
                             "(stays config-OFF); see MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY §2.",
            "advisory_only": True}


def _md(d):
    m = d["metrics"]; L = [f"# Scalp Stop Validation — {d['strategy']}", "",
                           f"**Overall:** {d['overall']}  ·  closed trades **{m['closed_trades']}**/150 gate",
                           f"_{d['trailing_note']}_", "", "| Metric | Value | Gate | Verdict |", "|---|---|---|---|"]
    for k in ("closed_trades", "win_pct", "expectancy_R", "profit_factor"):
        L.append(f"| {k} | {m.get(k)} | {GATE.get(k, ('','-'))[0]}{GATE.get(k,('','-'))[1]} | {d['gate_verdicts'].get(k,'')} |")
    L += [f"| max_dd_R | {m['max_dd_R']} | informational | — |", "",
          f"Tagging coverage: freshness {m['freshness_tagged']}/{m['closed_trades']} · "
          f"breakeven {m['breakeven_tagged']} · MAE {m['mae_tagged']} · "
          f"(trades with no risk denominator excluded: {m['tagged_no_risk_denominator']})", "",
          "By regime: " + ", ".join(f"{k} n={v['n']} exp={v['exp_R']}R" for k, v in m["by_regime"].items()),
          "", "_Advisory / read-only. No orders, no config changes._"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="momentum_scalp")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    d = run(a.strategy)
    print(_md(d) if a.markdown else json.dumps(d, indent=2, default=str))


if __name__ == "__main__":
    main()
