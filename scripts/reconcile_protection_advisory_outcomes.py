#!/usr/bin/env python3
"""Phase 193 — Profit-protection advisory close-loop reconciler (learning telemetry).

For every paper trade, links the profit-protection advisory (atm_profit_protection_advisories),
any applied adjustment (paper_protection_adjustment_proposals + audit), and the trade outcome
(paper_trades MFE/MAE/exit/pnl/r) into `protection_advisory_outcomes`.

- CLOSED trade  -> 'final_closed'  outcome (advisory accuracy, profit-left-on-table, give-back).
- OPEN trade with an APPLIED adjustment -> 'interim_open' tracking (operator accepted; profit
  locked; giveback avoided) until it closes.
- CLOSED trade with no advisory -> 'baseline_no_advisory' (honest baseline; advisories started
  2026-06-02, so legacy closes had none).

READ-ONLY on the broker. Writes only the outcomes table. No execution, no stop/order changes.
MFE units are captured raw and FLAGGED (`mfe_units_validated=false`) — they are inconsistent in
the source data (some look like %, some don't), so we do not fabricate a $ "profit left on table".
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_DIR = os.path.join(ROOT, "data/atm/protection_adjustment_audit")


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


def applied_audit_for(trade_id):
    """Scan audit jsonl for an APPLIED action on this trade."""
    if not os.path.isdir(AUDIT_DIR):
        return None
    hit = None
    for fn in sorted(os.listdir(AUDIT_DIR)):
        if not fn.endswith(".jsonl"):
            continue
        for line in open(os.path.join(AUDIT_DIR, fn)):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("trade_id") == trade_id and r.get("status") == "APPLIED":
                hit = r  # keep latest
    return hit


def run(persist=True):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if persist:
        wc = conn.cursor()
        wc.execute(open(os.path.join(ROOT, "migrations/2026_06_02_phase193_advisory_outcomes.sql")).read())
        conn.commit()

    # Phase 194: MFE/give-back sourced from bar-based trade_mfe_analysis (authoritative:
    # money_left in $, mfe_price for %). paper_trades.max_favorable_excursion is %, but is only
    # reliable where a bar analysis exists; elsewhere it is NULL (honestly unknown).
    cur.execute("""select pt.id,pt.symbol,pt.status,pt.entry_price,pt.exit_price,pt.current_price,
                          pt.shares,pt.pnl,pt.pnl_pct,pt.unrealized_pnl,pt.r_multiple,
                          pt.max_favorable_excursion mfe,pt.max_adverse_excursion mae,
                          pt.stop_order_id,pt.current_stop,pt.take_profit_price,pt.closed_at,
                          m.money_left, m.mfe_price
                   from paper_trades pt
                   left join trade_mfe_analysis m on m.trade_id = pt.id
                   order by pt.id""")
    trades = cur.fetchall()

    # advisory per trade (latest)
    cur.execute("""select distinct on (paper_trade_id) paper_trade_id, tradeai_action,
                          hermes_opinion, operator_action_required, audit_json
                   from atm_profit_protection_advisories order by paper_trade_id, created_at desc""")
    adv = {r["paper_trade_id"]: r for r in cur.fetchall()}

    # applied adjustment per trade
    cur.execute("""select trade_id, action, current_stop, proposed_stop,
                          profit_locked_after, giveback_before, giveback_after
                   from paper_protection_adjustment_proposals where status='APPLIED'""")
    applied = {r["trade_id"]: r for r in cur.fetchall()}

    out, counts = [], {"final_closed": 0, "interim_open": 0, "baseline_no_advisory": 0,
                       "accepted": 0, "ignored": 0, "gave_back": 0,
                       "with_bar_mfe": 0, "mfe_unknown": 0}
    wc = conn.cursor()
    for t in trades:
        tid = t["id"]; a = adv.get(tid); ap = applied.get(tid)
        au = applied_audit_for(tid)
        advisory_existed = a is not None
        adjustment_applied = ap is not None or (au is not None)
        closed = t["status"] == "closed"

        # operator decision
        if adjustment_applied:
            operator_decision = "accepted"
        elif advisory_existed and a.get("operator_action_required") and closed:
            operator_decision = "ignored"
        else:
            operator_decision = "none"

        # Phase 194: give-back from AUTHORITATIVE bar analysis (money_left $). Only trades with a
        # bar analysis get a give-back verdict; others are honestly 'unknown' (no fabrication).
        pnl_pct = f(t["pnl_pct"]); mfe = f(t["mfe"])
        money_left = f(t["money_left"]); mfe_price = f(t["mfe_price"])
        has_bar = money_left is not None
        mfe_validated = has_bar
        mfe_source = "bar_analysis" if has_bar else "none"
        if has_bar:
            gave_back = bool(money_left > 0.0)
            plot_usd = round(money_left, 2)
            plot_pct = round((mfe_price - f(t["entry_price"])) / f(t["entry_price"]) * 100
                             - (pnl_pct or 0), 2) if (mfe_price and t["entry_price"]) else None
            if plot_pct is not None:
                plot_pct = max(0.0, plot_pct)
        else:
            gave_back = None       # unknown — no reliable MFE
            plot_usd = None
            plot_pct = None

        # accuracy
        if not advisory_existed:
            accuracy = "baseline_no_advisory"
        elif not closed:
            accuracy = "in_flight"
        else:
            # advisory urged protection; did the trade then give back profit?
            urged = (a.get("tradeai_action") in
                     ("URGENT_PROTECTION_REVIEW", "LOCK_PROFIT_ADVISORY", "TAKE_PROFIT_ADVISORY",
                      "MOVE_TO_BREAKEVEN_ADVISORY"))
            if gave_back is None:
                accuracy = "unknown_no_mfe"   # closed but no reliable MFE to score against
            elif urged:
                accuracy = "confirmed" if gave_back else "contradicted"
            else:
                accuracy = "baseline_no_advisory"

        stop_before = f(ap["current_stop"]) if ap else (f(au["broker_order_before"]["stop_price"]) if au else None)
        stop_after = f(ap["proposed_stop"]) if ap else (f(au["broker_order_after"]["stop_price"]) if au else None)
        giveback_avoided = round(f(ap["giveback_before"]) - f(ap["giveback_after"]), 2) if (ap and ap["giveback_before"] is not None and ap["giveback_after"] is not None) else None

        rec = {
            "trade_id": tid, "symbol": t["symbol"],
            "record_kind": ("final_closed" if closed else ("interim_open" if adjustment_applied else "interim_open" if advisory_existed else "interim_open")),
            "trade_status": t["status"],
            "advisory_existed": advisory_existed,
            "advisory_action": a["tradeai_action"] if a else None,
            "hermes_opinion": a["hermes_opinion"] if a else None,
            "operator_action_required": a["operator_action_required"] if a else None,
            "adjustment_applied": adjustment_applied,
            "adjustment_action": (ap["action"] if ap else (au["action"] if au else None)),
            "stop_before": stop_before, "stop_after": stop_after,
            "operator_decision": operator_decision,
            "entry_price": f(t["entry_price"]), "exit_price": f(t["exit_price"]),
            "current_price": f(t["current_price"]),
            "realized_pnl": f(t["pnl"]) if closed else None,
            "realized_pnl_pct": pnl_pct if closed else None,
            "unrealized_pnl": f(t["unrealized_pnl"]) if not closed else None,
            "r_multiple": f(t["r_multiple"]),
            "mfe_raw": mfe, "mae_raw": f(t["mae"]),
            "profit_locked_by_adjustment": f(ap["profit_locked_after"]) if ap else None,
            "giveback_avoided": giveback_avoided,
            "gave_back_profit": gave_back,
            "profit_left_on_table_pct": plot_pct,
            "profit_left_on_table_usd": plot_usd,
            "mfe_source": mfe_source,
            "take_profit_would_have_helped": (bool(gave_back) and t["take_profit_price"] is None) if (closed and gave_back is not None) else None,
            "trailing_would_have_helped": gave_back if (closed and gave_back is not None) else None,
            "advisory_accuracy": accuracy,
            "mfe_units_validated": mfe_validated,
            "notes": ("MFE from bar analysis (authoritative)." if has_bar
                      else "No bar-based MFE — give-back not scored (honest unknown)."),
        }
        # only persist rows that are interesting: closed trades, or trades with advisory/adjustment
        if not (closed or advisory_existed or adjustment_applied):
            continue
        out.append(rec)
        if rec["record_kind"] == "final_closed":
            counts["final_closed"] += 1
        elif advisory_existed or adjustment_applied:
            counts["interim_open"] += 1
        if not advisory_existed and closed:
            counts["baseline_no_advisory"] += 1
        if operator_decision == "accepted":
            counts["accepted"] += 1
        if operator_decision == "ignored":
            counts["ignored"] += 1
        if gave_back:
            counts["gave_back"] += 1
        if has_bar:
            counts["with_bar_mfe"] += 1
        elif closed:
            counts["mfe_unknown"] += 1

        if persist:
            cols = list(rec.keys())
            wc.execute(f"""insert into protection_advisory_outcomes ({','.join(cols)})
                values ({','.join('%('+c+')s' for c in cols)})
                on conflict (trade_id) do update set
                {','.join(f'{c}=excluded.{c}' for c in cols if c!='trade_id')}, reconciled_at=now()""", rec)
    if persist:
        conn.commit()
    conn.close()
    print(json.dumps({"reconciled": len(out), "counts": counts}, indent=2, default=str))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-persist", action="store_true")
    a = ap.parse_args()
    run(persist=not a.no_persist)
