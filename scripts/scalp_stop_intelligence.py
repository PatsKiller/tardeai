#!/usr/bin/env python3
"""scalp_stop_intelligence.py — replay "what-if" for a closed trade's stop/trail (read-only, advisory).

Backs the Trade-Detail Stop Intelligence panel: replays the trade's actual intrabar OHLC path
(trade_intrabar_bars) and computes what a 2x ATR trail and a Chandelier(22,3) trail WOULD have done vs
the ACTUAL exit, plus the theoretical-optimal exit. For momentum scalps this usually shows trailing LEAVES
MONEY ON THE TABLE (truncates the fat tail) — concrete per-trade evidence for keeping Layer-3 off.

  python3 scripts/scalp_stop_intelligence.py --trade-id N        (or --sample to pick one with bars)
ADVISORY / read-only — no orders, no config writes.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _atr(bars, i, period=14):
    j0 = max(1, i - period + 1)
    trs = [max(bars[k]["high"] - bars[k]["low"],
               abs(bars[k]["high"] - bars[k - 1]["close"]),
               abs(bars[k]["low"] - bars[k - 1]["close"])) for k in range(j0, i + 1)]
    return sum(trs) / len(trs) if trs else (bars[i]["high"] - bars[i]["low"])


def _walk(bars, entry, init_stop, mode, mult=2.0, chand_n=22):
    """Walk the path under a trailing mode; return (exit_price, exit_reason, exit_idx). mode: fixed|atr|chandelier."""
    stop = init_stop
    for i in range(len(bars)):
        b = bars[i]
        if b["low"] <= stop:
            return stop, f"{mode}_stop", i
        if mode in ("atr", "chandelier") and i >= 1:
            atr = _atr(bars, i)
            if mode == "atr":
                ts = b["high"] - mult * atr
            else:
                hh = max(x["high"] for x in bars[max(0, i - chand_n + 1):i + 1])
                ts = hh - 3.0 * atr
            if ts > stop and ts < b["close"]:
                stop = ts
    return bars[-1]["close"], "eod", len(bars) - 1


def whatif(trade_id):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    # trade_intrabar_bars.trade_instance_id references trade_instances.id (NOT paper_trades.id — different
    # id spaces). Load the trade from trade_instances so entry/symbol MATCH the bars; pull the stop +
    # regime from paper_trades via the shared trade_key.
    cur.execute("""SELECT ti.id, ti.symbol, ti.entry_price, ti.exit_price,
                          COALESCE(pt.planned_stop, pt.stop_loss_price) AS stop,
                          pt.exit_reason, pt.market_regime
                   FROM trade_instances ti
                   LEFT JOIN paper_trades pt ON pt.trade_key = ti.trade_key
                   WHERE ti.id=%s""", (trade_id,))
    t = cur.fetchone()
    if not t:
        return {"error": f"trade_instance {trade_id} not found"}
    tid, sym, entry, exit_, stop, reason, regime = t
    entry = float(entry); exit_ = float(exit_) if exit_ else None
    stop = float(stop) if stop else None
    cur.execute("""SELECT open, high, low, close FROM trade_intrabar_bars
                   WHERE trade_instance_id=%s ORDER BY bar_seq""", (trade_id,))
    raw = [{"open": float(o), "high": float(h), "low": float(l), "close": float(c)}
           for (o, h, l, c) in cur.fetchall()]
    if not raw:
        return {"error": f"no intrabar bars for trade {trade_id} (run ingest_trade_intrabar_bars)"}
    # sanity filter: drop corrupt bars (the table has occasional glitches — e.g. a $6.20 high on an NVDA
    # $218 trade). Keep bars within 0.5x..2x of entry with high>=low>0.
    bars = [b for b in raw if 0 < b["low"] <= b["high"] and 0.5 * entry <= b["low"] and b["high"] <= 2.0 * entry]
    dropped = len(raw) - len(bars)
    if not bars:
        return {"error": f"all {len(raw)} bars failed sanity (corrupt OHLC for trade {trade_id})"}
    if not stop or stop >= entry:
        stop = entry - (bars[0]["high"] - bars[0]["low"])    # fallback initial risk = bar-0 range
    risk = entry - stop
    def R(px): return round((px - entry) / risk, 2) if risk > 0 else None
    variants = {
        "actual": {"exit": exit_, "R": R(exit_) if exit_ else None, "reason": reason},
        "fixed_stop_no_trail": dict(zip(("exit", "reason", "idx"), _walk(bars, entry, stop, "fixed"))),
        "atr_2x_trail": dict(zip(("exit", "reason", "idx"), _walk(bars, entry, stop, "atr", mult=2.0))),
        "chandelier_22_3": dict(zip(("exit", "reason", "idx"), _walk(bars, entry, stop, "chandelier"))),
    }
    for k, v in variants.items():
        if "exit" in v and v["exit"] is not None and "R" not in v:
            v["R"] = R(float(v["exit"]))
    opt_px = max(b["high"] for b in bars)
    return {"trade_id": tid, "symbol": sym, "regime": regime, "entry": entry, "initial_stop": round(stop, 2),
            "risk_per_share": round(risk, 3), "bars": len(bars), "bars_dropped_corrupt": dropped,
            "optimal_exit": {"price": round(opt_px, 2), "R": R(opt_px)}, "variants": variants,
            "verdict": _verdict(variants), "note": "advisory replay · Layer-3 trailing stays config-OFF"}


def _verdict(v):
    a = v.get("actual", {}).get("R"); atr = v.get("atr_2x_trail", {}).get("R")
    ch = v.get("chandelier_22_3", {}).get("R")
    if a is None or atr is None:
        return "insufficient data"
    best_trail = max(x for x in (atr, ch) if x is not None)
    if best_trail < a:
        return f"trailing would have LEFT MONEY (best trail {best_trail}R < actual {a}R) — keep trailing off"
    return f"trailing would have helped this trade (best trail {best_trail}R vs actual {a}R) — single trade, not the policy"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-id", type=int)
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()
    tid = a.trade_id
    if a.sample or tid is None:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT trade_instance_id, count(*) FROM trade_intrabar_bars
                       GROUP BY 1 HAVING count(*) >= 5 ORDER BY 2 DESC LIMIT 1""")
        r = cur.fetchone(); tid = r[0] if r else None
    if tid is None:
        print(json.dumps({"error": "no trade with intrabar bars found"})); return
    print(json.dumps(whatif(tid), indent=2, default=str))


if __name__ == "__main__":
    main()
