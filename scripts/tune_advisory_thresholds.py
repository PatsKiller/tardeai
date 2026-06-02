#!/usr/bin/env python3
"""Phase 198 — Profit-protection advisory threshold tuning framework (advisory; no auto-apply).

Backtests the 191D advisory thresholds against bar-validated closed-trade outcomes by replaying
the EXACT live scoring logic (`profit_protection_advisory.score`, with its module globals
monkeypatched per candidate) at each trade's MFE-peak decision point, then measuring how well each
threshold set would have flagged trades that went on to give back profit.

Reuses the live `score()` (no logic divergence). Read-only on the broker. Writes only the tuning
summary table. Recommends thresholds — does NOT auto-apply them (operator decision; advisory params,
not GO/WAIT).
"""
import os, sys, json
from datetime import datetime, timezone
import itertools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import profit_protection_advisory as ppa  # live scoring model

# protection-advising actions (operator would be prompted to protect)
ADVISE = {"URGENT_PROTECTION_REVIEW", "LOCK_PROFIT_ADVISORY", "MOVE_TO_BREAKEVEN_ADVISORY",
          "TAKE_PROFIT_ADVISORY", "TRAILING_STOP_ADVISORY"}

# sweep grid (GAIN_PCT_REVIEW and QUOTE_FRESH_MIN held; they are not the give-back levers)
GRID = {
    "GAIN_PCT_LOCK": [3.0, 5.0, 6.0, 8.0, 10.0],
    "LARGE_GAIN_USD": [100.0, 150.0, 250.0, 400.0],
    "GIVEBACK_FRACTION_URGENT": [0.3, 0.4, 0.5, 0.6],
}
CURRENT = {"GAIN_PCT_LOCK": ppa.GAIN_PCT_LOCK, "LARGE_GAIN_USD": ppa.LARGE_GAIN_USD,
           "GIVEBACK_FRACTION_URGENT": ppa.GIVEBACK_FRACTION_URGENT}


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2, psycopg2.extras
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def f(x):
    return float(x) if x is not None else None


def build_cases(conn):
    """Reconstruct each measurable closed trade's MFE-peak decision point + ground truth."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        select pt.id, pt.symbol, pt.strategy_id, pt.entry_price, pt.shares,
               pt.stop_loss, pt.current_stop, pt.take_profit_price,
               m.mfe_price, m.money_left,
               o.gave_back_profit, o.profit_left_on_table_usd
        from paper_trades pt
        join trade_mfe_analysis m on m.trade_id = pt.id
        left join protection_advisory_outcomes o on o.trade_id = pt.id
        where pt.status='closed' and pt.entry_price > 0 and m.mfe_price is not null
        order by pt.id""")
    cases = []
    for r in cur.fetchall():
        entry = f(r["entry_price"]); sh = int(r["shares"] or 0); peak = f(r["mfe_price"])
        stop = f(r["stop_loss"]) or f(r["current_stop"])
        if not (entry and sh and peak):
            continue
        locks = bool(stop and stop > entry)
        giveback = round((peak - (stop if stop else entry)) * sh, 2)
        audit = {
            "quote_fresh": True,
            "unrealized_pct": round((peak - entry) / entry * 100, 2),
            "unrealized_pnl": round((peak - entry) * sh, 2),
            "stop_locks_profit": locks,
            "profit_locked_usd": round((stop - entry) * sh, 2) if locks else 0.0,
            "take_profit_exists": r["take_profit_price"] is not None,
            "giveback_to_stop_usd": giveback,
            "current_price": peak, "current_broker_stop": stop, "shares": sh,
            "planned_stop": stop, "strategy": r["strategy_id"] or "",
            "trailing_threshold_met": False,
        }
        cases.append({
            "id": r["id"], "symbol": r["symbol"], "audit": audit,
            "gave_back": bool(r["gave_back_profit"]),
            "left_usd": f(r["profit_left_on_table_usd"]) or 0.0,
        })
    return cases


