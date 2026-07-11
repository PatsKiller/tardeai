#!/usr/bin/env python3
"""build_trade_execution_quality.py — replay-aware execution quality (read-only analytics; no trading writes).

Turns real fill timestamps + intraday bars (Alpaca->Schwab, via ohlc_charts) into computed execution metrics:
entry volume confirmation, session-VWAP relation, RSI/MACD at entry, post-entry MFE/MAE, post-exit missed
runner, capture ratio — then deterministic grades that separate OUTCOME (won/lost) from EXECUTION (good/poor).
A green trade can score poor execution. Grok interpretation is layered separately (grok_execution_review.py).

  python3 scripts/build_trade_execution_quality.py --source schwab --limit 20
  python3 scripts/build_trade_execution_quality.py --source paper  --limit 20
  python3 scripts/build_trade_execution_quality.py --trade-key <key>
  python3 scripts/build_trade_execution_quality.py --apply           # default is dry-run
"""
import argparse, json, sys, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ohlc_charts as oc


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _rules():
    import yaml
    return yaml.safe_load((ROOT / "config" / "execution_quality_rules.yaml").read_text())


def _family(strategy, classification):
    s = (strategy or classification or "unknown").lower()
    if "scalp" in s:
        return "momentum_scalp"
    if "gap" in s:
        return "gap_and_go"
    if "orb" in s or "open" in s:
        return "orb"
    if "swing" in s:
        return "swing"
    if "div" in s:
        return "dividend"
    if "day" in s:
        return "day_trade"
    return "unknown"


def _bars_for(symbol, ent, ext, review_min):
    """Multi-day holds -> DAILY bars (entry-context + exit + review days); same-day -> 1-min intraday.
    Returns (bars, source, session_open_or_None, is_daily)."""
    if ext.date() > ent.date():     # SWING / multi-day: daily bars
        start = (ent.date() - dt.timedelta(days=45)).isoformat()    # ~30 trading days of pre-entry context
        end = (ext.date() + dt.timedelta(days=25)).isoformat()      # exit + ~15 trading days for missed-runner
        bars, _ = oc._fetch(symbol, start, end, "1Day")
        src = "alpaca" if bars else None
        if not bars:
            bars = oc._schwab_bars(symbol, start, end, "1Day"); src = "schwab" if bars else None
        if not bars:
            bars = oc._yahoo_bars(symbol, start, end, "1Day"); src = "yahoo" if bars else None
        if not bars:
            bars = oc._price_cache_bars(symbol, start, end); src = "price_cache" if bars else None
        return bars or [], (src or "none"), None, True
    so = oc._sess(ent.date(), 9, 30)                                # SAME-DAY: 1-min intraday
    start = min(so, ent - dt.timedelta(minutes=15)).isoformat()
    # extend to session close so the post-spike FADE is visible (runner_type), without changing the bounded
    # missed-runner window (cutoff stays xi+review_min in compute)
    sess_close = oc._sess(ext.date(), 16, 0)
    end = max(ext + dt.timedelta(minutes=review_min + 5), sess_close + dt.timedelta(minutes=5)).isoformat()
    bars, err = oc._fetch(symbol, start, end, "1Min")
    src = "alpaca"
    if not bars:
        bars = oc._schwab_bars(symbol, start, end, "1Min"); src = "schwab" if bars else None
    if not bars:
        bars = oc._yahoo_bars(symbol, start, end, "1Min"); src = "yahoo" if bars else None
    return bars or [], (src or "none"), so, False


