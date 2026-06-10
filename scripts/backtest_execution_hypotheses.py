#!/usr/bin/env python3
"""backtest_execution_hypotheses.py — test alternative entry/exit rules vs actual fills (EVIDENCE ONLY).

Replays each trade's intraday bars (Alpaca->Schwab via ohlc_charts) and simulates rule variants, comparing
per-share P&L to the actual fill. NEVER alters live strategy configs — output is evidence for the operator.
Variants: volume_confirmed_entry, hold_above_vwap, macd_rollover_exit.

  python3 scripts/backtest_execution_hypotheses.py --source schwab --limit 30 --apply
  python3 scripts/backtest_execution_hypotheses.py --source paper --limit 30 --apply
Dry-run by default. Aggregates by strategy+hypothesis with a do-not-graft flag when the sample is too small.
"""
import argparse, json, sys, datetime as dt, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ohlc_charts as oc
import build_trade_execution_quality as beq

MIN_SAMPLE = 5   # below this, do_not_graft


def _intraday(symbol, ent, ext):
    so = oc._sess(ent.date(), 9, 30)
    start = min(so, ent - dt.timedelta(minutes=15)).isoformat()
    end = (ext + dt.timedelta(minutes=60)).isoformat()
    bars, _ = oc._fetch(symbol, start, end, "1Min")
    if not bars:
        bars = oc._schwab_bars(symbol, start, end, "1Min")
    return bars or [], so


def _vwap_series(bars, so):
    out, pv, v = [], 0.0, 0.0
    for b in bars:
        bt = dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
        if bt >= so:
            tp = (b["h"] + b["l"] + b["c"]) / 3.0
            pv += tp * (b.get("v") or 0); v += (b.get("v") or 0)
        out.append((pv / v) if v else b["c"])
    return out


def hypotheses(symbol, ent, ext, entry_price, exit_price, rvol_window=10, min_rvol=2.0):
    bars, so = _intraday(symbol, ent, ext)
    if len(bars) < 20:
        return None
    bt = [dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")) for b in bars]
    ei = min(range(len(bt)), key=lambda i: abs((bt[i] - ent).total_seconds()))
    xi = min(range(len(bt)), key=lambda i: abs((bt[i] - ext).total_seconds()))
    actual = exit_price - entry_price
    vwap = _vwap_series(bars, so)
    closes = [b["c"] for b in bars]
    macd = oc._macd(closes)
    res = {}

    # 1) volume_confirmed_entry: enter at the first bar from actual entry where RVOL >= min_rvol; exit unchanged
    new_ei = None
    for i in range(ei, xi + 1):
        prior = [bars[j].get("v") or 0 for j in range(max(0, i - rvol_window), i)]
        ap = (sum(prior) / len(prior)) if prior else 0
        if ap and (bars[i].get("v") or 0) / ap >= min_rvol:
            new_ei = i; break
    if new_ei is not None:
        v_pnl = exit_price - bars[new_ei]["c"]
        res["volume_confirmed_entry"] = (True, round(v_pnl, 4),
                                         {"new_entry": round(bars[new_ei]["c"], 4), "delayed_bars": new_ei - ei})
    else:
        res["volume_confirmed_entry"] = (False, None, {"reason": "no volume-confirmed bar in window (would skip)"})

    # 2) hold_above_vwap: enter at actual entry; exit on the first close below session VWAP after entry
    v_exit = None
    for i in range(ei + 1, len(bars)):
        if bars[i]["c"] < vwap[i]:
            v_exit = bars[i]["c"]; v_exit_i = i; break
    if v_exit is None:
        v_exit, v_exit_i = bars[-1]["c"], len(bars) - 1   # held to window end (stayed above VWAP)
    res["hold_above_vwap"] = (True, round(v_exit - entry_price, 4),
                              {"variant_exit": round(v_exit, 4), "held_bars_vs_actual": v_exit_i - xi})

    # 3) macd_rollover_exit: enter at actual entry; exit when MACD hist crosses + -> - after entry
    m_exit = None
    for i in range(ei + 1, len(bars)):
        if macd[i] and macd[i - 1] and macd[i - 1]["hist"] > 0 >= macd[i]["hist"]:
            m_exit = bars[i]["c"]; m_exit_i = i; break
    if m_exit is None:
        m_exit, m_exit_i = bars[-1]["c"], len(bars) - 1
    res["macd_rollover_exit"] = (True, round(m_exit - entry_price, 4),
                                 {"variant_exit": round(m_exit, 4), "held_bars_vs_actual": m_exit_i - xi})

    return {"actual_pnl_ps": round(actual, 4), "variants": res}


def run(source="schwab", limit=30, apply=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    agg = collections.defaultdict(lambda: {"n": 0, "improved": 0, "delta_sum": 0.0})
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "source": source, "trades": 0, "rows": 0}
    for t in beq._rows(source, limit, None):
        if not (t["ent"] and t["ext"] and t["entry_price"] and t["exit_price"]):
            continue
        fam = beq._family(t["strategy"], t["classification"])
        cfg = beq._rules()["strategies"].get(fam, beq._rules()["strategies"]["unknown"])
        try:
            h = hypotheses(t["symbol"], t["ent"], t["ext"], t["entry_price"], t["exit_price"],
                           int(cfg["rvol_window"]), float(cfg["min_entry_rvol"]) or 1.5)
        except Exception:
            h = None
        if not h:
            continue
        report["trades"] += 1
        for name, (applicable, vpnl, detail) in h["variants"].items():
            improved = bool(applicable and vpnl is not None and vpnl > h["actual_pnl_ps"])
            delta = round((vpnl - h["actual_pnl_ps"]), 4) if (applicable and vpnl is not None) else None
            key = (t["strategy"] or fam, name)
            if applicable and delta is not None:
                agg[key]["n"] += 1; agg[key]["improved"] += int(improved); agg[key]["delta_sum"] += delta
            report["rows"] += 1
            if apply:
                cur.execute("""INSERT INTO trade_execution_hypothesis_results
                    (trade_key,source,symbol,strategy_id,hypothesis,actual_pnl_ps,variant_pnl_ps,delta_ps,improved,applicable,detail)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (trade_key,source,hypothesis) DO UPDATE SET variant_pnl_ps=EXCLUDED.variant_pnl_ps,
                      delta_ps=EXCLUDED.delta_ps, improved=EXCLUDED.improved, detail=EXCLUDED.detail""",
                    (t["trade_key"], t["source"], t["symbol"], t["strategy"], name, h["actual_pnl_ps"],
                     vpnl, delta, improved, applicable, json.dumps(detail)))
        if apply:
            conn.commit()
    report["aggregate"] = [{"strategy": k[0], "hypothesis": k[1], "sample": v["n"],
                            "improved_pct": round(100 * v["improved"] / v["n"]) if v["n"] else None,
                            "avg_delta_ps": round(v["delta_sum"] / v["n"], 4) if v["n"] else None,
                            "do_not_graft": v["n"] < MIN_SAMPLE} for k, v in sorted(agg.items())]
    print(json.dumps(report, indent=2, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="schwab")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.source, a.limit, a.apply)


if __name__ == "__main__":
    main()