def evaluate(cases, thresholds):
    """Monkeypatch the live model's globals and score every case at its peak."""
    ppa.GAIN_PCT_LOCK = thresholds["GAIN_PCT_LOCK"]
    ppa.LARGE_GAIN_USD = thresholds["LARGE_GAIN_USD"]
    ppa.GIVEBACK_FRACTION_URGENT = thresholds["GIVEBACK_FRACTION_URGENT"]
    gb = [c for c in cases if c["gave_back"]]
    tp = fp = 0
    missed_usd = 0.0
    flagged = 0
    for c in cases:
        action, *_ = ppa.score(c["audit"])
        advise = action in ADVISE
        if advise:
            flagged += 1
        if c["gave_back"]:
            if advise:
                tp += 1
            else:
                missed_usd += c["left_usd"]
        elif advise:
            fp += 1
    capture = round(100 * tp / len(gb), 1) if gb else None
    return {"capture_pct": capture, "flagged": flagged, "flag_rate_pct": round(100 * flagged / len(cases), 1) if cases else None,
            "tp": tp, "fp": fp, "giveback_total": len(gb), "missed_giveback_usd": round(missed_usd, 2)}


def run(persist=True):
    load_env()
    conn = db()
    cases = build_cases(conn)
    # current thresholds baseline
    current_perf = evaluate(cases, CURRENT)
    # full sweep
    results = []
    for gl, lg, gf in itertools.product(GRID["GAIN_PCT_LOCK"], GRID["LARGE_GAIN_USD"], GRID["GIVEBACK_FRACTION_URGENT"]):
        th = {"GAIN_PCT_LOCK": gl, "LARGE_GAIN_USD": lg, "GIVEBACK_FRACTION_URGENT": gf}
        perf = evaluate(cases, th)
        results.append({"thresholds": th, **perf})
    # restore live globals
    ppa.GAIN_PCT_LOCK = CURRENT["GAIN_PCT_LOCK"]; ppa.LARGE_GAIN_USD = CURRENT["LARGE_GAIN_USD"]
    ppa.GIVEBACK_FRACTION_URGENT = CURRENT["GIVEBACK_FRACTION_URGENT"]
    # recommend: max capture, then lowest flag_rate (least over-flagging), then lowest missed_$
    ranked = sorted(results, key=lambda r: (-(r["capture_pct"] or 0), r["flag_rate_pct"] or 0, r["missed_giveback_usd"]))
    recommended = ranked[0]

    out = {"run_at": datetime.now(timezone.utc).isoformat(),
           "cases": len(cases), "giveback_cases": sum(1 for c in cases if c["gave_back"]),
           "current_thresholds": CURRENT, "current_performance": current_perf,
           "recommended_thresholds": recommended["thresholds"],
           "recommended_performance": {k: recommended[k] for k in ("capture_pct", "flag_rate_pct", "tp", "fp", "missed_giveback_usd")},
           "note": "Advisory recommendation only — thresholds are advisory-model params (191D), "
                   "NOT GO/WAIT. Operator applies manually. Small sample; revisit as advised trades close."}
    if persist:
        cur = conn.cursor()
        cur.execute("""create table if not exists advisory_threshold_tuning (
            id bigserial primary key, run_at timestamptz default now(),
            cases int, giveback_cases int,
            current_thresholds jsonb, current_performance jsonb,
            recommended_thresholds jsonb, recommended_performance jsonb, full_sweep jsonb)""")
        cur.execute("""insert into advisory_threshold_tuning
            (cases,giveback_cases,current_thresholds,current_performance,recommended_thresholds,recommended_performance,full_sweep)
            values (%s,%s,%s,%s,%s,%s,%s)""",
            (out["cases"], out["giveback_cases"], json.dumps(CURRENT), json.dumps(current_perf),
             json.dumps(recommended["thresholds"]), json.dumps(out["recommended_performance"]),
             json.dumps(ranked[:10])))
        conn.commit()
    conn.close()
    out["top_sweep"] = ranked[:6]
    print(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    run(persist="--no-persist" not in sys.argv)