def compute(symbol, ent, ext, entry_price, exit_price, qty, realized_pnl, strategy, classification):
    R = _rules()
    fam = _family(strategy, classification)
    cfg = R["strategies"].get(fam, R["strategies"]["unknown"])
    review_min = int(cfg.get("post_exit_review_min", 60))
    bars, src, so, is_daily = _bars_for(symbol, ent, ext, review_min)
    out = {"strategy_family": fam, "bars_source": src, "bars_count": len(bars), "bar_interval": "1Day" if is_daily else "1Min"}
    if len(bars) < (8 if is_daily else 15):
        out["path_status"] = "NO_INTRADAY_PATH" if not bars else "INSUFFICIENT_BARS"
        return out
    # index bars by UTC datetime
    bt = [dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")) for b in bars]
    has_vol = any((b.get("v") or 0) > 0 for b in bars)
    out["path_status"] = "OK" if has_vol else "NO_VOLUME_DATA"

    def idx_at(ts):
        return min(range(len(bt)), key=lambda i: abs((bt[i] - ts).total_seconds()))

    ei, xi = idx_at(ent), idx_at(ext)
    direction = 1 if (exit_price - entry_price) * (realized_pnl or 0) >= 0 else 1  # round-trips are long

    # ── entry volume confirmation (RVOL) ──
    w = int(cfg["rvol_window"])
    prior = [bars[j].get("v") or 0 for j in range(max(0, ei - w), ei)]
    avg_prior = (sum(prior) / len(prior)) if prior else 0
    entry_vol = bars[ei].get("v") or 0
    rvol = round(entry_vol / avg_prior, 2) if avg_prior else None
    out["entry_volume_ratio"] = rvol
    out["entry_relative_volume_window"] = w
    out["entry_volume_confirmed"] = (rvol is not None and rvol >= cfg["min_entry_rvol"]) if has_vol else None

    # ── session VWAP at entry (intraday only; not meaningful for daily swing bars) ──
    if is_daily:
        out["entry_above_vwap"] = None
        out["entry_vwap_distance_pct"] = None
    else:
        cum_pv = cum_v = 0.0
        for j in range(ei + 1):
            if bt[j] >= so:
                tp = (bars[j]["h"] + bars[j]["l"] + bars[j]["c"]) / 3.0
                cum_pv += tp * (bars[j].get("v") or 0); cum_v += (bars[j].get("v") or 0)
        vwap_e = (cum_pv / cum_v) if cum_v else bars[ei]["c"]
        out["entry_above_vwap"] = bool(entry_price >= vwap_e)
        out["entry_vwap_distance_pct"] = round((entry_price - vwap_e) / vwap_e * 100, 2) if vwap_e else None

    # ── RSI / MACD at entry ──
    closes = [b["c"] for b in bars]
    rsi = oc._rsi(closes); macd = oc._macd(closes)
    out["entry_rsi"] = rsi[ei] if ei < len(rsi) else None
    if ei >= 1 and macd[ei] and macd[ei - 1]:
        out["entry_macd_state"] = "rising" if macd[ei]["hist"] >= macd[ei - 1]["hist"] else "falling"
    else:
        out["entry_macd_state"] = None

    # ── capture = of the move available DURING THE HOLD (entry->exit), how much did you get? ──
    # MFE/MAE and 'available' are measured over the hold ONLY; the post-exit run is a SEPARATE concern
    # (missed-runner, below) — including it here wrongly penalized well-timed exits as 'poor'.
    cutoff = min(len(bars) - 1, xi + (15 if is_daily else review_min))   # daily: ~15 trading days post-exit (for missed-runner)
    hold = bars[ei:xi + 1] or bars[ei:ei + 1]
    hi = max(b["h"] for b in hold); lo = min(b["l"] for b in hold)
    out["mfe_after_entry"] = round(hi - entry_price, 4)      # best price reached WHILE IN the trade
    out["mae_after_entry"] = round(entry_price - lo, 4)
    available = max(hi - entry_price, 0.0001)
    captured = exit_price - entry_price
    out["available_profit"] = round(available, 4); out["captured_profit"] = round(captured, 4)
    out["capture_ratio"] = round(max(0.0, min(1.0, captured / available)), 3)

    # ── post-exit path (missed runner) ──
    post = bars[xi:cutoff + 1]
    p_hi = max(b["h"] for b in post) if post else exit_price
    p_hi_i = max(range(xi, cutoff + 1), key=lambda i: bars[i]["h"]) if post else xi
    out["post_exit_high"] = round(p_hi, 4)
    out["post_exit_high_time"] = bt[p_hi_i].isoformat()
    out["mfe_after_exit"] = round(p_hi - exit_price, 4)
    out["mfe_after_exit_pct"] = round((p_hi - exit_price) / exit_price * 100, 2) if exit_price else None
    out["missed_profit"] = round(max(0.0, p_hi - exit_price) * (qty or 0), 2)
    out["missed_profit_pct"] = out["mfe_after_exit_pct"]

    # ── runner classification: did the post-exit spike SUSTAIN (trend) or FADE back (parabolic pump)? ──
    # From the post-exit high forward to the end of the fetched window (extended to session close intraday),
    # how much of the spike was given back? Trend = holds; parabolic pump = spikes then collapses (a trap).
    spike = p_hi - exit_price
    after_hi = bars[p_hi_i:]
    trough_after = min((b["l"] for b in after_hi), default=p_hi)
    gave_back = round((p_hi - trough_after) / spike, 3) if spike > 0 else 0.0
    out["post_exit_gave_back_ratio"] = gave_back
    mpct = out["mfe_after_exit_pct"] or 0
    if spike <= 0 or mpct < 15:
        out["runner_type"] = "none"
    elif is_daily:
        # SWING: the post-exit high was reached over days. A retrace here = the trend topped (scale-out
        # lesson), NOT an intraday pump — holding still captured real upside on the way up.
        out["runner_type"] = "sustained_trend" if gave_back < 0.5 else "trend_top"
    else:
        # SCALP/intraday: a big same-session spike that collapses is a parabolic pump-and-dump (a trap).
        if mpct >= 40 and gave_back >= 0.6:
            out["runner_type"] = "parabolic_pump"
        elif gave_back < 0.4:
            out["runner_type"] = "sustained_trend"
        else:
            out["runner_type"] = "faded"

    # ── deterministic flags + grades (OUTCOME separate from EXECUTION) ──
    realized = realized_pnl if realized_pnl is not None else captured * (qty or 0)
    out["outcome_grade"] = "win" if realized > 0 else ("loss" if realized < 0 else "breakeven")
    runner = (p_hi - exit_price) > cfg["runner_mult"] * max(captured, 0.0001)
    out["no_volume_entry_flag"] = bool(has_vol and rvol is not None and rvol < cfg["min_entry_rvol"])
    out["early_entry_flag"] = bool(has_vol and rvol is not None and rvol < cfg["early_entry_rvol"])
    out["late_entry_flag"] = bool(out["entry_vwap_distance_pct"] is not None and out["entry_vwap_distance_pct"] > 4)
    out["premature_exit_flag"] = bool(out["capture_ratio"] < cfg["premature_capture"] and runner)
    out["missed_runner_flag"] = bool(runner)

    out["entry_timing_grade"] = "early" if out["no_volume_entry_flag"] else ("late" if out["late_entry_flag"] else "ok")
    out["exit_timing_grade"] = ("premature" if out["premature_exit_flag"]
                                else "early" if out["capture_ratio"] < cfg["min_capture_ratio"] else "ok")
    out["missed_opportunity_grade"] = ("severe" if runner and out["mfe_after_exit_pct"] and out["mfe_after_exit_pct"] > 25
                                       else "moderate" if runner else "minimal")
    bad = sum([out["no_volume_entry_flag"], out["premature_exit_flag"], out["capture_ratio"] < cfg["min_capture_ratio"]])
    out["execution_grade"] = ("poor" if bad >= 2 else "weak" if bad == 1
                              else "good" if (out["capture_ratio"] >= 0.7 and out.get("entry_volume_confirmed")) else "ok")
    out["discipline_grade"] = "violated" if (out["no_volume_entry_flag"] and cfg.get("require_above_vwap") and not out["entry_above_vwap"]) else "followed"
    viol = []
    if cfg.get("require_above_vwap") and not out["entry_above_vwap"]:
        viol.append("entry_below_vwap")
    if out["no_volume_entry_flag"]:
        viol.append("entry_without_volume_confirmation")
    if out["premature_exit_flag"]:
        viol.append("premature_exit_before_runner")
    # ── multi-day post-exit follow-through (the BIG missed runner — e.g. RGNT ran up over the following days) ──
    try:
        d_start = (ext + dt.timedelta(days=1)).date().isoformat()
        d_end = (ext + dt.timedelta(days=12)).date().isoformat()
        dbars, _e = oc._fetch(symbol, d_start, d_end, "1Day")
        if dbars:
            md_hi = max(b["h"] for b in dbars)
            out["post_exit_high_10d"] = round(md_hi, 4)
            out["missed_10d_pct"] = round((md_hi - exit_price) / exit_price * 100, 2) if exit_price else None
            if out["missed_10d_pct"] and out["missed_10d_pct"] > 25:        # a big multi-day runner was left behind
                out["missed_opportunity_grade"] = "severe"
                out["missed_runner_flag"] = True
                if out["no_volume_entry_flag"] or out["premature_exit_flag"]:
                    out["execution_grade"] = "poor"                          # early/premature + big runner = poor
    except Exception:
        pass

    out["strategy_rule_violations"] = viol
    md = f" | 10d post-exit +{out.get('missed_10d_pct')}%" if out.get("missed_10d_pct") else ""
    out["computed_summary"] = (f"{out['outcome_grade'].upper()} outcome / {out['execution_grade'].upper()} execution — "
                               f"entry RVOL {rvol}, capture {int(out['capture_ratio']*100)}%, "
                               f"{out['missed_opportunity_grade']} missed{md}.")
    return out


def _rows(source, limit, trade_key):
    conn = _conn(); cur = conn.cursor()
    if source == "schwab":
        q = """SELECT 'srt:'||id AS trade_key, account, symbol, entry_time, exit_time, entry_price, exit_price,
                      qty, net_pnl, COALESCE(strategy_tag, classification), classification
               FROM schwab_round_trips WHERE basis_status IS DISTINCT FROM 'basis_unknown' AND entry_time IS NOT NULL
                 AND exit_time IS NOT NULL AND canary IS NOT TRUE"""
        if trade_key:
            q += f" AND 'srt:'||id = '{trade_key}'"
        q += f" ORDER BY exit_time DESC LIMIT {int(limit)}"
        cur.execute(q)
        for r in cur.fetchall():
            yield {"trade_key": r[0], "source": "schwab_round_trip", "broker": "schwab", "account": r[1],
                   "symbol": r[2], "ent": r[3], "ext": r[4], "entry_price": float(r[5]) if r[5] else None,
                   "exit_price": float(r[6]) if r[6] else None, "qty": float(r[7]) if r[7] else None,
                   "realized_pnl": float(r[8]) if r[8] is not None else None, "strategy": r[9], "classification": r[10]}
    elif source == "paper":
        q = """SELECT 'pt:'||id, symbol, entry_time, COALESCE(exit_time, closed_at), entry_price, exit_price,
                      shares, pnl, strategy_id
               FROM paper_trades WHERE status='closed' AND exit_price IS NOT NULL AND entry_time IS NOT NULL"""
        if trade_key:
            q += f" AND 'pt:'||id = '{trade_key}'"
        q += f" ORDER BY COALESCE(exit_time, closed_at) DESC NULLS LAST LIMIT {int(limit)}"
        cur.execute(q)
        for r in cur.fetchall():
            yield {"trade_key": r[0], "source": "paper_trade", "broker": "alpaca", "account": "alpaca_paper",
                   "symbol": r[1], "ent": r[2], "ext": r[3], "entry_price": float(r[4]) if r[4] else None,
                   "exit_price": float(r[5]) if r[5] else None, "qty": float(r[6]) if r[6] else None,
                   "realized_pnl": float(r[7]) if r[7] is not None else None, "strategy": r[8], "classification": r[8]}


def run(source="schwab", limit=20, trade_key=None, apply=False):
    conn = _conn(); cur = conn.cursor()
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "source": source, "rows": []}
    for t in _rows(source, limit, trade_key):
        if not (t["ent"] and t["ext"] and t["entry_price"] and t["exit_price"]):
            continue
        try:
            m = compute(t["symbol"], t["ent"], t["ext"], t["entry_price"], t["exit_price"], t["qty"],
                        t["realized_pnl"], t["strategy"], t["classification"])
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            report["rows"].append({"trade_key": t["trade_key"], "symbol": t["symbol"], "error": str(e)[:120]})
            continue
        hold_min = None
        if t.get("ent") and t.get("ext"):
            try:
                hold_min = int((t["ext"] - t["ent"]).total_seconds() / 60)
            except Exception:
                hold_min = None
        rec = {**t, **m, "hold_minutes": hold_min}
        report["rows"].append({"trade_key": t["trade_key"], "symbol": t["symbol"], "path": m.get("path_status"),
                               "outcome": m.get("outcome_grade"), "execution": m.get("execution_grade"),
                               "entry_timing": m.get("entry_timing_grade"), "exit_timing": m.get("exit_timing_grade"),
                               "capture": m.get("capture_ratio"), "rvol": m.get("entry_volume_ratio"),
                               "missed_pct": m.get("mfe_after_exit_pct"), "summary": m.get("computed_summary")})
        if apply and m.get("path_status"):
            _defaults = {k: None for k in (
                "entry_volume_confirmed", "entry_volume_ratio", "entry_relative_volume_window", "entry_above_vwap",
                "entry_vwap_distance_pct", "entry_macd_state", "entry_rsi", "entry_timing_grade", "exit_timing_grade",
                "execution_grade", "outcome_grade", "discipline_grade", "missed_opportunity_grade", "mfe_after_entry",
                "mae_after_entry", "mfe_after_exit", "mfe_after_exit_pct", "post_exit_high", "post_exit_high_time",
                "capture_ratio", "available_profit", "captured_profit", "missed_profit", "missed_profit_pct",
                "premature_exit_flag", "early_entry_flag", "late_entry_flag", "no_volume_entry_flag", "computed_summary",
                "runner_type", "post_exit_gave_back_ratio")}
            rec = {**_defaults, **rec}
            cur.execute("""INSERT INTO trade_execution_quality
                (trade_key,source,broker,account,symbol,strategy_id,entry_time,exit_time,entry_price,exit_price,qty,
                 realized_pnl,hold_minutes,bar_interval,bars_source,bars_count,path_status,entry_volume_confirmed,
                 entry_volume_ratio,entry_relative_volume_window,entry_above_vwap,entry_vwap_distance_pct,
                 entry_macd_state,entry_rsi,entry_timing_grade,exit_timing_grade,execution_grade,outcome_grade,
                 discipline_grade,missed_opportunity_grade,mfe_after_entry,mae_after_entry,mfe_after_exit,
                 mfe_after_exit_pct,post_exit_high,post_exit_high_time,capture_ratio,available_profit,captured_profit,
                 missed_profit,missed_profit_pct,premature_exit_flag,early_entry_flag,late_entry_flag,
                 no_volume_entry_flag,strategy_rule_violations,computed_summary,runner_type,post_exit_gave_back_ratio,updated_at)
                VALUES (%(trade_key)s,%(source)s,%(broker)s,%(account)s,%(symbol)s,%(strategy)s,%(ent)s,%(ext)s,
                 %(entry_price)s,%(exit_price)s,%(qty)s,%(realized_pnl)s,%(hold_minutes)s,%(bar_interval)s,%(bars_source)s,%(bars_count)s,
                 %(path_status)s,%(entry_volume_confirmed)s,%(entry_volume_ratio)s,%(entry_relative_volume_window)s,
                 %(entry_above_vwap)s,%(entry_vwap_distance_pct)s,%(entry_macd_state)s,%(entry_rsi)s,
                 %(entry_timing_grade)s,%(exit_timing_grade)s,%(execution_grade)s,%(outcome_grade)s,
                 %(discipline_grade)s,%(missed_opportunity_grade)s,%(mfe_after_entry)s,%(mae_after_entry)s,
                 %(mfe_after_exit)s,%(mfe_after_exit_pct)s,%(post_exit_high)s,%(post_exit_high_time)s,
                 %(capture_ratio)s,%(available_profit)s,%(captured_profit)s,%(missed_profit)s,%(missed_profit_pct)s,
                 %(premature_exit_flag)s,%(early_entry_flag)s,%(late_entry_flag)s,%(no_volume_entry_flag)s,
                 %(violjson)s,%(computed_summary)s,%(runner_type)s,%(post_exit_gave_back_ratio)s,NOW())
                ON CONFLICT (trade_key, source) DO UPDATE SET
                 broker=EXCLUDED.broker, account=EXCLUDED.account, symbol=EXCLUDED.symbol,
                 strategy_id=EXCLUDED.strategy_id, entry_time=EXCLUDED.entry_time, exit_time=EXCLUDED.exit_time,
                 entry_price=EXCLUDED.entry_price, exit_price=EXCLUDED.exit_price, qty=EXCLUDED.qty,
                 realized_pnl=EXCLUDED.realized_pnl, hold_minutes=EXCLUDED.hold_minutes,
                 bar_interval=EXCLUDED.bar_interval, bars_source=EXCLUDED.bars_source, bars_count=EXCLUDED.bars_count,
                 path_status=EXCLUDED.path_status, entry_volume_confirmed=EXCLUDED.entry_volume_confirmed,
                 entry_volume_ratio=EXCLUDED.entry_volume_ratio,
                 entry_relative_volume_window=EXCLUDED.entry_relative_volume_window,
                 entry_above_vwap=EXCLUDED.entry_above_vwap, entry_vwap_distance_pct=EXCLUDED.entry_vwap_distance_pct,
                 entry_macd_state=EXCLUDED.entry_macd_state, entry_rsi=EXCLUDED.entry_rsi,
                 entry_timing_grade=EXCLUDED.entry_timing_grade, exit_timing_grade=EXCLUDED.exit_timing_grade,
                 execution_grade=EXCLUDED.execution_grade, outcome_grade=EXCLUDED.outcome_grade,
                 discipline_grade=EXCLUDED.discipline_grade, missed_opportunity_grade=EXCLUDED.missed_opportunity_grade,
                 mfe_after_entry=EXCLUDED.mfe_after_entry, mae_after_entry=EXCLUDED.mae_after_entry,
                 mfe_after_exit=EXCLUDED.mfe_after_exit, mfe_after_exit_pct=EXCLUDED.mfe_after_exit_pct,
                 post_exit_high=EXCLUDED.post_exit_high, post_exit_high_time=EXCLUDED.post_exit_high_time,
                 capture_ratio=EXCLUDED.capture_ratio, available_profit=EXCLUDED.available_profit,
                 captured_profit=EXCLUDED.captured_profit, missed_profit=EXCLUDED.missed_profit,
                 missed_profit_pct=EXCLUDED.missed_profit_pct, premature_exit_flag=EXCLUDED.premature_exit_flag,
                 early_entry_flag=EXCLUDED.early_entry_flag, late_entry_flag=EXCLUDED.late_entry_flag,
                 no_volume_entry_flag=EXCLUDED.no_volume_entry_flag,
                 strategy_rule_violations=EXCLUDED.strategy_rule_violations,
                 computed_summary=EXCLUDED.computed_summary, runner_type=EXCLUDED.runner_type,
                 post_exit_gave_back_ratio=EXCLUDED.post_exit_gave_back_ratio, updated_at=NOW()""",
                {**rec, "violjson": json.dumps(m.get("strategy_rule_violations", []))})
            conn.commit()
    print(json.dumps(report, indent=2, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="schwab")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--trade-key")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.source, a.limit, a.trade_key, a.apply)


if __name__ == "__main__":
    main()
